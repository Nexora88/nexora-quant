"""Fail-closed compatibility stub: live exchange execution is disabled."""

class LiveExecutor:
    """Placeholder retained only so legacy imports fail safely and explicitly."""

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError("LiveExecutor is disabled; use the paper simulator only")


__all__ = ["LiveExecutor"]
