"""Host actions are structured file operations, never arbitrary shell execution."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from .policy import FORBIDDEN, GOVERNANCE, matches, safe_relative


class WorkspaceGuard:
    def __init__(self, root, allowed, max_bytes=100_000):
        self.root = Path(root).resolve(strict=True)
        if self.root == Path.home() or str(self.root).startswith("/home/optiplex/investment"):
            raise ValueError("production or home workspace denied")
        self.allowed = frozenset(allowed)
        for name in self.allowed:
            safe_relative(name)
            if matches(name, FORBIDDEN) or matches(name, GOVERNANCE) or name.startswith((".todos/", "docs/plans/", "owner_gateway/", "deployment_agent/", "dev_agent/", "systemd/", "ops/")):
                raise ValueError("protected write scope")
        self.max_bytes = max_bytes

    def resolve(self, name, write=False):
        safe_relative(name)
        if matches(name, FORBIDDEN) or (write and name not in self.allowed):
            raise ValueError("operation denied")
        path = self.root / name
        current = self.root
        for part in Path(name).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("symlink denied")
            if current.exists() and not (current.is_file() or current.is_dir()):
                raise ValueError("special file denied")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("workspace escape")
        return path

    def read(self, name):
        path = self.resolve(name)
        if path.stat().st_size > self.max_bytes:
            raise ValueError("context too large")
        return path.read_text()

    def write(self, name, text):
        if not isinstance(text, str) or len(text.encode()) > self.max_bytes:
            raise ValueError("diff budget exceeded")
        path = self.resolve(name, True)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Provider has no filesystem/process access. Reject hard links as well.
        if path.exists() and path.stat().st_nlink != 1:
            raise ValueError("hardlink denied")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)

    def apply(self, action):
        if set(action) != {"type", "path", "content"} or action["type"] != "write":
            raise ValueError("only scoped text writes are supported; shell/network denied")
        self.write(action["path"], action["content"])
