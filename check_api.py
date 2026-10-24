"""A real, small AI Studio smoke check. Does not write chat history."""
import os
import sys
from pathlib import Path

from olpai.config import load_api_key
from olpai.gemini import GeminiGateway
from olpai.models import ChatError, DEFAULT_MODEL, TOKEN_LIMIT


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        api_key = load_api_key(Path(__file__).resolve().parent)
    except ChatError as exc:
        print(str(exc))
        return 1
    if not api_key:
        print("Chưa có GEMINI_API_KEY. Thiết lập theo README.md trước khi kiểm tra.")
        return 2
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    gateway = GeminiGateway(api_key)
    try:
        text = "Trả lời đúng một từ: OK."
        tokens = gateway.count_text(model, text)
        result = gateway.generate(model, [{"role": "user", "content": text}], TOKEN_LIMIT - tokens)
        print(f"Kết nối thành công. Model yêu cầu: {model}")
        print(f"Model phản hồi: {result.actual_model or 'không được API cung cấp'}")
        print(f"Input mới: {tokens}; output: {result.output_tokens}; thinking: {result.thinking_tokens}")
        print(f"Kết thúc: {result.finish_reason}; có văn bản: {bool(result.text)}")
        return 0
    except ChatError as exc:
        print(str(exc))
        return 1
    finally:
        gateway.client.close()


if __name__ == "__main__":
    sys.exit(main())
