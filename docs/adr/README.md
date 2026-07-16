# Architecture Decision Records (ADRs)

This directory records the consequential architectural decisions taken while
building the multi-language review translation & summarization pipeline. Each
ADR follows the same structure so a Solutions Architect encountering the
codebase can quickly reconstruct **why** the system looks the way it does:

- **Context** — the problem or constraint that forced the decision.
- **Alternatives considered** — 2–3 realistic options that were evaluated.
- **Decision** — the option chosen.
- **Rationale** — why the chosen option beat the alternatives, including
  trade-offs and what would push us to revisit the decision.

ADRs are immutable once accepted. To supersede an ADR, add a new one and mark
the old one as `Superseded by ADR-NNN` in its header.

References:

- [AWS Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html) — decision-making guidance
- Michael Nygard's original ADR template — [github.com/joelparkerhenderson/architecture-decision-record](https://github.com/joelparkerhenderson/architecture-decision-record)

## Index

| # | Title | Status |
|---|-------|--------|
| [ADR-001](adr-001-service-selection-for-translation.md) | Service selection for translation | Accepted |
| [ADR-002](adr-002-genai-service-for-summarization.md) | GenAI service for summarization | Accepted |
| [ADR-003](adr-003-orchestration-pattern.md) | Orchestration pattern | Accepted |
| [ADR-004](adr-004-pii-handling-strategy.md) | PII handling strategy | Accepted |
| [ADR-005](adr-005-quality-gate-implementation.md) | Quality-gate implementation | Accepted |
| [ADR-006](adr-006-translation-quality-scoring.md) | Translation quality scoring | Accepted |
