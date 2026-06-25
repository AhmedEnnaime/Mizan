import os

# Must be set before any module imports config.py
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GMAIL_USER", "test@gmail.com")
os.environ.setdefault("GMAIL_APP_PASSWORD", "test-password")
os.environ.setdefault("RECIPIENT_EMAIL", "recipient@test.com")

import pytest
import storage.db as db_module


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    db_module.init_db()
    return tmp_path / "test.db"
