"""Package only allow-listed source files, never personal keys or chat data."""
from pathlib import Path
import zipfile


def build_public_package(root: Path) -> Path:
    destination = root / "dist" / "olpai-chat-public.zip"
    destination.parent.mkdir(exist_ok=True)
    files = [
        "app.py", "check_api.py", "package_public.py", "requirements.txt",
        "requirements.lock.txt", "README.md", "DEPLOY.md", "run.ps1", ".gitignore",
        ".streamlit/config.toml", ".streamlit/secrets.toml.example",
    ]
    files += [str(path.relative_to(root)) for path in (root / "olpai").glob("*.py")]
    files += [str(path.relative_to(root)) for path in (root / "tests").glob("*.py")]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(files):
            archive.write(root / relative, Path(relative).as_posix())
    return destination


if __name__ == "__main__":
    print(build_public_package(Path(__file__).resolve().parent))
