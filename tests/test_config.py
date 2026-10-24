import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from olpai.config import load_api_key, load_public_mode
from olpai.models import ChatError


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".streamlit").mkdir()
        self.file = self.root / ".streamlit" / "secrets.toml"
        self.env = patch.dict(os.environ, {"GEMINI_API_KEY": ""})
        self.env.start()
        os.environ.pop("OLPAI_PUBLIC_MODE", None)
        self.addCleanup(self.env.stop)

    def test_reads_file_without_environment_and_rereads_changes(self):
        self.file.write_text('GEMINI_API_KEY = "first-test-key"', encoding="utf-8-sig")
        self.assertEqual(load_api_key(self.root), "first-test-key")
        self.file.write_text('GEMINI_API_KEY = "second-test-key"', encoding="utf-8")
        self.assertEqual(load_api_key(self.root), "second-test-key")

    def test_environment_takes_precedence(self):
        self.file.write_text('GEMINI_API_KEY = "file-test-key"', encoding="utf-8")
        os.environ["GEMINI_API_KEY"] = "env-test-key"
        self.assertEqual(load_api_key(self.root), "env-test-key")

    def test_missing_file_returns_empty_key(self):
        self.assertEqual(load_api_key(self.root), "")

    def test_malformed_file_does_not_expose_key(self):
        self.file.write_text('GEMINI_API_KEY = "private-test-key', encoding="utf-8")
        with self.assertRaises(ChatError) as caught:
            load_api_key(self.root)
        self.assertNotIn("private-test-key", str(caught.exception))

    def test_public_mode_is_safe_default(self):
        self.assertTrue(load_public_mode(self.root))
        self.file.write_text('GEMINI_API_KEY = "owner-test-key"', encoding="utf-8")
        self.assertTrue(load_public_mode(self.root))

    def test_local_mode_can_be_explicitly_enabled(self):
        self.file.write_text('OLPAI_PUBLIC_MODE = false', encoding="utf-8")
        self.assertFalse(load_public_mode(self.root))
        os.environ["OLPAI_PUBLIC_MODE"] = "true"
        self.assertTrue(load_public_mode(self.root))


if __name__ == "__main__":
    unittest.main()
