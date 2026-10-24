import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from olpai.models import DefinitelyRejected, Generated, UnknownUsage
from olpai.storage import Store

APP = str(Path(__file__).resolve().parents[1] / "app.py")


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.environment = patch.dict(os.environ, {
            "OLPAI_DATA_DIR": self.tmp.name,
            "GEMINI_API_KEY": "test-not-a-real-key",
            "OLPAI_PUBLIC_MODE": "false",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.count_patch = patch("olpai.gemini.GeminiGateway.count_text", side_effect=lambda model, text: len(text))
        self.generate_patch = patch("olpai.gemini.GeminiGateway.generate", return_value=Generated(
            "```python\nprint('xin chào')\n```", 10, 5, "STOP", "gemini-3.6-flash"
        ))
        self.counter = self.count_patch.start()
        self.generator = self.generate_patch.start()
        self.addCleanup(self.count_patch.stop)
        self.addCleanup(self.generate_patch.stop)
        self.addCleanup(st.cache_resource.clear)

    def app(self):
        return AppTest.from_file(APP, default_timeout=10).run()

    def test_start_and_send_then_new_chat(self):
        app = self.app()
        self.assertFalse(app.exception)
        self.assertFalse(app.chat_input[0].disabled)
        self.assertFalse(app.chat_input[0].proto.accept_file)
        self.assertFalse(app.chat_input[0].proto.accept_audio)
        session_id = app.radio[0].value
        app.chat_input[0].set_value("hello").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.chat_message), 2)
        store = Store(Path(self.tmp.name) / "chat.sqlite3")
        self.assertEqual(store.get_session(session_id)["used_tokens"], 15)
        app.sidebar.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertNotEqual(app.radio[0].value, session_id)
        self.assertEqual(len(app.chat_message), 0)
        app.radio[0].set_value(session_id).run()
        self.assertEqual(len(app.chat_message), 2)

    def test_overlong_input_restores_draft_without_saving(self):
        app = self.app()
        app.chat_input[0].set_value("x" * 2001).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertEqual(len(app.chat_message), 0)
        self.assertFalse(self.generator.called)
        self.assertEqual(app.chat_input[0].proto.value, "x" * 2001)

    def test_exhaustion_disables_input(self):
        app = self.app()
        app.chat_input[0].set_value("x" * 2000).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.chat_input[0].disabled)
        self.assertFalse(self.generator.called)

    def test_no_api_key_keeps_history_readable(self):
        os.environ["GEMINI_API_KEY"] = ""
        with patch("olpai.config.load_api_key", return_value=""):
            app = self.app()
        self.assertFalse(app.exception)
        self.assertTrue(app.chat_input[0].disabled)
        self.assertTrue(any("Nhập / đổi API key" in entry.value for entry in app.info))

    def test_rejected_request_restores_text_and_budget(self):
        self.generator.side_effect = DefinitelyRejected("API từ chối")
        app = self.app()
        app.chat_input[0].set_value("keep this draft").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertFalse(app.chat_input[0].disabled)
        self.assertEqual(app.chat_input[0].proto.value, "keep this draft")
        self.assertEqual(len(app.chat_message), 0)

    def test_ambiguous_failure_locks_input_but_keeps_history(self):
        self.generator.side_effect = UnknownUsage("Không xác định được usage")
        app = self.app()
        app.chat_input[0].set_value("hello").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.chat_input[0].disabled)
        self.assertEqual(len(app.chat_message), 1)
        self.assertTrue(app.error)

    def test_reload_restores_selected_session_and_budget(self):
        app = self.app()
        session_id = app.radio[0].value
        app.chat_input[0].set_value("hello").run()
        restored = AppTest.from_file(APP, default_timeout=10)
        restored.query_params["session"] = session_id
        restored.run()
        self.assertFalse(restored.exception)
        self.assertEqual(restored.radio[0].value, session_id)
        self.assertEqual(len(restored.chat_message), 2)

    def enter_key(self, app, key):
        app.menu_button[0].click("Nhập / đổi API key").run()
        self.assertFalse(app.exception)
        field = next(field for field in app.text_input if field.key == "api_key_entry")
        self.assertEqual(field.proto.type, 1)  # TextInput protobuf PASSWORD enum.
        field.set_value(key)
        next(button for button in app.button if button.label == "Dùng API key").click().run()
        self.assertFalse(app.exception)

    def test_manual_key_overrides_local_key_and_can_be_removed(self):
        app = self.app()
        self.enter_key(app, "visitor-test-key")
        self.assertEqual(app.session_state["visitor_api_key"], "visitor-test-key")
        self.assertFalse(app.chat_input[0].disabled)
        app.menu_button[0].click("Xóa API key khỏi phiên").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.chat_input[0].disabled)
        self.assertEqual(app.session_state["visitor_api_key"], "")

    def test_public_visitors_have_separate_keys_and_history(self):
        os.environ["OLPAI_PUBLIC_MODE"] = "true"
        first = self.app()
        self.assertTrue(first.chat_input[0].disabled)  # Never borrow the server key.
        self.enter_key(first, "visitor-A-test-key")
        first.chat_input[0].set_value("private conversation A").run()
        self.assertFalse(first.exception)
        second = self.app()
        self.assertTrue(second.chat_input[0].disabled)
        self.assertEqual(len(second.chat_message), 0)
        self.enter_key(second, "visitor-B-test-key")
        second.chat_input[0].set_value("private conversation B").run()
        self.assertFalse(second.exception)
        self.assertNotEqual(first.query_params["workspace"], second.query_params["workspace"])
        self.assertEqual(first.session_state["visitor_api_key"], "visitor-A-test-key")
        self.assertEqual(second.session_state["visitor_api_key"], "visitor-B-test-key")
        first.run()
        self.assertFalse(first.exception)
        visible = " ".join(entry.value for entry in first.text)
        self.assertIn("private conversation A", visible)
        self.assertNotIn("private conversation B", visible)
        for path in Path(self.tmp.name).rglob("*.sqlite3"):
            data = path.read_bytes()
            self.assertNotIn(b"visitor-A-test-key", data)
            self.assertNotIn(b"visitor-B-test-key", data)
        self.assertNotIn("visitor-A-test-key", str(first.query_params))

    def test_public_reload_preserves_history_but_requires_key_again(self):
        os.environ["OLPAI_PUBLIC_MODE"] = "true"
        app = self.app()
        self.enter_key(app, "visitor-test-key")
        app.chat_input[0].set_value("saved public history").run()
        restored = AppTest.from_file(APP, default_timeout=10)
        restored.query_params.update(app.query_params)
        restored.run()
        self.assertFalse(restored.exception)
        self.assertEqual(len(restored.chat_message), 2)
        self.assertTrue(restored.chat_input[0].disabled)
        self.assertEqual(restored.session_state["visitor_api_key"], "")

    def test_removing_one_visitors_key_does_not_close_another_client(self):
        os.environ["OLPAI_PUBLIC_MODE"] = "true"
        clients = {}
        def initialize(gateway, key):
            gateway.client = SimpleNamespace(close=Mock())
            clients[key] = gateway.client
        with patch("olpai.gemini.GeminiGateway.__init__", initialize):
            # AppTest hardcodes "test session id" for all runners. Supply two
            # actual cache scopes to simulate distinct browser connections.
            scope = "streamlit.runtime.caching.cache_resource_api.get_session_id_or_throw"
            with patch(scope, return_value="browser-A"):
                first = self.app()
                self.enter_key(first, "client-A-test-key")
                first.chat_input[0].set_value("hello A").run()
            first_client = clients["client-A-test-key"]
            first_close_count = first_client.close.call_count
            with patch(scope, return_value="browser-B"):
                second = self.app()
                self.enter_key(second, "client-B-test-key")
                second.chat_input[0].set_value("hello B").run()
            self.assertEqual(first_client.close.call_count, first_close_count)
            with patch(scope, return_value="browser-B"):
                second.menu_button[0].click("Xóa API key khỏi phiên").run()
            clients["client-B-test-key"].close.assert_called_once()
            self.assertEqual(first_client.close.call_count, first_close_count)
            with patch(scope, return_value="browser-A"):
                first.chat_input[0].set_value("still works A").run()
            self.assertFalse(first.exception)

    def test_public_workspace_cannot_escape_data_directory(self):
        os.environ["OLPAI_PUBLIC_MODE"] = "true"
        app = AppTest.from_file(APP, default_timeout=10)
        app.query_params["workspace"] = "../../outside"
        app.run()
        self.assertFalse(app.exception)
        self.assertRegex(str(app.query_params["workspace"]), r"[0-9a-f]{64}")


if __name__ == "__main__":
    unittest.main()
