# 23 — Prompt Versioning & Eval Harness (M5.1)

The first **Phase 5 (AI moat)** milestone. Makes the analysis prompt an explicit,
**versioned** artifact and adds an **eval harness** that scores analysis quality
against labeled cases, so prompt/model changes can be **gated in CI**. Files:
`app/prompts.py` (versioned registry), `app/ai/{base,config,openai_provider,
factory}.py` (thread the version), `app/eval/*` (harness + golden set + CLI),
`analyses.prompt_version` column + migration `0011`, `.github/workflows/eval.yml`.
Backend‑only; the frontend response gains an additive `prompt_version` field.

## Why

Prompt/model quality was previously invisible: a prompt edit could silently
regress classification accuracy, and there was no record of *which* prompt
produced an analysis. M5.1 makes prompts versioned + attributable and adds a
measurable, CI‑gateable quality signal — the foundation for the AI moat
(M5.2 RAG, M5.3 auto‑resolve all need eval‑gating).

## Prompt versioning (`app/prompts.py`)

The prompt is now a **registry of versions**, mirroring the provider/plan
registries (D3/D23):

```python
@dataclass(frozen=True)
class PromptVersion:
    version: str
    system_prompt: str
    user_prompt_builder: Callable[[str], str] = _build_user_prompt
    def messages(self, ticket_text) -> list[dict[str, str]]: ...

PROMPT_VERSIONS: dict[str, PromptVersion] = {"v1": PROMPT_V1, "v2": PROMPT_V2}  # append; never mutate
DEFAULT_PROMPT_VERSION = "v1"   # v2 (context-aware, M5.2) is opt-in via LLM_PROMPT_VERSION
def get_prompt(version: str | None = None) -> PromptVersion:    # fails safe to default
```

- **`v1`** is the pre‑M5.1 system prompt, unchanged (so historical behavior is
  identical). `get_prompt` **fails safe** to the default for `None`/unknown
  versions — the same conservative pattern as `get_plan`.
- **Selection:** `LLM_PROMPT_VERSION` (env) → `Settings.llm_prompt_version` →
  `ProviderConfig.prompt_version` → `get_prompt(...)` in `OpenAIProvider`. Unset ⇒
  default.
- **Back‑compat:** `SYSTEM_PROMPT` / `build_user_prompt` are still exported.
- **Golden rule:** **never edit a shipped version's text in place** — add a new
  version, so historical analyses stay attributable and evals stay comparable
  (the prompt analogue of "never edit a shipped migration").

The provider records the version it used on the result: `AnalysisResult` gained
`prompt_version: str | None`. It flows `run_analysis → persist_analysis →
add_analysis` into the new **`analyses.prompt_version`** column (nullable
`String(32)`, migration `0011_analysis_prompt_version` — additive/back‑compat,
like `model`). It is surfaced on the `AnalysisRead` API model (parallel to
`model`) for traceability.

## Eval harness (`app/eval/`)

Provider‑agnostic, pure‑scored, offline‑by‑default:

- **`harness.py`** — `EvalCase(ticket_text, expected_category, expected_priority)`,
  `run_eval(provider, cases) -> EvalReport` (analyzes each case; a `Provider*`
  error becomes an error outcome, not an abort), and pure metrics on `EvalReport`
  (`category_accuracy`, `priority_accuracy`, `exact_match_accuracy`, counts).
  `meets_threshold(report, min_category_accuracy, min_priority_accuracy)` is the
  gate; `summarize(report)` renders a human report with mismatches.
- **`golden.py`** — `GOLDEN_CASES`, a small curated fixture of unambiguously
  labeled tickets. Grow it, or derive cases from the `feedback` table's
  `corrected_category`/`corrected_priority` labels as real signal accumulates.
- **`__main__.py`** — `python -m app.eval`: builds the configured provider, runs
  the golden set, prints the report, and **exits non‑zero** when accuracy is
  below `EVAL_MIN_CATEGORY_ACCURACY` / `EVAL_MIN_PRIORITY_ACCURACY` (defaults
  0.80 / 0.60; priority is inherently fuzzier). This is the CI gate command.

Because `run_eval` takes any `AnalysisProvider`, the **default test suite scores
the harness deterministically with a fake provider** (no live LLM) — matching the
"strong tests without live infra" DNA. A **real** run needs a provider key.

## CI gate (`.github/workflows/eval.yml`)

A **manual, opt‑in** workflow (`workflow_dispatch`) that runs `python -m app.eval`
with a real `OPENAI_API_KEY` secret and the threshold inputs. It is **skipped when
no key secret is configured** (`if: secrets.OPENAI_API_KEY != ''`) and is
deliberately **off the per‑PR path** (live LLM calls cost money) — a maintainer
dispatches it on a branch to gate a prompt/model change before merge. The default
`ci.yml` (dummy key) is unchanged.

## Testing

- `tests/test_prompts.py` — registry: default/unknown fail‑safe, registered
  version, `messages()` shape, back‑compat exports.
- `tests/test_eval.py` — pure `EvalReport` metrics (incl. empty ⇒ 0.0, no
  ZeroDivision), `run_eval` all‑correct / partial / provider‑error via a
  `_FakeProvider`, `meets_threshold`, `summarize` content, golden‑set validity,
  and a **guarded opt‑in live eval** (`skipif` unless `RUN_LIVE_EVAL=1` + a real
  key).
- `tests/test_openai_provider.py` asserts the result records `prompt_version=v1`;
  `tests/test_repositories.py` asserts `add_analysis` persists it.
- Verified: **635 passed / 18 skipped**, **94.64% coverage** (gate 90%); migration
  `0011` verified offline.

## What must NEVER change

- Prompt versions are **append‑only** — never edit a shipped version's text
  (attribution + eval comparability). `get_prompt` stays fail‑safe.
- The `TicketAnalysis` structured‑output contract + `Provider*` translation are
  unchanged; `prompt_version` is additive (nullable column, additive API field).
- The eval harness stays **provider‑agnostic** and the **default test path needs
  no live LLM** (fake provider); the live gate is opt‑in (cost).

## Deferred / next

- **✅ M5.2 — RAG over the knowledge base — DONE:** an embeddings provider
  abstraction + a tenant‑isolated vector store behind a port, feeding retrieved
  context into `run_analysis`. It added an **append‑only context‑aware prompt
  `v2`** (v1 unchanged) selected with `LLM_PROMPT_VERSION=v2` + `RAG_ENABLED=true`;
  the eval harness stays comparable because `v2` is a new version, not an edit to
  `v1`. See [24_rag.md](24_rag.md).
- Feedback‑derived eval sets (build `EvalCase`s from `feedback` rows); per‑version
  A/B eval reports; regression‑tracking of accuracy over time; USD‑cost per eval.
