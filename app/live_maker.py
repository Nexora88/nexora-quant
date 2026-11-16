"""Compatibility names for disabled live maker execution."""


def install_buy_limit(LiveExecutor: type) -> None:
    raise RuntimeError("Live maker orders are disabled; use paper simulation only")


install_maker_entry = install_buy_limit
