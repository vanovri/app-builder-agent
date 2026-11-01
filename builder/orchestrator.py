"""Planner -> Backend -> Frontend -> Tester -> verify (pytest + HTTP smoke) -> Debugger loop."""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import agents
from .llm import FORMAT_HELP, parse_files, parse_json
from .sandbox import run_pytest, write_files

ROOT = Path(__file__).resolve().parent.parent
REQS = "fastapi>=0.110\nuvicorn>=0.29\nhttpx>=0.27\npytest>=8.0\n"


@dataclass
class Build:
    prompt: str
    workspace: str = ""
    passed: bool = False
    spec: dict = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke_test(files: dict[str, str], spec: dict, python: str = sys.executable, timeout: float = 20) -> dict:
    """Start the app with uvicorn on a free port and hit / plus parameter-less GET endpoints."""
    checks, ok = [], True
    with tempfile.TemporaryDirectory(prefix="smoke-") as d:
        write_files(Path(d), files)
        port = _free_port()
        env = {"PATH": "/usr/bin:/bin", "HOME": d, "APP_DB": str(Path(d) / "smoke.db")}
        proc = subprocess.Popen([python, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=d, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            paths = ["/"] + [e["path"] for e in spec.get("endpoints", [])
                             if e.get("method", "").upper() == "GET" and "{" not in e.get("path", "")]
            deadline = time.time() + timeout
            for path in dict.fromkeys(paths):
                while True:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
                            body = r.read().decode(errors="ignore")
                            good = r.status == 200 and (path != "/" or "<html" in body.lower())
                            checks.append({"path": path, "status": r.status, "ok": good})
                            ok &= good
                            break
                    except urllib.error.HTTPError as e:
                        checks.append({"path": path, "status": e.code, "ok": False}); ok = False; break
                    except Exception as e:
                        if proc.poll() is not None or time.time() > deadline:
                            checks.append({"path": path, "status": None, "ok": False, "error": str(e)}); ok = False; break
                        time.sleep(0.3)
        finally:
            proc.terminate()
            try:
                log = proc.communicate(timeout=5)[0]
            except subprocess.TimeoutExpired:
                proc.kill(); log = proc.communicate()[0]
    return {"passed": ok, "checks": checks, "server_log": (log or "")[-3000:]}


class AppBuilder:
    def __init__(self, llm, out_root: Path | None = None, max_debug: int = 3, on_event=None):
        self.llm, self.max_debug, self.on_event = llm, max_debug, on_event
        self.out_root = Path(out_root or os.getenv("APP_WORKSPACE", ROOT / "workspace"))

    def _log(self, b: Build, agent: str, **kw):
        ev = {"agent": agent, "t": round(time.time(), 1), **kw}
        b.trace.append(ev)
        if self.on_event:
            self.on_event(ev)

    def _files(self, prompt: str) -> dict:
        f = parse_files(self.llm.complete(prompt))
        return f or parse_files(self.llm.complete(prompt + "\n\nNo file blocks found in your last reply. " + FORMAT_HELP))

    def build(self, prompt: str) -> Build:
        b = Build(prompt)
        c = agents.CONTRACT
        spec = parse_json(self.llm.complete(agents.PLANNER.format(prompt=prompt, contract=c)))
        slug = re.sub(r"[^a-z0-9-]+", "-", str(spec.get("slug") or spec.get("app_name", "app")).lower()).strip("-") or "app"
        b.spec, specs = spec, json.dumps(spec, indent=1)
        self._log(b, "planner", output=f"{spec.get('app_name')}: {len(spec.get('endpoints', []))} endpoints", spec=spec)

        be = self._files(agents.BACKEND.format(spec=specs, contract=c, fmt=FORMAT_HELP))
        be.setdefault("app/__init__.py", "")
        self._log(b, "backend", files=sorted(be), output=f"{len(be.get('app/main.py', ''))} chars main.py")
        fe = self._files(agents.FRONTEND.format(spec=specs, backend=be.get("app/main.py", ""), contract=c, fmt=FORMAT_HELP))
        self._log(b, "frontend", files=sorted(fe))
        te = self._files(agents.TESTER.format(spec=specs, backend=be.get("app/main.py", ""), contract=c, fmt=FORMAT_HELP))
        self._log(b, "tester", files=sorted(te))
        files = {**be, **fe, **te, "requirements.txt": REQS}

        for i in range(self.max_debug + 1):
            pt = run_pytest(files, timeout=120, no_network=True)
            sm = smoke_test(files, spec)
            ok = pt["passed"] and sm["passed"]
            self._log(b, "verify", round=i, passed=ok, pytest_summary=pt["summary"], failures=pt["failures"],
                      pytest_output=pt["output"][-5000:], smoke=sm, sandbox=pt["sandbox"])
            if ok or i == self.max_debug:
                b.passed = ok
                break
            fix = self._files(agents.DEBUGGER.format(
                spec=specs, files="\n".join(f"=== FILE: {k} ===\n{v}=== END ===" for k, v in files.items() if k != "requirements.txt"),
                pytest=pt["output"][-5000:], smoke=json.dumps({k: sm[k] for k in ("checks", "server_log")})[-3000:], fmt=FORMAT_HELP))
            fix.pop("requirements.txt", None)
            self._log(b, "debugger", round=i, files=sorted(fix))
            files = {**files, **fix}

        files["README.md"] = (f"# {spec.get('app_name', slug)}\n\n{spec.get('summary', '')}\n\nGenerated by app-builder-agent from: "
                              f"\"{prompt}\"\n\n```bash\npip install -r requirements.txt\nuvicorn app.main:app --reload  # http://127.0.0.1:8000\n"
                              f"pytest -q\n```\n\n## Endpoints\n" + "\n".join(f"- `{e.get('method')} {e.get('path')}` {e.get('description', '')}"
                                                                            for e in spec.get("endpoints", [])) + "\n")
        ws = self.out_root / slug
        if ws.exists():
            shutil.rmtree(ws)
        write_files(ws, files)
        (ws / "build_trace.json").write_text(json.dumps(b.trace, indent=1))
        b.workspace, b.files = str(ws), files
        self._log(b, "orchestrator", output=f"{'PASS' if b.passed else 'FAIL'} -> {ws}")
        return b
