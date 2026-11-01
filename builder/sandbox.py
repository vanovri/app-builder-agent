"""Sandboxed test runner: temp dir copy, timeout, minimal env, no network (unshare -rn) when available."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path


@lru_cache
def netns_available() -> bool:
    if os.getenv("SANDBOX_NO_NETNS") or not shutil.which("unshare"):
        return False
    try:
        return subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def safe_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if rel.startswith("/") or ".." in Path(rel).parts or root.resolve() not in p.parents:
        raise ValueError(f"unsafe path: {rel}")
    return p


def write_files(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = safe_path(root, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def run_pytest(files: dict[str, str], timeout: int = 60, python: str = sys.executable,
               no_network: bool = True) -> dict:
    with tempfile.TemporaryDirectory(prefix="sandbox-") as d:
        write_files(Path(d), files)
        cmd = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "--color=no"]
        isolated = no_network and netns_available()
        if isolated:
            cmd = ["unshare", "-rn"] + cmd
        env = {"PATH": "/usr/bin:/bin", "HOME": d, "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
        try:
            p = subprocess.run(cmd, cwd=d, env=env, capture_output=True, text=True, timeout=timeout)
            out, rc = (p.stdout + p.stderr)[-12000:], p.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = f"TIMEOUT after {timeout}s\n{(e.stdout or b'')[-4000:]!r}", -9
    lines = [l for l in out.strip().splitlines() if l.strip()]
    return {"passed": rc == 0, "returncode": rc, "output": out,
            "summary": lines[-1] if lines else "", "sandbox": "netns+tmpdir" if isolated else "tmpdir",
            "failures": re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.M)}
