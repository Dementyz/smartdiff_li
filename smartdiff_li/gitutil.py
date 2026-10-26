"""Работа с git: список изменённых файлов и чтение файлов из любой ревизии."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


@dataclass
class ChangedFile:
    path: str
    status: str  # A | M | D


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def git(root: Path, *args: str) -> str:
    proc = _run(root, *args)
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def repo_root(path: Path) -> Path:
    try:
        return Path(git(path, "rev-parse", "--show-toplevel").strip())
    except (GitError, FileNotFoundError) as exc:
        raise GitError(f"{path} is not inside a git repository") from exc


def _split(output: str) -> list[str]:
    return [part for part in output.split("\0") if part]


class WorkTree:
    """Рабочая копия: отслеживаемые и неотслеживаемые файлы, кроме игнорируемых."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def python_files(self) -> list[str]:
        out = git(self.root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        return sorted(p for p in _split(out)
                      if p.endswith(".py") and (self.root / p).is_file())

    def read(self, path: str) -> str | None:
        try:
            return (self.root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


class GitRev:
    """Дерево файлов на конкретной ревизии."""

    def __init__(self, root: Path, rev: str) -> None:
        self.root = root
        self.rev = rev

    def python_files(self) -> list[str]:
        out = git(self.root, "ls-tree", "-r", "-z", "--name-only", self.rev)
        return sorted(p for p in _split(out) if p.endswith(".py"))

    def read(self, path: str) -> str | None:
        proc = _run(self.root, "show", f"{self.rev}:{path}")
        return proc.stdout if proc.returncode == 0 else None


def changed_files(root: Path, base: str, head: str | None) -> list[ChangedFile]:
    """Файлы, изменённые между base и head (head=None: рабочая копия)."""
    args = ["diff", "--name-status", "--no-renames", "-z", base]
    if head is not None:
        args.append(head)
    parts = _split(git(root, *args))
    files = {parts[i + 1]: parts[i][0] for i in range(0, len(parts) - 1, 2)}
    if head is None:
        for path in _split(git(root, "ls-files", "-z", "--others", "--exclude-standard")):
            files.setdefault(path, "A")
    return [ChangedFile(path, status) for path, status in sorted(files.items())]


def _verify(root: Path, rev: str) -> str:
    if _run(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").returncode != 0:
        raise GitError(f"unknown revision: {rev}")
    return rev


def resolve_revisions(root: Path, revs: list[str]) -> tuple[str, str | None, str]:
    """Превращает аргументы CLI в (base, head, подпись). head=None: рабочая копия."""
    if len(revs) > 2:
        raise GitError("expected at most two revisions")
    if not revs:
        base, head = "HEAD", None
    elif len(revs) == 2:
        base, head = revs
    elif "..." in revs[0]:
        left, _, right = revs[0].partition("...")
        left, head = left or "HEAD", right or "HEAD"
        base = git(root, "merge-base", _verify(root, left), _verify(root, head)).strip()
    elif ".." in revs[0]:
        left, _, right = revs[0].partition("..")
        base, head = left or "HEAD", right or "HEAD"
    else:
        base, head = revs[0], None
    _verify(root, base)
    if head is not None:
        _verify(root, head)
    shown_base = revs[0].partition("...")[0] if len(revs) == 1 and "..." in revs[0] else base
    return base, head, f"{shown_base}..{head or 'working tree'}"
