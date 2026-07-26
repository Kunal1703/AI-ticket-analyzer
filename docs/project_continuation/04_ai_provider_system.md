# 04 — AI Provider System

This is the **template abstraction** for the whole project. The auth and tenancy layers were modeled on it. Understand this document deeply before adding any pluggable subsystem.

Files: `app/ai/base.py`, `app/ai/config.py`, `app/ai/openai_provider.py`, `app/ai/factory.py`, `app/ai/__init__.py`, plus the back‑compat shim `app/openai_client.py`.

## Why the abstraction exists

The origin app called the OpenAI SDK directly inside the endpoint. Two problems: (1) the business logic was coupled to one vendor, and (2) OpenAI's exception types leaked into HTTP mapping. The abstraction makes the **business logic depend only on `AnalysisProvider` + provider‑agnostic errors**, so:

- adding a new LLM backend requires **zero** changes to routes, services, persistence, or error mapping;
- the app can run against OpenAI, Groq, Together, OpenRouter, Ollama (local, no key), or any OpenAI‑compatible endpoint — chosen purely by config.

This was built in M0.5 (the seam) and completed by the "provider‑agnostic refactor" (config generalization + OpenAI‑compatible family), before M1.3.

## The interface (`app/ai/base.py`)

```python
class AnalysisProvider(ABC):
    @property @abstractmethod
    def name(self) -> str: ...          # "openai", "groq", ...
    @property @abstractmethod
    def model(self) -> str: ...         # resolved model id (used for persistence)
    @abstractmethod
    async def analyze(self, ticket_text: str) -> AnalysisResult: ...
    async def aclose(self) -> None: ... # default no-op; override to close clients
```

Result + usage (added M1.4):
```python
@dataclass(frozen=True)
class TokenUsage:  prompt_tokens: int; completion_tokens: int; total_tokens: int
@dataclass(frozen=True)
class AnalysisResult: analysis: TicketAnalysis; usage: TokenUsage | None = None
                       prompt_version: str | None = None   # M5.1
```

**Prompt versioning (M5.1):** prompts are a **versioned registry** in
`app/prompts.py` (`PromptVersion` + `PROMPT_VERSIONS` + `get_prompt`, mirroring
`_PROVIDERS`), selected via `LLM_PROMPT_VERSION` → `ProviderConfig.prompt_version`.
`OpenAIProvider` builds messages from `get_prompt(config.prompt_version)` and
records the version on `AnalysisResult.prompt_version`, which flows to
`analyses.prompt_version` (persistence) and the eval harness. **Never edit a
shipped prompt version in place — add a new one.** See [23_prompts_eval.md](23_prompts_eval.md).

**Provider‑agnostic error hierarchy (the crux — NEVER remove):**
```
ProviderError                    → HTTP 502 ("AI service unavailable")
 ├─ ProviderTimeoutError         → HTTP 504
 ├─ ProviderRateLimitError       → HTTP 429
 ├─ ProviderConnectionError      → HTTP 502
 └─ ProviderResponseError        → HTTP 502 ("Invalid AI response") — refusal/unparseable
```

**Contract:** every provider MUST translate its SDK's exceptions into these. The `/analyze` route catches only these. If you add a provider that raises its own SDK exceptions without translating, you have broken the abstraction.

## ProviderConfig (`app/ai/config.py`)

```python
@dataclass(frozen=True)
class ProviderConfig:
    provider: str; model: str
    api_key: str | None = None; base_url: str | None = None
    timeout: int = 30; max_retries: int = 3; temperature: float = 0.2
```

**Why a neutral config object instead of passing `Settings`:** providers depend only on the fields they need, not on the app‑wide settings. This decouples providers from configuration and makes them trivially unit‑testable (`OpenAIProvider(ProviderConfig(...))`). The factory builds a `ProviderConfig` from `Settings`.

## Factory + registry (`app/ai/factory.py`)

```python
@dataclass(frozen=True)
class ProviderSpec:
    factory: Callable[[ProviderConfig], AnalysisProvider]
    default_base_url: str | None = None
    default_model: str | None = None
    requires_api_key: bool = True
    requires_base_url: bool = False

_PROVIDERS: dict[str, ProviderSpec] = {
    "openai":            ProviderSpec(OpenAIProvider, default_model="gpt-4o-2024-08-06"),
    "groq":              ProviderSpec(OpenAIProvider, default_base_url="https://api.groq.com/openai/v1"),
    "together":          ProviderSpec(OpenAIProvider, default_base_url="https://api.together.xyz/v1"),
    "openrouter":        ProviderSpec(OpenAIProvider, default_base_url="https://openrouter.ai/api/v1"),
    "ollama":            ProviderSpec(OpenAIProvider, default_base_url="http://localhost:11434/v1",
                                      default_model="llama3.1", requires_api_key=False),
    "openai-compatible": ProviderSpec(OpenAIProvider, requires_api_key=False, requires_base_url=True),
}
```

- `build_provider_config(settings)` resolves base_url/model with per‑provider defaults and **validates per‑provider requirements** (e.g., `openai` requires a key → clear `ValueError`; `ollama` needs none; `openai-compatible` requires `LLM_BASE_URL`).
- `build_provider(settings)` builds the config and returns `spec.factory(config)`.

**Why one class serves many providers:** Groq/Together/OpenRouter/Ollama all speak the OpenAI API; only `base_url`/`api_key`/`model` differ. `OpenAIProvider` accepts `base_url`, so it covers the entire OpenAI‑compatible family with no new code.

