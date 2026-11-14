"""Isolate tests from local data and cloud credentials before importing the application."""
import os
import tempfile
from pathlib import Path

import pytest

# Settings capture the path at import time: set it before any test imports canary.
_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix='canary-tests-')
os.environ['CANARY_DB'] = str(Path(_TEST_DIRECTORY.name) / 'canary.db')


@pytest.fixture(autouse=True)
def offline_provider_environment(monkeypatch):
    from canary.config import settings
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(settings, 'llm_provider', 'none')
