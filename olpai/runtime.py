import atexit
import os
from pathlib import Path
import re
from threading import Lock

from .storage import Store


class ApplicationLock:
    """OS-owned lock: released even when the app process crashes."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a+b")
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError(
                "Một tiến trình chatbot khác đang dùng dữ liệu này. Hãy dùng cửa sổ app đang mở."
            ) from None
        atexit.register(self.close)

    def close(self):
        if not self.handle.closed:
            self.handle.close()


class Runtime:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._workspaces: dict[str, Store] = {}
        self._workspace_lock = Lock()
        self.lock = ApplicationLock(data_dir / ".app.lock")
        try:
            self.store = Store(data_dir / "chat.sqlite3")
            self.store.recover_interrupted()
        except BaseException:
            self.lock.close()
            raise

    def workspace_store(self, workspace_id: str) -> Store:
        if not re.fullmatch(r"[0-9a-f]{64}", workspace_id):
            raise ValueError("Invalid workspace identifier")
        with self._workspace_lock:
            if workspace_id not in self._workspaces:
                store = Store(self.data_dir / "workspaces" / workspace_id / "chat.sqlite3")
                store.recover_interrupted()
                self._workspaces[workspace_id] = store
            return self._workspaces[workspace_id]
