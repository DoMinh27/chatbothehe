import json
import unittest
from unittest.mock import patch

import httpx
from google import genai
from google.genai import types

from olpai.gemini import GeminiGateway
from olpai.models import THINKING_HEADROOM, CountingFailed, DefinitelyRejected, UnknownUsage


def response(text="answer", output=6, thinking=3, prompt=10, **extra):
    body = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                        "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": output,
                          "thoughtsTokenCount": thinking,
                          "totalTokenCount": prompt + output + thinking},
        "modelVersion": "gemini-3.6-flash",
    }
    body.update(extra)
    return body


class GeminiTests(unittest.TestCase):
    def gateway(self, handler):
        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        real_client = genai.Client
        def factory(**kwargs):
            kwargs["http_options"].httpx_client = http_client
            return real_client(**kwargs)
        with patch("olpai.gemini.genai.Client", side_effect=factory):
            gateway = GeminiGateway("test-not-a-real-key")
        self.addCleanup(gateway.client.close)
        return gateway

    def test_real_sdk_wire_contract_and_no_tools(self):
        requests = []
        text = "Tiếng Việt 🙂\n    print('a')\n"
        def handler(request):
            requests.append(json.loads(request.content))
            if request.url.path.endswith(":countTokens"):
                return httpx.Response(200, json={"totalTokens": 17})
            return httpx.Response(200, json=response())
        gateway = self.gateway(handler)
        self.assertEqual(gateway.count_text("gemini-3.5-flash", text), 17)
        result = gateway.generate("gemini-3.5-flash", [
            {"role": "user", "content": text},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "continue"},
        ], 23)
        self.assertEqual(result.actual_model, "gemini-3.6-flash")
        self.assertEqual(requests[0]["contents"][0]["parts"][0]["text"], text)
        body = requests[1]
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 23 + THINKING_HEADROOM)
        self.assertEqual(body["generationConfig"]["candidateCount"], 1)
        thinking = body["generationConfig"]["thinkingConfig"]
        # Google GenAI 2.33 serializes the nested field in protobuf snake_case.
        self.assertFalse(thinking.get("includeThoughts", thinking.get("include_thoughts")))
        self.assertEqual(thinking.get("thinkingLevel", thinking.get("thinking_level")), "MINIMAL")
        self.assertNotIn("thinkingBudget", thinking)
        self.assertNotIn("thinking_budget", thinking)
        self.assertNotIn("systemInstruction", body)
        self.assertFalse(body.get("tools"))
        self.assertEqual([m["role"] for m in body["contents"]], ["user", "model", "user"])

    def test_no_sdk_retries_on_429_or_500(self):
        for code, expected in [(429, DefinitelyRejected), (500, UnknownUsage), (408, UnknownUsage)]:
            with self.subTest(code=code):
                calls = []
                def handler(request):
                    calls.append(request)
                    return httpx.Response(code, json={"error": {"code": code, "message": "test"}})
                gateway = self.gateway(handler)
                with self.assertRaises(expected):
                    gateway.generate("gemini-3.5-flash", [{"role": "user", "content": "x"}], 100)
                self.assertEqual(len(calls), 1)

    def test_missing_usage_locks_instead_of_estimating(self):
        parsed = types.GenerateContentResponse.model_validate(response(usageMetadata=None))
        with self.assertRaises(UnknownUsage):
            GeminiGateway.parse_response(parsed)

    def test_thought_summaries_are_never_returned(self):
        body = response()
        body["candidates"][0]["content"]["parts"].insert(0, {"text": "hidden thought", "thought": True})
        parsed = types.GenerateContentResponse.model_validate(body)
        self.assertEqual(GeminiGateway.parse_response(parsed).text, "answer")

    def test_continuation_does_not_generate_another_response(self):
        calls = []
        def handler(request):
            calls.append(request)
            body = response()
            body["candidates"][0]["finishReason"] = "CONTINUATION"
            body["continuationToken"] = "must-not-be-followed"
            return httpx.Response(200, json=body)
        gateway = self.gateway(handler)
        result = gateway.generate("gemini-3.5-flash", [{"role": "user", "content": "x"}], 100)
        self.assertEqual(result.finish_reason, "CONTINUATION")
        self.assertEqual(len(calls), 1)

    def test_empty_output_still_counts_thinking(self):
        parsed = types.GenerateContentResponse.model_validate(response(text="", output=0, thinking=100))
        result = GeminiGateway.parse_response(parsed)
        self.assertEqual((result.text, result.thinking_tokens), ("", 100))

    def test_inconsistent_usage_is_rejected(self):
        for body in [
            response(usageMetadata={"candidatesTokenCount": 5}),
            (response(usageMetadata={"promptTokenCount": 10, "totalTokenCount": 30,
                                     "candidatesTokenCount": 6, "thoughtsTokenCount": 3})),
        ]:
            with self.subTest(body=body):
                with self.assertRaises(UnknownUsage):
                    GeminiGateway.parse_response(types.GenerateContentResponse.model_validate(body))

    def test_thinking_over_remaining_does_not_discard_visible_answer(self):
        gateway = self.gateway(lambda request: httpx.Response(
            200, json=response(text="OK", output=2, thinking=5000)
        ))
        result = gateway.generate("gemini-3.5-flash", [{"role": "user", "content": "x"}], 2)
        self.assertEqual((result.text, result.output_tokens, result.thinking_tokens), ("OK", 2, 5000))

    def test_overlong_visible_answer_keeps_only_verified_unicode_prefix(self):
        requests = []
        text = "Việt🙂\n```python\n    print('xin chào')\n```"
        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            if request.url.path.endswith(":countTokens"):
                prefix = body["contents"][0]["parts"][0]["text"]
                return httpx.Response(200, json={"totalTokens": len(prefix)})
            return httpx.Response(200, json=response(text=text, output=len(text), thinking=80))
        gateway = self.gateway(handler)
        result = gateway.generate("gemini-3.5-flash", [{"role": "user", "content": "x"}], 5)
        self.assertEqual(result.text, "Việt🙂")
        self.assertEqual(result.output_tokens, 5)
        self.assertEqual(result.thinking_tokens, 80)
        self.assertEqual(result.finish_reason, "LOCAL_TOKEN_LIMIT")
        self.assertEqual(sum("generationConfig" in request for request in requests), 1)

    def test_count_failure_is_safe_and_does_not_expose_provider_details(self):
        gateway = self.gateway(lambda request: httpx.Response(403, json={
            "error": {"code": 403, "message": "private credentials"},
        }))
        with self.assertRaises(CountingFailed) as caught:
            gateway.count_text("gemini-3.5-flash", "hello")
        self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
