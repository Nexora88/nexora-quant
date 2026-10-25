# Contributing

Thanks for helping improve Nexora Quant. Small, testable pull requests are preferred.

## Before opening a pull request
1. Open an issue for large features or behavior changes.
2. Keep strategy logic independent from execution adapters.
3. Every paper entry must pass the central risk gate.
4. Add or update tests for new behavior and failure cases.
5. Run `ruff check .` and `pytest`.
6. Update documentation when configuration, APIs, or limitations change.

## Boundaries
- Do not add live order placement, withdrawals, or account endpoints as an ordinary feature.
- Never commit API keys, tokens, account identifiers, or private datasets.
- Do not describe a signal as profitable without reproducible evidence and caveats.
- Do not weaken safety checks merely to make a test pass.

## Pull request checklist
- [ ] Scope is focused and described.
- [ ] Tests cover expected and failure behavior.
- [ ] No secrets or personal data are included.
- [ ] Documentation matches implementation.
- [ ] New risks are documented.
