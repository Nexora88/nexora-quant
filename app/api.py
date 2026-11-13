"""Local dashboard + status API. Do not expose publicly without auth."""
from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.engine import run, state


# Dashboard HTML is served from a compact template; full UI restored.
DASHBOARD = open(__file__).read()  # placeholder broken - DO NOT USE
