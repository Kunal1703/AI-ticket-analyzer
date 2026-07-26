"""
Shared test configuration and fixtures.
"""

from collections.abc import AsyncGenerator, Callable, Generator

import pytest
from app.ai.base import AnalysisProvider
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def clear_cache() -> Generator[None, None, None]:
    """Clear the app's cache before/after each test to avoid cross-test leaks.

    Only the in-memory cache exposes a synchronous ``clear``; other backends
    (e.g. Redis) are not used in the test environment.
    """

    def _clear() -> None:
        from app.main import app

        clear = getattr(app.state.cache, "clear", None)
        if callable(clear):
            clear()

    _clear()
    yield
    _clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client bound to the FastAPI app."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def override_provider() -> Generator[Callable[[AnalysisProvider], None], None, None]:
    """Return a setter that overrides the injected AI provider for a test.

    The override is automatically cleared on teardown.
    """
    from app.dependencies import get_analysis_provider
    from app.main import app

    def _set(provider: AnalysisProvider) -> None:
        app.dependency_overrides[get_analysis_provider] = lambda: provider

    yield _set
    app.dependency_overrides.pop(get_analysis_provider, None)


@pytest.fixture
def override_db_sessionmaker() -> Generator[Callable[[object], None], None, None]:
    """Return a setter that overrides the injected DB session factory for a test.

    The override is automatically cleared on teardown.
    """
    from app.dependencies import get_db_sessionmaker
    from app.main import app

    def _set(sessionmaker: object) -> None:
        app.dependency_overrides[get_db_sessionmaker] = lambda: sessionmaker

    yield _set
    app.dependency_overrides.pop(get_db_sessionmaker, None)


@pytest.fixture
def override_cache() -> Generator[Callable[[object], None], None, None]:
    """Return a setter that overrides the injected cache for a test."""
    from app.dependencies import get_cache
    from app.main import app

    def _set(cache: object) -> None:
        app.dependency_overrides[get_cache] = lambda: cache

    yield _set
    app.dependency_overrides.pop(get_cache, None)
