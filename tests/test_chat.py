from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from olpai.models import (
    BudgetExceeded, CountingFailed, DEFAULT_MODEL, DefinitelyRejected,
    Generated, SessionUnavailable, UnknownUsage,
)
from olpai.runtime import Runtime
from olpai.service import ChatService
from olpai.storage import Store


class FakeGateway:
    def __init__(self, results=None, counts=None):
        self.results = list(results or [])
        self.counts = counts or {}
        self.calls = []
        self.count_calls = []

    def count_text(self, model, text):
        self.count_calls.append((model, text))
        return self.counts.get(text, len(text))

    def generate(self, model, history, remaining):
        self.calls.append((model, history, remaining))
        result = self.results.pop(0) if self.results else Generated("OK", 2, 3, "STOP", "actual-model")
        if isinstance(result, BaseException):
            raise result
        return result


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "chat.sqlite3"
        self.store = Store(self.path)
        self.session = self.store.create_session(DEFAULT_MODEL)

    def service(self, gateway=None):
        return ChatService(self.store, gateway or FakeGateway())

    def assert_consistent(self, session_id=None):
        session_id = session_id or self.session
        row = self.store.get_session(session_id)
        messages = self.store.messages(session_id)
        self.assertEqual(row["used_tokens"], sum(
            message["token_count"] for message in messages
        ))
        self.assertLessEqual(row["used_tokens"], 2000)

    def test_multi_turn_counts_new_input_once_and_sends_history(self):
        gateway = FakeGateway([
            Generated("first answer", 150, 50, "STOP"),
            Generated("second answer", 100, 25, "STOP"),
        ], {"first": 100, "second": 200})
        service = self.service(gateway)
        service.send_turn(self.session, "first")
        service.send_turn(self.session, "second")
        self.assertEqual(self.store.get_session(self.session)["used_tokens"], 550)
        self.assertEqual(self.store.get_session(self.session)["thinking_tokens"], 75)
        self.assertEqual([call[2] for call in gateway.calls], [1900, 1550])
        self.assertEqual([m["content"] for m in gateway.calls[1][1]],
                         ["first", "first answer", "second"])
        self.assert_consistent()

    def test_sessions_are_isolated(self):
        other = self.store.create_session(DEFAULT_MODEL)
        gateway = FakeGateway()
        service = self.service(gateway)
        service.send_turn(self.session, "secret in A")
        service.send_turn(other, "hello in B")
        self.assertEqual([m["content"] for m in gateway.calls[1][1]], ["hello in B"])
        self.assert_consistent(other)

    def test_1999_input_leaves_exactly_one_output_token(self):
        gateway = FakeGateway([Generated("x", 1, 0, "MAX_TOKENS")])
        self.service(gateway).send_turn(self.session, "x" * 1999)
        self.assertEqual(gateway.calls[0][2], 1)
        self.assertEqual(self.store.get_session(self.session)["status"], "exhausted")
        self.assert_consistent()

    def test_2000_input_does_not_call_generation(self):
        gateway = FakeGateway()
        self.service(gateway).send_turn(self.session, "x" * 2000)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(self.store.get_session(self.session)["used_tokens"], 2000)
        self.assert_consistent()

    def test_2001_input_is_not_saved(self):
        gateway = FakeGateway()
        with self.assertRaises(BudgetExceeded):
            self.service(gateway).send_turn(self.session, "x" * 2001)
        self.assertEqual(self.store.messages(self.session), [])
        self.assertEqual(gateway.calls, [])
        self.assert_consistent()

    def test_boundary_across_multiple_turns(self):
        gateway = FakeGateway([Generated("a", 1998, 1997, "MAX_TOKENS")])
        service = self.service(gateway)
        service.send_turn(self.session, "x")
        self.assertEqual(self.store.get_session(self.session)["used_tokens"], 1999)
        service.send_turn(self.session, "y")
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(self.store.get_session(self.session)["used_tokens"], 2000)
        self.assert_consistent()

    def test_thinking_never_exhausts_visible_budget(self):
        gateway = FakeGateway([Generated("", 0, 1995, "MAX_TOKENS")])
        result = self.service(gateway).send_turn(self.session, "hello")
        self.assertFalse(result.exhausted)
        self.assertEqual(result.text, "")
        self.assertEqual(self.store.get_session(self.session)["thinking_tokens"], 1995)
        self.assertEqual(self.store.get_session(self.session)["used_tokens"], 5)
        self.assertEqual(self.store.get_session(self.session)["status"], "active")
        self.assert_consistent()

    def test_exhausted_session_never_generates_again(self):
        gateway = FakeGateway()
        service = self.service(gateway)
        service.send_turn(self.session, "x" * 2000)
        with self.assertRaises(SessionUnavailable):
            service.send_turn(self.session, "another")
        self.assertEqual(gateway.calls, [])

    def test_truncated_code_is_not_completed_or_regenerated(self):
        code = "```python\nfor i in range(10):\n    print("
        gateway = FakeGateway([Generated(code, 1999, 0, "MAX_TOKENS")])
        self.service(gateway).send_turn(self.session, "x")
        self.assertEqual(self.store.messages(self.session)[-1]["content"], code)
        self.assertEqual(len(gateway.calls), 1)

    def test_provider_overflow_is_not_stored_or_displayed(self):
        gateway = FakeGateway([Generated("forbidden overflow", 2000, 1, "STOP")])
        with self.assertRaises(UnknownUsage):
            self.service(gateway).send_turn(self.session, "x")
        self.assertEqual([m["content"] for m in self.store.messages(self.session)], ["x"])
        self.assertEqual(self.store.get_session(self.session)["status"], "locked")
        self.assert_consistent()

    def test_unicode_and_whitespace_are_preserved(self):
        text = "  Tiếng Việt 🙂\n```python\n    print('xin chào')\n```\n"
        answer = "Dữ liệu 🧠\n    giữ thụt lề\n"
        gateway = FakeGateway([Generated(answer, 30, 5, "STOP")], {text: 41})
        self.service(gateway).send_turn(self.session, text)
        self.assertEqual(gateway.count_calls[0][1], text)
        self.assertEqual([m["content"] for m in self.store.messages(self.session)], [text, answer])
        self.assert_consistent()

    def test_data_and_counters_survive_new_store_instance(self):
        self.service().send_turn(self.session, "remember")
        reopened = Store(self.path)
        self.assertEqual(reopened.messages(self.session), self.store.messages(self.session))
        self.assertEqual(reopened.get_session(self.session), self.store.get_session(self.session))

    def test_definite_rejection_rolls_back_and_does_not_retry(self):
        gateway = FakeGateway([DefinitelyRejected("quota")])
        with self.assertRaises(DefinitelyRejected):
            self.service(gateway).send_turn(self.session, "not accepted")
        row = self.store.get_session(self.session)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["used_tokens"], 0)
        self.assertEqual(row["title"], "Cuộc trò chuyện mới")
        self.assertEqual(self.store.messages(self.session), [])
        self.assertEqual(len(gateway.calls), 1)

    def test_rejection_preserves_older_messages(self):
        gateway = FakeGateway([Generated("answer", 10, 5, "STOP"), DefinitelyRejected("quota")])
        service = self.service(gateway)
        service.send_turn(self.session, "first")
        before = self.store.get_session(self.session)["used_tokens"]
        with self.assertRaises(DefinitelyRejected):
            service.send_turn(self.session, "second")
        self.assertEqual(self.store.get_session(self.session)["used_tokens"], before)
        self.assertEqual([m["content"] for m in self.store.messages(self.session)], ["first", "answer"])
        self.assert_consistent()

    def test_timeout_locks_session_and_does_not_retry(self):
        gateway = FakeGateway([TimeoutError("private provider details")])
        service = self.service(gateway)
        with self.assertRaises(UnknownUsage) as caught:
            service.send_turn(self.session, "hello")
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(self.store.get_session(self.session)["status"], "locked")
        with self.assertRaises(SessionUnavailable):
            service.send_turn(self.session, "retry")
        self.assertEqual(len(gateway.calls), 1)
        self.assert_consistent()

    def test_completed_request_id_is_idempotent(self):
        gateway = FakeGateway()
        service = self.service(gateway)
        first = service.send_turn(self.session, "hello", "same-id")
        second = service.send_turn(self.session, "hello", "same-id")
        self.assertEqual(first, second)
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(len(gateway.count_calls), 1)
        self.assert_consistent()

    def test_counting_failure_does_not_spend_budget(self):
        gateway = FakeGateway()
        def fail(*args):
            raise CountingFailed("unavailable")
        gateway.count_text = fail
        with self.assertRaises(CountingFailed):
            self.service(gateway).send_turn(self.session, "hello")
        self.assertEqual(self.store.messages(self.session), [])
        self.assertEqual(self.store.get_session(self.session)["status"], "active")

    def test_two_concurrent_tabs_only_generate_one_turn(self):
        entered, release = Event(), Event()
        gateway = FakeGateway()
        original = gateway.generate
        def blocking(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError()
            return original(*args)
        gateway.generate = blocking
        service = self.service(gateway)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.send_turn, self.session, "first")
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(SessionUnavailable):
                    service.send_turn(self.session, "second")
            finally:
                release.set()
            first.result(timeout=5)
        self.assertEqual(len(gateway.calls), 1)
        self.assert_consistent()

    def test_interrupted_turn_is_locked_after_restart(self):
        self.store.reserve_turn(self.session, "crashed-request", "hello", 5)
        reopened = Store(self.path)
        reopened.recover_interrupted()
        self.assertEqual(reopened.get_session(self.session)["status"], "locked")
        with self.assertRaises(SessionUnavailable):
            ChatService(reopened, FakeGateway()).send_turn(self.session, "retry")
        self.assert_consistent()

    def test_one_runtime_cannot_interrupt_another(self):
        directory = Path(self.tmp.name) / "runtime"
        runtime = Runtime(directory)
        try:
            with self.assertRaises(RuntimeError):
                Runtime(directory)
            session = runtime.store.create_session(DEFAULT_MODEL)
            runtime.store.reserve_turn(session, "pending", "hello", 5)
        finally:
            runtime.lock.close()
        restarted = Runtime(directory)
        try:
            self.assertEqual(restarted.store.get_session(session)["status"], "locked")
        finally:
            restarted.lock.close()


if __name__ == "__main__":
    unittest.main()
