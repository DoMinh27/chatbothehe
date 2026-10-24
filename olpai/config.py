import os
from pathlib import Path

import toml

from .models import ChatError


def read_settings(project_dir: Path) -> dict:
    path = project_dir / ".streamlit" / "secrets.toml"
    if not path.exists():
        return {}
    try:
        return toml.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, toml.TomlDecodeError):
        # Parser errors can contain the key's source line. Never display them.
        raise ChatError(
            'Không đọc được .streamlit/secrets.toml. Dùng định dạng GEMINI_API_KEY = "key của bạn".'
        ) from None


def load_public_mode(project_dir: Path) -> bool:
    override = os.environ.get("OLPAI_PUBLIC_MODE")
    if override is not None:
        if override.lower().strip() in {"1", "true", "yes"}:
            return True
        if override.lower().strip() in {"0", "false", "no"}:
            return False
        raise ChatError("OLPAI_PUBLIC_MODE phải là true hoặc false.")
    value = read_settings(project_dir).get("OLPAI_PUBLIC_MODE", True)
    if not isinstance(value, bool):
        raise ChatError("OLPAI_PUBLIC_MODE trong secrets.toml phải là true hoặc false.")
    return value


def load_api_key(project_dir: Path) -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    settings = read_settings(project_dir)
    value = settings.get("GEMINI_API_KEY", "")
    if not isinstance(value, str):
        raise ChatError('GEMINI_API_KEY trong secrets.toml phải là chuỗi đặt trong dấu nháy kép.')
    return value.strip()
