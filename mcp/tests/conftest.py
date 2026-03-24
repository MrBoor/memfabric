import json
import logging
import shutil
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Patch server module to use a fresh tmp directory for every test."""
    import server

    memory_dir = tmp_path / "memory"
    system_dir = tmp_path / "system"
    rules_file = system_dir / "rules.md"
    status_file = system_dir / "status.json"

    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "MEMORY_DIR", memory_dir)
    monkeypatch.setattr(server, "SYSTEM_DIR", system_dir)
    monkeypatch.setattr(server, "RULES_FILE", rules_file)
    monkeypatch.setattr(server, "STATUS_FILE", status_file)
    monkeypatch.setattr(server, "LOG_FILE", tmp_path / "log.txt")

    server._ensure_dirs()

    yield tmp_path
