"""
Tests for the application factory and lifespan (Milestone M1.0).

Verifies that ``create_app`` wires shared resources onto ``app.state`` and that
the lifespan handler releases the provider's resources on shutdown.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.config import Settings
from app.main import create_app, lifespan


def _settings(**overrides: object) -> Settings:
    """Build Settings without reading the local .env file."""
    base: dict[str, object] = {"llm_api_key": "sk-test-dummy"}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type, call-arg]


class TestCreateApp:
    """create_app builds an app with shared resources on app.state."""

    def test_builds_shared_state(self) -> None:
        app = create_app(_settings())
        assert app.state.settings is not None
        assert app.state.cache is not None
        assert app.state.provider is not None

    def test_uses_provided_settings(self) -> None:
        app = create_app(_settings(app_version="9.9.9"))
        assert app.state.settings.app_version == "9.9.9"

    def test_no_database_url_means_no_sessionmaker(self) -> None:
        app = create_app(_settings())
        assert app.state.db_engine is None
        assert app.state.db_sessionmaker is None

    def test_database_url_builds_sessionmaker(self) -> None:
        app = create_app(_settings(database_url="postgresql+psycopg://u:p@localhost:5432/db"))
        assert app.state.db_engine is not None
        assert app.state.db_sessionmaker is not None

    def test_no_jwt_secret_means_no_token_service(self) -> None:
        assert create_app(_settings()).state.token_service is None

    def test_jwt_secret_builds_token_service(self) -> None:
        app = create_app(_settings(jwt_secret="super-secret"))
        assert app.state.token_service is not None

    def test_starts_without_api_key_for_keyless_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Core requirement: no OpenAI key needed when another provider is used.
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        app = create_app(Settings(_env_file=None, ai_provider="ollama"))  # type: ignore[call-arg]
        assert app.state.provider.name == "ollama"


class TestLifespan:
    """The lifespan handler closes the provider on shutdown."""

    @pytest.mark.anyio
    async def test_lifespan_closes_provider(self) -> None:
        app = create_app(_settings())
        mock_provider = MagicMock()
        mock_provider.aclose = AsyncMock()
        app.state.provider = mock_provider

        async with lifespan(app):
            pass

        mock_provider.aclose.assert_awaited_once()

    @pytest.mark.anyio
    async def test_lifespan_closes_cache(self) -> None:
        app = create_app(_settings())
        mock_cache = MagicMock()
        mock_cache.aclose = AsyncMock()
        app.state.cache = mock_cache

        async with lifespan(app):
            pass

        mock_cache.aclose.assert_awaited_once()

    @pytest.mark.anyio
    async def test_lifespan_disposes_db_engine(self) -> None:
        app = create_app(_settings(database_url="postgresql+psycopg://u:p@localhost:5432/db"))
        mock_provider = MagicMock()
        mock_provider.aclose = AsyncMock()
        app.state.provider = mock_provider
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        app.state.db_engine = mock_engine

        async with lifespan(app):
            pass

        mock_engine.dispose.assert_awaited_once()
