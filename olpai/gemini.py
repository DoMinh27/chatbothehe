from google import genai
from google.genai import errors, types

from .models import (
    TOKEN_LIMIT, THINKING_HEADROOM, CountingFailed, DefinitelyRejected,
    Generated, UnknownUsage,
)


def enum_name(value) -> str:
    return str(getattr(value, "value", value) or "UNKNOWN")


class GeminiGateway:
    def __init__(self, api_key: str):
        # One network attempt, including the original request. Never regenerate
        # silently: a retry could spend an unknown amount of the session budget.
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=120_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def count_text(self, model: str, text: str) -> int:
        try:
            count = self.client.models.count_tokens(model=model, contents=text).total_tokens
        except Exception:
            # Don't expose provider exceptions: they can include request data.
            raise CountingFailed(
                "Không đếm được token. Kiểm tra API key, kết nối hoặc quota rồi gửi lại."
            ) from None
        if type(count) is not int or count < 0:
            raise CountingFailed("API không trả số token hợp lệ; chưa gửi tin nhắn.")
        return count

    def generate(self, model: str, history: list[dict], remaining: int) -> Generated:
        if not 1 <= remaining <= TOKEN_LIMIT:
            raise ValueError("Invalid visible output budget")
        contents = [
            types.Content(
                role="model" if message["role"] == "assistant" else "user",
                parts=[types.Part(text=message["content"])],
            )
            for message in history if message["content"]
        ]
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    candidate_count=1,
                    max_output_tokens=remaining + THINKING_HEADROOM,
                    response_modalities=["TEXT"],
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=False,
                        thinking_level=types.ThinkingLevel.MINIMAL,
                    ),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    automatic_continuation=False,
                ),
            )
        except errors.ClientError as exc:
            # 408/499 and every unrecognized failure are ambiguous. Only explicit
            # validation/auth/quota rejections are safe to roll back.
            if exc.code in {400, 401, 403, 404, 413, 422, 429}:
                raise DefinitelyRejected(
                    f"Gemini từ chối yêu cầu (HTTP {exc.code}). "
                    "Lượt này đã được hoàn tác; kiểm tra API key, model hoặc quota."
                ) from None
            raise UnknownUsage("Không xác định được token đã tiêu. Session đã bị khóa.") from None
        except Exception:
            raise UnknownUsage(
                "Mất kết nối, hết thời gian chờ hoặc lỗi API. "
                "Không xác định được token đã tiêu; session đã bị khóa."
            ) from None
        result = self.parse_response(response)
        return self.limit_visible_output(model, result, remaining)

    def limit_visible_output(self, model: str, result: Generated, remaining: int) -> Generated:
        if result.output_tokens <= remaining:
            return result
        # Gemini does not return token IDs. Count Unicode-safe text prefixes
        # with the actual model; retain only a prefix verified to fit. BPE token
        # counts need not be monotonic, so this promises a safe prefix rather
        # than claiming it is the longest possible prefix or always exactly N.
        low, high = 0, len(result.text)
        kept, kept_tokens = "", 0
        while low <= high:
            middle = (low + high) // 2
            prefix = result.text[:middle]
            count = self.count_text(model, prefix) if prefix else 0
            if count <= remaining:
                kept, kept_tokens = prefix, count
                low = middle + 1
            else:
                high = middle - 1
        return Generated(
            kept, kept_tokens, result.thinking_tokens, "LOCAL_TOKEN_LIMIT", result.actual_model,
        )

    @staticmethod
    def parse_response(response) -> Generated:
        usage = response.usage_metadata
        if usage is None:
            raise UnknownUsage("API thiếu usage metadata; session đã bị khóa.")
        prompt = usage.prompt_token_count
        total = usage.total_token_count
        output = usage.candidates_token_count if usage.candidates_token_count is not None else 0
        thinking = usage.thoughts_token_count if usage.thoughts_token_count is not None else 0
        if (any(type(n) is not int or n < 0 for n in (prompt, total, output, thinking))
                or total != prompt + output + thinking):
            raise UnknownUsage("Usage metadata không đầy đủ hoặc không nhất quán; session đã bị khóa.")
        candidates = response.candidates or []
        if len(candidates) > 1:
            raise UnknownUsage("API trả nhiều hơn một câu trả lời; session đã bị khóa.")
        candidate = candidates[0] if candidates else None
        text = ""
        if candidate and candidate.content:
            # Thought summaries, signatures, function calls and binary parts are
            # never displayed, persisted or included in subsequent context.
            text = "".join(
                part.text for part in candidate.content.parts or []
                if part.text is not None and not part.thought
            )
        if text and output == 0:
            raise UnknownUsage("API thiếu số token cho câu trả lời; session đã bị khóa.")
        finish = enum_name(candidate.finish_reason) if candidate else "BLOCKED"
        return Generated(text, output, thinking, finish, response.model_version)