## OpenAIProvider (`app/ai/openai_provider.py`)

- Lazily builds `AsyncOpenAI(api_key, base_url, timeout, max_retries=0)` (SDK retries off — we retry via tenacity for finer control). For keyless providers (Ollama) a placeholder key is used because the SDK requires a non‑empty string.
- `analyze` runs `_request_analysis` inside `tenacity.AsyncRetrying` (attempts = `config.max_retries`, `wait_exponential`, retry on `APIConnectionError/APITimeoutError/RateLimitError`), then **translates** exceptions into `Provider*`.
- Uses `client.beta.chat.completions.parse(..., response_format=TicketAnalysis, temperature=...)` (structured outputs). Defensive checks for `message.refusal` and `message.parsed is None` → `ValueError` → `ProviderResponseError`.
- `_extract_usage` reads `completion.usage` best‑effort into `TokenUsage` (malformed usage → `None`, never raises).
- `aclose` closes the client.

## Configuration (provider‑agnostic)

`Settings` (see `app/config.py`) uses **generic `LLM_*`** fields, with **`OPENAI_*` accepted as backward‑compatible environment aliases** (via `AliasChoices`):

| Setting | Env (+ alias) | Notes |
|---|---|---|
| `ai_provider` | `AI_PROVIDER` | default `"openai"` |
| `llm_api_key` | `LLM_API_KEY` / `OPENAI_API_KEY` | **optional** (Ollama needs none) |
| `llm_model` | `LLM_MODEL` / `OPENAI_MODEL` | None → provider default |
| `llm_base_url` | `LLM_BASE_URL` | per‑provider default or SDK default |
| `llm_timeout` | `LLM_TIMEOUT` / `OPENAI_TIMEOUT` | |
| `llm_max_retries` | `LLM_MAX_RETRIES` / `OPENAI_MAX_RETRIES` | `Field(ge=1)` — 0 would never call the provider |
| `llm_temperature` | `LLM_TEMPERATURE` | default 0.2 |

> **CRITICAL TESTING GOTCHA (do not relearn the hard way):** the `OPENAI_*` aliases work for **environment variables** but **NOT as init kwargs when the env var is also present** (pydantic‑settings raises `extra_forbidden`). Tests must construct `Settings(_env_file=None, llm_api_key=...)` using the **canonical `llm_*` names**, never `openai_api_key=`. CI sets `OPENAI_API_KEY`, which would break kwarg‑alias tests. This bug was caught and fixed during the provider‑agnostic refactor.

## Future Anthropic / Gemini support

Anthropic and Gemini speak **different** APIs (not OpenAI‑compatible), so they are **registry‑ready but intentionally not implemented** (consistent with the user's "create the interface, don't implement those yet" directive). To add one:

1. Add the SDK to `requirements.txt` (`anthropic`, `google-genai`).
2. Create `app/ai/anthropic_provider.py` implementing `AnalysisProvider` (its own structured‑output mechanism: Anthropic tool‑use / Gemini `response_schema`), **translating its errors into `Provider*`**.
3. Add one `_PROVIDERS["anthropic"] = ProviderSpec(AnthropicProvider, ...)` entry.
4. Add tests (translation of each error type, success, refusal). No business‑logic changes.

Some OpenAI‑compatible endpoints (e.g., certain Ollama models) don't support `json_schema` structured outputs; a future variant provider could use JSON‑mode + manual validation. The abstraction already supports adding it.

**Embeddings sibling (M5.2):** the RAG layer reuses this exact template in
`app/embeddings/` — an `EmbeddingProvider` ABC + `Embedding*` error hierarchy +
`EmbeddingConfig` + a `_EMBEDDING_PROVIDERS` registry (`OpenAIEmbeddingProvider`
for the OpenAI‑compatible family + a keyless deterministic `hash` provider). Same
rules: business logic depends only on the ABC, providers translate SDK errors, one
class serves many backends. See [24_rag.md](24_rag.md). M5.2 also added an
**additive** `analyze(ticket_text, *, context=None)` param (RAG grounding): `None`
reproduces prior behavior, and the context is folded in by the selected
`PromptVersion` — the `AnalysisResult` contract and `Provider*` translation are
unchanged.

## What must NEVER change

- The **`Provider*` exception hierarchy** and the rule that providers translate into it. Business logic depends on it.
- `analyze` returning `AnalysisResult` (analysis + optional usage) — not a bare `TicketAnalysis`. The split keeps the response/cache shape stable while surfacing usage. The `context` kwarg (M5.2) is additive and optional.
- The route catching only `Provider*` errors (never SDK exceptions).

## Tradeoffs

- **One `OpenAIProvider` for many backends** trades a little per‑provider clarity for huge code reuse. Acceptable because the API is genuinely identical.
- **tenacity inside the provider** (not centralized) means each provider owns its retry policy — correct, because retryable exception types differ by SDK.
- **`beta.chat.completions.parse`** is a beta SDK surface (noted as debt). Migrate when the stable path lands; the change is isolated to `OpenAIProvider`.

## The back‑compat shim (`app/openai_client.py`)

`analyze_ticket(text, settings=None)` still works (`from app.openai_client import analyze_ticket`) and delegates to `build_provider(...).analyze(...).analysis`. It's a thin, deprecated facade for legacy imports — the app itself uses the DI provider. Don't build new features on it.
