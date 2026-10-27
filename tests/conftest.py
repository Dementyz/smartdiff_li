import subprocess
from pathlib import Path

import pytest

from smartdiff_li import _pycore, core

try:
    from smartdiff_li import _core
except ImportError:
    _core = None

BACKENDS = {"c": _core, "python": _pycore}


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")

    def git(self, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(self.root), *args],
                              capture_output=True, text=True, check=True)
        return proc.stdout

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def remove(self, path: str) -> None:
        (self.root / path).unlink()

    def commit(self, message: str = "commit") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


@pytest.fixture(autouse=True, params=list(BACKENDS))
def backend(request, monkeypatch):
    """Каждый тест прогоняется и с C-ядром, и с ядром на Python."""
    impl = BACKENDS[request.param]
    if impl is None:
        pytest.skip("C extension is not built (make ext)")
    monkeypatch.setattr(core, "_impl", impl)
    return impl
