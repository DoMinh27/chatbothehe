from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

from .models import (
    TOKEN_LIMIT, BudgetExceeded, Generated, SessionUnavailable, TurnResult,
    UnknownUsage,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    BUDGET_VERSION = 2

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    model TEXT NOT NULL,
                    actual_model TEXT,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','busy','exhausted','locked')),
                    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
                    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
                    thinking_tokens INTEGER NOT NULL DEFAULT 0 CHECK(thinking_tokens >= 0),
                    used_tokens INTEGER NOT NULL DEFAULT 0
                        CHECK(used_tokens BETWEEN 0 AND 2000)
                        CHECK(used_tokens = input_tokens + output_tokens),
                    lock_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    state TEXT NOT NULL CHECK(state IN ('pending','completed','rejected','unknown')),
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    thinking_tokens INTEGER NOT NULL DEFAULT 0,
                    finish_reason TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    turn_id TEXT NOT NULL REFERENCES turns(id),
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    thinking_tokens INTEGER NOT NULL DEFAULT 0,
                    finish_reason TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(turn_id, role)
                );
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id);
            """)
        self._migrate_visible_budget()

    def _migrate_visible_budget(self) -> None:
        with self.connection() as db:
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='sessions'").fetchone()[0]
            legacy = "input_tokens + output_tokens + thinking_tokens" in schema
            if not legacy:
                db.execute("PRAGMA user_version=2")
                return
            # SQLite backup includes committed WAL data. Never overwrite a
            # previous backup or expose message contents in migration logs.
            backups = self.path.parent / "backups"
            backups.mkdir(exist_ok=True)
            backup_path = backups / f"{self.path.stem}-before-visible-budget-{uuid.uuid4().hex[:12]}.sqlite3"
            with closing(sqlite3.connect(backup_path)) as backup:
                db.backup(backup)
            # The constraint cannot be changed by ALTER COLUMN. Rebuild only
            # the parent table, preserving IDs and all dependent chat rows.
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='sessions'").fetchone()[0]
            if "input_tokens + output_tokens + thinking_tokens" not in schema:
                return
            new_schema = schema.replace("CREATE TABLE sessions", "CREATE TABLE sessions_visible", 1)
            new_schema = new_schema.replace(
                "input_tokens + output_tokens + thinking_tokens", "input_tokens + output_tokens"
            )
            db.execute(new_schema)
            db.execute("""
                INSERT INTO sessions_visible
                SELECT id,title,model,actual_model,
                    CASE WHEN status='exhausted' AND input_tokens+output_tokens<2000
                         THEN 'active' ELSE status END,
                    input_tokens,output_tokens,thinking_tokens,input_tokens+output_tokens,
                    lock_reason,created_at,updated_at
                FROM sessions
            """)
            db.execute("DROP TABLE sessions")
            db.execute("ALTER TABLE sessions_visible RENAME TO sessions")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("Không thể chuyển đổi dữ liệu: liên kết lịch sử không hợp lệ.")
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connection(self, write: bool = False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_session(self, model: str) -> str:
        session_id, timestamp = uuid.uuid4().hex, now()
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO sessions(id,title,model,created_at,updated_at) VALUES(?,?,?,?,?)",
                (session_id, "Cuộc trò chuyện mới", model, timestamp, timestamp),
            )
        return session_id

    def get_session(self, session_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise SessionUnavailable("Không tìm thấy session.")
        return dict(row)

    def list_sessions(self) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, id"
            )]

    def messages(self, session_id: str) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,)
            )]

    def completed_result(self, request_id: str, session_id: str) -> TurnResult | None:
        with self.connection() as db:
            turn = db.execute("SELECT * FROM turns WHERE id=?", (request_id,)).fetchone()
            if turn is None:
                return None
            if turn["session_id"] != session_id or turn["state"] != "completed":
                raise SessionUnavailable("Lượt gửi này đã được xử lý hoặc đang bị khóa.")
            message = db.execute(
                "SELECT content FROM messages WHERE turn_id=? AND role='assistant'", (request_id,)
            ).fetchone()
            session = db.execute("SELECT status FROM sessions WHERE id=?", (session_id,)).fetchone()
        return TurnResult(request_id, message["content"] if message else "",
                          turn["finish_reason"], session["status"] == "exhausted")

    def reserve_turn(self, session_id: str, request_id: str, text: str, count: int) -> int:
        if type(count) is not int or count < 0:
            raise ValueError("Invalid input token count")
        with self.connection(write=True) as db:
            if db.execute("SELECT 1 FROM turns WHERE id=?", (request_id,)).fetchone():
                raise SessionUnavailable("Lượt gửi này đã được xử lý. Không gửi lại tự động.")
            session = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if session is None or session["status"] != "active":
                raise SessionUnavailable("Session đang xử lý, đã hết token hoặc đã bị khóa.")
            remaining = TOKEN_LIMIT - session["used_tokens"]
            if count > remaining:
                raise BudgetExceeded(
                    f"Tin nhắn cần {count} token nhưng session chỉ còn {remaining}. Hãy rút ngắn."
                )
            timestamp = now()
            db.execute(
                "INSERT INTO turns(id,session_id,state,input_tokens,created_at) VALUES(?,?,'pending',?,?)",
                (request_id, session_id, count, timestamp),
            )
            db.execute(
                "INSERT INTO messages(session_id,turn_id,role,content,token_count,created_at) "
                "VALUES(?,?,'user',?,?,?)", (session_id, request_id, text, count, timestamp),
            )
            has_previous = db.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id=? AND role='user'", (session_id,)
            ).fetchone()[0] > 1
            title = session["title"] if has_previous else " ".join(text.split())[:60]
            db.execute(
                "UPDATE sessions SET status='busy',title=?,input_tokens=input_tokens+?,"
                "used_tokens=used_tokens+?,updated_at=? WHERE id=?",
                (title, count, count, timestamp, session_id),
            )
        return remaining - count

    def complete_turn(self, session_id: str, request_id: str, result: Generated) -> TurnResult:
        counts = (result.output_tokens, result.thinking_tokens)
        if any(type(n) is not int or n < 0 for n in counts):
            raise UnknownUsage("API trả về số token không hợp lệ.")
        with self.connection(write=True) as db:
            turn = db.execute("SELECT * FROM turns WHERE id=?", (request_id,)).fetchone()
            session = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if (turn is None or turn["session_id"] != session_id or
                    turn["state"] != "pending" or session["status"] != "busy"):
                raise SessionUnavailable("Lượt gửi không còn ở trạng thái đang xử lý.")
            used = session["used_tokens"] + result.output_tokens
            if used > TOKEN_LIMIT:
                raise UnknownUsage("API báo số token vượt giới hạn đã yêu cầu; phản hồi bị loại bỏ.")
            if result.text and result.output_tokens == 0:
                raise UnknownUsage("API trả văn bản nhưng không báo số token đầu ra.")
            timestamp = now()
            db.execute(
                "INSERT INTO messages(session_id,turn_id,role,content,token_count,thinking_tokens,"
                "finish_reason,created_at) VALUES(?,?,'assistant',?,?,?,?,?)",
                (session_id, request_id, result.text, result.output_tokens,
                 result.thinking_tokens, result.finish_reason, timestamp),
            )
            db.execute(
                "UPDATE turns SET state='completed',output_tokens=?,thinking_tokens=?,finish_reason=? WHERE id=?",
                (result.output_tokens, result.thinking_tokens, result.finish_reason, request_id),
            )
            status = "exhausted" if used == TOKEN_LIMIT else "active"
            db.execute(
                "UPDATE sessions SET status=?,used_tokens=?,output_tokens=output_tokens+?,"
                "thinking_tokens=thinking_tokens+?,actual_model=COALESCE(?,actual_model),"
                "updated_at=? WHERE id=?",
                (status, used, result.output_tokens, result.thinking_tokens,
                 result.actual_model, timestamp, session_id),
            )
        return TurnResult(request_id, result.text, result.finish_reason, status == "exhausted")

    def reject_turn(self, session_id: str, request_id: str) -> None:
        with self.connection(write=True) as db:
            turn = db.execute("SELECT * FROM turns WHERE id=? AND session_id=? AND state='pending'",
                              (request_id, session_id)).fetchone()
            if turn is None:
                return
            db.execute("DELETE FROM messages WHERE turn_id=?", (request_id,))
            db.execute("UPDATE turns SET state='rejected',finish_reason='REJECTED' WHERE id=?", (request_id,))
            first = db.execute(
                "SELECT content FROM messages WHERE session_id=? AND role='user' ORDER BY id LIMIT 1",
                (session_id,),
            ).fetchone()
            title = " ".join(first["content"].split())[:60] if first else "Cuộc trò chuyện mới"
            db.execute(
                "UPDATE sessions SET status='active',title=?,used_tokens=used_tokens-?,"
                "input_tokens=input_tokens-?,updated_at=? WHERE id=?",
                (title, turn["input_tokens"], turn["input_tokens"], now(), session_id),
            )

    def lock_turn(self, session_id: str, request_id: str, reason: str) -> None:
        with self.connection(write=True) as db:
            turn = db.execute("SELECT state FROM turns WHERE id=? AND session_id=?",
                              (request_id, session_id)).fetchone()
            if turn and turn["state"] == "pending":
                db.execute("UPDATE turns SET state='unknown',finish_reason='USAGE_UNKNOWN' WHERE id=?",
                           (request_id,))
                db.execute(
                    "UPDATE sessions SET status='locked',lock_reason=?,updated_at=? WHERE id=?",
                    (reason, now(), session_id),
                )

    def recover_interrupted(self) -> None:
        """Call once after acquiring the exclusive application process lock."""
        with self.connection(write=True) as db:
            db.execute(
                "UPDATE sessions SET status='locked',lock_reason=?,updated_at=? WHERE status='busy'",
                ("Ứng dụng đã dừng giữa lượt; không xác định được token đã tiêu.", now()),
            )
            db.execute(
                "UPDATE turns SET state='unknown',finish_reason='INTERRUPTED' WHERE state='pending'"
            )
