"""Prompts for each specialist agent. Contract every generated app must follow is in CONTRACT."""
CONTRACT = """App contract (MUST follow):
- Python 3, FastAPI, sqlite3 from the standard library only (no ORM, no extra packages besides fastapi, uvicorn, pydantic, httpx for tests).
- Backend in app/main.py exposing `app = FastAPI(...)`; also create an empty app/__init__.py.
- DB path: `DB_PATH = os.environ.get("APP_DB", "app.db")`; create tables at import time (CREATE TABLE IF NOT EXISTS). Open a new sqlite3 connection per request.
- JSON API under /api/... ; GET / returns static/index.html via FileResponse(Path(__file__).resolve().parent.parent / "static" / "index.html").
- Frontend: single static/index.html with inline CSS + vanilla JS calling the /api endpoints with fetch (relative URLs). No build step, no CDN.
- Tests: tests/test_api.py with pytest + fastapi.testclient.TestClient. At the very top, before importing the app: `import os, tempfile; os.environ["APP_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")`. Then `from app.main import app`."""

PLANNER = """You are the PLANNER agent in a multi-agent app builder.
User request: {prompt}
{contract}
Produce a concise spec. Reply with ONLY JSON:
{{"app_name": "...", "slug": "kebab-case-name", "summary": "...",
 "entities": [{{"name": "...", "fields": {{"field": "type and notes"}}}}],
 "endpoints": [{{"method": "GET|POST|PUT|PATCH|DELETE", "path": "/api/...", "description": "request/response shape"}}],
 "frontend": "what the page shows and does",
 "files": ["app/__init__.py", "app/main.py", "static/index.html", "tests/test_api.py"]}}"""

BACKEND = """You are the BACKEND agent. Implement the backend exactly per this spec.
Spec:
{spec}
{contract}
Return app/__init__.py and app/main.py.
{fmt}"""

FRONTEND = """You are the FRONTEND agent. Build static/index.html for this spec, calling the existing backend.
Spec:
{spec}
Backend (app/main.py):
{backend}
{contract}
Return only static/index.html.
{fmt}"""

TESTER = """You are the TESTER agent. Write pytest tests covering every endpoint in the spec (happy paths, 404/422 cases, and GET / returning HTML).
Spec:
{spec}
Backend (app/main.py):
{backend}
{contract}
Return only tests/test_api.py.
{fmt}"""

DEBUGGER = """You are the DEBUGGER agent. The generated app fails verification. Find the root cause and fix it.
Prefer fixing the app; only change a test if the test itself contradicts the spec.
Spec:
{spec}
Files:
{files}
Pytest output:
{pytest}
HTTP smoke test:
{smoke}
Return ONLY the files you change, in full.
{fmt}"""
