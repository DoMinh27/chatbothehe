from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from olpai.models import DEFAULT_MODEL, Generated
from olpai.service import ChatService
from olpai.storage import Store


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "chat.sqlite3"
        # Use the real dependent tables and a fixture for the old parent schema.
        Store(self.path)
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        db.executescript("""
            DROP TABLE sessions;
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, model TEXT NOT NULL,
                actual_model TEXT, status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','busy','exhausted','locked')),
                input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens>=0),
                output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens>=0),
                thinking_tokens INTEGER NOT NULL DEFAULT 0 CHECK(thinking_tokens>=0),
                used_tokens INTEGER NOT NULL DEFAULT 0 CHECK(used_tokens BETWEEN 0 AND 2000)
                    CHECK(used_tokens = input_tokens + output_tokens + thinking_tokens),
                lock_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            PRAGMA user_version=1;
        """)
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy", "Old title", DEFAULT_MODEL, "actual", "exhausted",
             300, 500, 1200, 2000, None, "timestamp", "timestamp"),
        )
        db.execute(
            "INSERT INTO turns(id,session_id,state,input_tokens,output_tokens,thinking_tokens,"
            "finish_reason,created_at) VALUES('old-turn','legacy','completed',300,500,1200,'STOP','timestamp')"
        )
        db.execute(
            "INSERT INTO messages(session_id,turn_id,role,content,token_count,created_at) "
            "VALUES('legacy','old-turn','user','Câu hỏi cũ 🙂',300,'timestamp')"
        )
        db.execute(
            "INSERT INTO messages(session_id,turn_id,role,content,token_count,thinking_tokens,"
            "finish_reason,created_at) "
            "VALUES('legacy','old-turn','assistant','Câu trả lời cũ',500,1200,'STOP','timestamp')"
        )
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("locked", "Uncertain usage", DEFAULT_MODEL, None, "locked",
             10, 0, 0, 10, "Uncertain usage", "timestamp", "timestamp"),
        )
        db.commit()
        db.close()

    def test_migration_restores_visible_budget_and_preserves_history(self):
        store = Store(self.path)
        session = store.get_session("legacy")
        self.assertEqual(session["used_tokens"], 800)
        self.assertEqual(session["thinking_tokens"], 1200)
        self.assertEqual(session["status"], "active")
        self.assertEqual([message["content"] for message in store.messages("legacy")],
                         ["Câu hỏi cũ 🙂", "Câu trả lời cũ"])
        with store.connection() as db:
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(store.get_session("locked")["status"], "locked")

    def test_backup_is_readable_and_migration_only_runs_once(self):
        Store(self.path)
        Store(self.path)
        backups = list((self.path.parent / "backups").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as backup:
            self.assertEqual(backup.execute("SELECT used_tokens FROM sessions WHERE id='legacy'").fetchone()[0], 2000)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2)

    def test_chat_continues_after_migration_without_charging_thinking(self):
        store = Store(self.path)
        class Gateway:
            def count_text(self, model, text):
                return 20
            def generate(self, model, history, remaining):
                self.remaining = remaining
                return Generated("New answer", 100, 5000, "STOP")
        gateway = Gateway()
        ChatService(store, gateway).send_turn("legacy", "Next question")
        self.assertEqual(gateway.remaining, 1180)
        self.assertEqual(store.get_session("legacy")["used_tokens"], 920)
        self.assertEqual(store.get_session("legacy")["thinking_tokens"], 6200)
        self.assertEqual(len(store.messages("legacy")), 4)


if __name__ == "__main__":
    unittest.main()
