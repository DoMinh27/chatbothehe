from dataclasses import dataclass

TOKEN_LIMIT = 2000
# Provider limits include thinking; reserve separate headroom, then enforce the
# visible answer budget before anything is persisted or displayed.
THINKING_HEADROOM = 2048
DEFAULT_MODEL = "gemini-3.5-flash"


class ChatError(Exception):
    """An error whose message is safe to display to the user."""


class BudgetExceeded(ChatError):
    pass


class SessionUnavailable(ChatError):
    pass


class DefinitelyRejected(ChatError):
    """The provider explicitly rejected the request before generation."""


class UnknownUsage(ChatError):
    """Generation may have happened, but its usage cannot be established."""


class CountingFailed(ChatError):
    pass


@dataclass(frozen=True)
class Generated:
    text: str
    output_tokens: int
    thinking_tokens: int
    finish_reason: str
    actual_model: str | None = None


@dataclass(frozen=True)
class TurnResult:
    request_id: str
    text: str
    finish_reason: str
    exhausted: bool
