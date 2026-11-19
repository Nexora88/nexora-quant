"""Keep developer .env settings out of the automated test environment."""
import os

# App configuration loads .env at import time. Tests must exercise deterministic
# defaults and explicit overrides, not the operator's private paper-account profile.
os.environ.setdefault("PYTHON_DOTENV_DISABLED", "true")
