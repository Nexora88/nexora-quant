"""Live executor hardening is intentionally unavailable in paper-only builds."""


def harden_live_executor() -> None:
    """Fail closed instead of patching or enabling a real exchange executor."""
    raise RuntimeError("Live execution is disabled; no live executor can be hardened")
