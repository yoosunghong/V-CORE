import pytest


@pytest.fixture(autouse=True)
def use_rule_based_llm_for_unit_tests(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "rule_based")
    monkeypatch.setenv("SESSION_REPOSITORY", "memory")
    monkeypatch.setenv("UE5_CLIENT_MODE", "mock")
    monkeypatch.setenv("AUTO_COMPLETE_DEMO_COMMANDS", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
