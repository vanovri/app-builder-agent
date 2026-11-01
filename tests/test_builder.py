import json

from builder.llm import MockLLM
from builder.orchestrator import AppBuilder

SPEC = {"app_name": "Mini Todo", "slug": "mini-todo", "summary": "todos",
        "endpoints": [{"method": "GET", "path": "/api/todos"}, {"method": "POST", "path": "/api/todos"}]}
MAIN_OK = '''import os, sqlite3
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
DB_PATH = os.environ.get("APP_DB", "app.db")
with sqlite3.connect(DB_PATH) as c:
    c.execute("CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, title TEXT)")
app = FastAPI()
class T(BaseModel):
    title: str
@app.get("/")
def index():
    return FileResponse(Path(__file__).resolve().parent.parent / "static" / "index.html")
@app.get("/api/todos")
def list_todos():
    with sqlite3.connect(DB_PATH) as c:
        return [{"id": i, "title": t} for i, t in c.execute("SELECT id, title FROM todos")]
@app.post("/api/todos", status_code=201)
def add(t: T):
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute("INSERT INTO todos (title) VALUES (?)", (t.title,))
        return {"id": cur.lastrowid, "title": t.title}
'''
BACKEND_OK = f"=== FILE: app/__init__.py ===\n=== END ===\n=== FILE: app/main.py ===\n{MAIN_OK}=== END ==="
BACKEND_BROKEN = BACKEND_OK.replace('return {"id": cur.lastrowid, "title": t.title}', 'return {"id": cur.lastrowid, "title": t.titel}')
FRONT = "=== FILE: static/index.html ===\n<html><body><h1>Todos</h1></body></html>\n=== END ==="
TESTS = '''=== FILE: tests/test_api.py ===
import os, tempfile
os.environ["APP_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
def test_flow():
    assert c.post("/api/todos", json={"title": "x"}).status_code == 201
    assert c.get("/api/todos").json()[0]["title"] == "x"
def test_index():
    assert "<h1>" in c.get("/").text
=== END ==='''


def test_build_passes_first_try(tmp_path):
    llm = MockLLM([json.dumps(SPEC), BACKEND_OK, FRONT, TESTS])
    events = []
    b = AppBuilder(llm, out_root=tmp_path, on_event=events.append).build("todo app")
    assert b.passed, b.trace
    assert [e["agent"] for e in b.trace] == ["planner", "backend", "frontend", "tester", "verify", "orchestrator"]
    ws = tmp_path / "mini-todo"
    assert (ws / "app/main.py").exists() and (ws / "static/index.html").exists() and (ws / "build_trace.json").exists()
    smoke = b.trace[4]["smoke"]["checks"]
    assert {c["path"] for c in smoke} == {"/", "/api/todos"} and all(c["ok"] for c in smoke)


def test_debugger_fixes_failure(tmp_path):
    llm = MockLLM([json.dumps(SPEC), BACKEND_BROKEN, FRONT, TESTS, BACKEND_OK])
    b = AppBuilder(llm, out_root=tmp_path, max_debug=2).build("todo app")
    agents = [e["agent"] for e in b.trace]
    assert b.passed and agents.count("verify") == 2 and "debugger" in agents
    assert "titel" in llm.prompts[4]  # debugger saw the failing code/output
    assert not b.trace[4]["passed"]


def test_gives_up_after_max_debug(tmp_path):
    llm = MockLLM([json.dumps(SPEC), BACKEND_BROKEN, FRONT, TESTS, BACKEND_BROKEN])
    b = AppBuilder(llm, out_root=tmp_path, max_debug=1).build("todo app")
    assert not b.passed and [e["agent"] for e in b.trace].count("verify") == 2
