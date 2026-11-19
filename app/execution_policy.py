"""Execution-mode policy helpers."""


def maker_route_enabled(mode: str, prefer_maker: bool) -> bool:
    """Maker orders are only real exchange orders; PAPER must not fake queue fills."""
    return str(mode).strip().lower() == "live" and bool(prefer_maker)
