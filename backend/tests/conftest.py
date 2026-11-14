"""Isolate tests from local data and cloud credentials before importing the application."""
import os
import tempfile
from pathlib import Path

import pytest

# Settings are read at import time: set everything before any test imports canary.
_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix='canary-tests-')
# Never read the developer's .env (real keys, local timeouts) during tests; config.py honours this flag.
os.environ['CANARY_SKIP_DOTENV'] = '1'
os.environ['CANARY_DB'] = str(Path(_TEST_DIRECTORY.name) / 'canary.db')
os.environ['CANARY_LLM_PROVIDER'] = 'none'
os.environ['CANARY_LLM_MODEL'] = ''
os.environ['CANARY_LLM_TIMEOUT_S'] = '15'
os.environ['GEMINI_API_KEY'] = ''
os.environ['ANTHROPIC_API_KEY'] = ''
# CANARY_KB keeps the application default (backend/kb.db, read-only); tests that need it skip when it is missing.


@pytest.fixture(autouse=True)
def offline_provider_environment(monkeypatch):
    from canary.config import settings
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(settings, 'llm_provider', 'none')
    monkeypatch.setattr(settings, 'llm_model', '')
    monkeypatch.setattr(settings, 'llm_timeout_s', 15.0)
