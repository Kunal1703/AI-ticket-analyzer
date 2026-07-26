"""
Tests for the versioned prompt registry (M5.1).
"""

from app.prompts import (
    DEFAULT_PROMPT_VERSION,
    PROMPT_VERSIONS,
    SYSTEM_PROMPT,
    available_prompt_versions,
    build_user_prompt,
    get_prompt,
)


class TestPromptRegistry:
    def test_default_version_is_registered(self) -> None:
        assert DEFAULT_PROMPT_VERSION in PROMPT_VERSIONS
        assert available_prompt_versions() == sorted(PROMPT_VERSIONS)

    def test_get_prompt_defaults_and_fails_safe(self) -> None:
        assert get_prompt(None).version == DEFAULT_PROMPT_VERSION
        # Unknown version falls back to the default (never raises).
        assert get_prompt("does-not-exist").version == DEFAULT_PROMPT_VERSION

    def test_get_prompt_returns_registered_version(self) -> None:
        assert get_prompt("v1").version == "v1"

    def test_messages_shape(self) -> None:
        messages = get_prompt("v1").messages("My ticket text")
        assert [m["role"] for m in messages] == ["system", "user"]
        assert "My ticket text" in messages[1]["content"]
        assert messages[0]["content"] == get_prompt("v1").system_prompt

    def test_backcompat_exports(self) -> None:
        # Pre-M5.1 imports still work and match the v1 prompt.
        assert get_prompt("v1").system_prompt == SYSTEM_PROMPT
        assert "TICKET START" in build_user_prompt("hello")
