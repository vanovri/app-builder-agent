import argparse
import json

from .llm import make_llm
from .orchestrator import AppBuilder


def _print(ev):
    a = ev["agent"]
    if a == "verify":
        print(f"[verify r{ev['round']}] {'PASS' if ev['passed'] else 'FAIL'} pytest: {ev['pytest_summary']} | smoke: "
              + ", ".join(f"{c['path']}={c['status']}" for c in ev['smoke']['checks']))
        if not ev["passed"]:
            print("   failures:", ev["failures"] or ev["pytest_output"][-600:])
    else:
        print(f"[{a}] " + (ev.get("output") or "") + (f" files={ev['files']}" if ev.get("files") else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="build-app")
    ap.add_argument("prompt")
    ap.add_argument("--max-debug", type=int, default=3)
    ap.add_argument("--provider", choices=["openai", "grok-cli"])
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args(argv)
    b = AppBuilder(make_llm(a.provider), max_debug=a.max_debug, on_event=None if a.brief else _print).build(a.prompt)
    if a.brief:
        print(json.dumps({"passed": b.passed, "workspace": b.workspace, "app": b.spec.get("app_name"),
                          "endpoints": [f"{e.get('method')} {e.get('path')}" for e in b.spec.get("endpoints", [])],
                          "trace": [{k: v for k, v in e.items() if k in ("agent", "round", "passed", "pytest_summary", "files", "output")}
                                    for e in b.trace],
                          "run": f"cd {b.workspace} && ~/projects/app-builder-agent/.venv/bin/uvicorn app.main:app --port 8000"}, indent=1))
    else:
        print(f"\nRun it: cd {b.workspace} && ~/projects/app-builder-agent/.venv/bin/uvicorn app.main:app --port 8000")


if __name__ == "__main__":
    main()
