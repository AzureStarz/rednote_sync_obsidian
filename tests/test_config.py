import rednote_sync_obsidian.config as config_module
from rednote_sync_obsidian.config import Settings, get_settings


def disable_dotenv(monkeypatch):
    monkeypatch.setattr(config_module, "load_dotenv", lambda *_args, **_kwargs: False)
    for name in [
        "LLM_PROVIDER",
        "LLM_API_STYLE",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "RAW_STORAGE_ROOT",
        "CRAWL_COOKIE",
    ]:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def test_deepseek_provider_defaults(monkeypatch):
    disable_dotenv(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    settings = Settings.from_env()
    assert settings.llm_provider == "deepseek"
    assert settings.llm_api_style == "chat_completions"
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-v4-pro"
    assert settings.llm_api_key == "sk-deepseek"


def test_openai_legacy_env_still_works(monkeypatch):
    disable_dotenv(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.5")
    settings = Settings.from_env()
    assert settings.llm_provider == "openai"
    assert settings.llm_api_style == "responses"
    assert settings.llm_model == "gpt-5.5"
    assert settings.llm_api_key == "sk-openai"


def test_worker_requires_raw_storage_not_llm_or_github():
    settings = Settings(redis_url="redis://test", raw_storage_root="/tmp/raw", llm_api_key="", github_token="", github_repo="")
    settings.require_worker()


def test_worker_requires_raw_storage_root():
    settings = Settings(redis_url="redis://test", raw_storage_root="")
    try:
        settings.require_worker()
    except RuntimeError as exc:
        assert "RAW_STORAGE_ROOT" in str(exc)
    else:
        raise AssertionError("require_worker should reject missing RAW_STORAGE_ROOT")
