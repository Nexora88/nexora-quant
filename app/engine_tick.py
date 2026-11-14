"""TEMPORARY: broken placeholder after bad push. Run recovery:

  git fetch origin 7a4ee79d74fbf286eac46956a0a04d7423972e81
  python scripts/restore_engine_tick.py
  git add app/engine_tick.py && git commit -m "fix: restore engine_tick" && git push

Until then, imports will fail on purpose so CI does not look healthy.
"""
raise RuntimeError(
    "app/engine_tick.py needs restore. Run: python scripts/restore_engine_tick.py"
)
