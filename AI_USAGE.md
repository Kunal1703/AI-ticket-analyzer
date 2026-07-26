# AI Usage Disclosure

This document provides transparency about how AI tools were used during the development of AI Ticket Analyzer.

## AI Tools Used

| Tool | Version | Purpose |
|------|---------|---------|
| GitHub Copilot | Latest | Code autocompletion and inline suggestions |
| ChatGPT (GPT-4o) | Latest | Architecture brainstorming and prompt engineering |
| Claude (Anthropic) | Claude 3.5 Sonnet | Code review, documentation drafting |

## What AI Generated

### Code Generation
- **Initial boilerplate** — FastAPI app scaffold, Dockerfile, docker-compose.yml, and .gitignore were generated with AI assistance and then customized
- **Pydantic models** — Base model structure was AI-suggested; enum values and field validators were manually specified based on requirements
- **Test scaffolding** — pytest fixtures and test structure were AI-assisted; specific test cases and assertions were manually designed
- **Prompt engineering** — The system prompt was iteratively refined with AI assistance, but the priority guidelines and classification rules were manually crafted based on domain knowledge

### Documentation
- **README.md** — Structure and formatting were AI-assisted; technical content was manually verified
- **architecture.md** — Mermaid diagrams were AI-generated and manually verified; the architecture comparison table content was a mix of AI suggestions and manual analysis

## What Was Manually Reviewed

### Architecture Decisions
- **Direct OpenAI vs. LangChain** — Manually evaluated trade-offs based on dependency weight, use-case complexity, and maintenance burden
- **Structured outputs vs. free-form parsing** — Manually tested both approaches to confirm structured outputs' reliability advantage
- **Retry strategy** — Tenacity configuration (exponential backoff, selective retry on transient errors) was manually designed based on OpenAI's rate limit documentation
- **Caching strategy** — Decision to use in-memory LRU over Redis was a manual trade-off between simplicity and scalability

### Code Quality
- **Type hints** — Verified all function signatures and return types manually
- **Error handling** — Each error path (timeout, rate limit, connection error, validation error) was manually traced through the code
- **Security** — Ensured API key is loaded from environment variables only, `.env` is gitignored, Docker runs as non-root user

## What Was Manually Tested

### Local Testing
- ✅ All pytest tests run successfully with mocked OpenAI responses
- ✅ Model validation tests cover edge cases (empty tickets, invalid categories, boundary lengths)
- ✅ API tests verify correct HTTP status codes for error scenarios
- ✅ End-to-end manual testing with real OpenAI API calls to verify structured output parsing

### Docker Testing
- ✅ `docker build` completes without errors
- ✅ `docker run` starts the server and responds to health checks
- ✅ `docker-compose up` orchestrates the service correctly

### Integration Testing
- ✅ Verified OpenAI structured outputs produce valid `TicketAnalysis` responses
- ✅ Tested with various ticket types (billing, technical, bug reports) to confirm category accuracy
- ✅ Confirmed retry logic activates on simulated transient failures
- ✅ Validated cache hit/miss behavior with identical and different tickets

## Engineering Decisions Requiring Human Review

| Decision | AI Suggested | Human Reviewed and Modified |
|----------|-------------|---------------------------|
| OpenAI model selection (`gpt-4o-2024-08-06`) | ✅ | ✅ Confirmed model supports structured outputs |
| Temperature setting (0.2) | ✅ | ✅ Tested different values; 0.2 gives consistent classification |
| Max ticket length (5000 chars) | ❌ Manual | ✅ Based on typical support ticket length analysis |
| Cache size (128 entries) | ✅ | ✅ Appropriate for single-instance deployment |
| Retry count (3 attempts) | ✅ | ✅ Aligned with OpenAI best practices |
| Non-root Docker user | ❌ Manual | ✅ Security best practice |
| No authentication layer | ❌ Manual | ✅ Intentional for assessment scope; noted as future improvement |

## Summary

AI tools were used as **accelerators** — for scaffolding, drafting, and suggesting patterns. All critical decisions around architecture, security, error handling, and prompt engineering were made or validated by a human engineer. The final codebase reflects deliberate engineering choices, not unreviewed AI output.
