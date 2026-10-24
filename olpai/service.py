import uuid
from typing import Protocol

from .models import (
    ChatError, DefinitelyRejected, Generated, SessionUnavailable, TurnResult, UnknownUsage,
)
from .storage import Store


class Gateway(Protocol):
    def count_text(self, model: str, text: str) -> int: ...

    def generate(self, model: str, history: list[dict], remaining: int) -> Generated: ...


class ChatService:
    def __init__(self, store: Store, gateway: Gateway):
        self.store, self.gateway = store, gateway

    def send_turn(self, session_id: str, text: str, request_id: str | None = None) -> TurnResult:
        if not isinstance(text, str) or not text.strip():
            raise ChatError("Hãy nhập văn bản trước khi gửi.")
        request_id = request_id or uuid.uuid4().hex
        previous = self.store.completed_result(request_id, session_id)
        if previous:
            return previous
        session = self.store.get_session(session_id)
        if session["status"] != "active":
            raise SessionUnavailable("Session đang xử lý, đã hết token hoặc đã bị khóa.")
        count = self.gateway.count_text(session["model"], text)
        remaining = self.store.reserve_turn(session_id, request_id, text, count)
        try:
            if remaining == 0:
                result = Generated("", 0, 0, "INPUT_EXHAUSTED")
            else:
                result = self.gateway.generate(
                    session["model"], self.store.messages(session_id), remaining,
                )
            return self.store.complete_turn(session_id, request_id, result)
        except DefinitelyRejected:
            self.store.reject_turn(session_id, request_id)
            raise
        except UnknownUsage as exc:
            self.store.lock_turn(session_id, request_id, str(exc))
            raise
        except BaseException as exc:
            # Includes Streamlit interruptions, Ctrl+C and failed DB writes after
            # generation. Never leave a retryable session with unaccounted usage.
            reason = "Lượt gửi bị gián đoạn; không xác định được token đã tiêu. Session đã bị khóa."
            self.store.lock_turn(session_id, request_id, reason)
            if not isinstance(exc, Exception):
                raise
            raise UnknownUsage(reason) from None
