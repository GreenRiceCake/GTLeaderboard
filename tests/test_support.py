"""Temporary test folders with inherited Windows workspace permissions."""

from pathlib import Path
from uuid import uuid4


class WorkspaceDirectory:
    def __init__(self):
        self.root = Path(__file__).resolve().parents[1] / "artifacts" / "tests"
        self.path = self.root / uuid4().hex
        self.path.mkdir(parents=True)
        self.name = str(self.path)

    def cleanup(self):
        if self.path.resolve().parent != self.root.resolve():
            raise RuntimeError("Test cleanup path escaped its workspace.")
        # These tests only create flat files. Avoid any recursive cleanup.
        for child in self.path.iterdir():
            child.unlink()
        self.path.rmdir()

    def __enter__(self):
        return self.name

    def __exit__(self, *_):
        self.cleanup()

