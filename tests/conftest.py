import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _with_windows_runtime_env(env):
    """Preserve Windows Winsock/CRT roots when production code passes a POSIX-minimal env."""
    if sys.platform != "win32" or not isinstance(env, dict):
        return env
    upper = {k.upper() for k in env}
    if "SYSTEMROOT" in upper:
        return env
    patched = dict(env)
    for key in ("SYSTEMROOT", "WINDIR", "COMSPEC"):
        if os.environ.get(key):
            patched[key] = os.environ[key]
    sandbox_tmp = patched.get("HOME")
    if sandbox_tmp:
        patched.setdefault("TEMP", sandbox_tmp)
        patched.setdefault("TMP", sandbox_tmp)
    return patched


@pytest.fixture(autouse=True)
def _isolate_env_and_windows_subprocess(monkeypatch):
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_PROVIDER", "MODEL", "GROK_BIN"):
        monkeypatch.delenv(key, raising=False)
    if sys.platform == "win32":
        real_run = subprocess.run
        real_popen = subprocess.Popen

        def _run(*args, **kwargs):
            if "env" in kwargs:
                kwargs["env"] = _with_windows_runtime_env(kwargs["env"])
            return real_run(*args, **kwargs)

        def _popen(*args, **kwargs):
            if "env" in kwargs:
                kwargs["env"] = _with_windows_runtime_env(kwargs["env"])
            return real_popen(*args, **kwargs)

        monkeypatch.setattr(subprocess, "run", _run)
        monkeypatch.setattr(subprocess, "Popen", _popen)
