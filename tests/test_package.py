from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from package_public import build_public_package


class PublicPackageTests(unittest.TestCase):
    def test_package_contains_source_but_excludes_credentials_and_chat_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            names = [
                "app.py", "check_api.py", "package_public.py", "requirements.txt",
                "requirements.lock.txt", "README.md", "DEPLOY.md", "run.ps1", ".gitignore",
                ".streamlit/config.toml", ".streamlit/secrets.toml.example", "olpai/__init__.py",
                "tests/test_example.py",
            ]
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("public source", encoding="utf-8")
            for name in [".streamlit/secrets.toml", ".env", "data/chat.sqlite3", ".venv/private.txt"]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("PRIVATE-TEST-SENTINEL", encoding="utf-8")
            with zipfile.ZipFile(build_public_package(root)) as archive:
                self.assertIn("app.py", archive.namelist())
                self.assertIn("olpai/__init__.py", archive.namelist())
                self.assertNotIn(".streamlit/secrets.toml", archive.namelist())
                self.assertNotIn(".env", archive.namelist())
                self.assertFalse(any(name.startswith(("data/", ".venv/")) for name in archive.namelist()))
                for name in archive.namelist():
                    self.assertNotIn(b"PRIVATE-TEST-SENTINEL", archive.read(name))


if __name__ == "__main__":
    unittest.main()
