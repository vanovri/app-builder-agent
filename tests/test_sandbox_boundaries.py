"""Sandbox path containment, LLM block parsing, retry loop, and CLI brief integration."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from builder import cli
from builder.llm import MockLLM, parse_files, parse_json
from builder.orchestrator import AppBuilder
from builder.sandbox import run_pytest, safe_path, write_files


@pytest.mark.parametrize("relative", ["../escape.py", "/absolute.py", "nested/../../escape.py"])
def test_rejects_escaping_generated_paths(tmp_path, relative):
    with pytest.raises(ValueError, match="unsafe path"):
        safe_path(tmp_path, relative)


def test_parse_json_handles_escaped_quotes_and_braces_inside_strings():
    raw = 'Here is spec:\n```json\n{"app_name": "Brace {App} \\"v1\\"", "slug": "brace-app"}\n```'
    parsed = parse_json(raw)
    assert parsed == {"app_name": 'Brace {App} "v1"', "slug": "brace-app"}


def test_file_blocks_strip_fences_and_roundtrip_to_workspace(tmp_path):
    text = (
        "=== FILE: app/main.py ===\n"
        "```python\n"
        "value = 42\n"
        "```\n"
        "=== END ===\n"
    )
    files = parse_files(text)
    write_files(tmp_path, files)
    assert (tmp_path / "app/main.py").read_text(encoding="utf-8") == "value = 42\n"


def test_runner_decodes_pytest_failure_and_cleans_temp_workspace():
    observed = []

    def execute(command, **kwargs):
        root = Path(kwargs["cwd"])
        observed.append(root)
        assert (root / "test_generated.py").read_text(encoding="utf-8") == "assert False\n"
        return subprocess.CompletedProcess(
            command, 1, "FAILED test_generated.py::test_x - mismatch\n1 failed\n", ""
        )

    with (
        patch("builder.sandbox.netns_available", return_value=False),
        patch("builder.sandbox.subprocess.run", side_effect=execute),
    ):
        result = run_pytest({"test_generated.py": "assert False\n"})
    assert not result["passed"]
    assert result["failures"] == ["test_generated.py::test_x"]
    assert result["sandbox"] == "tmpdir"
    assert not observed[0].exists()


def test_runner_timeout_is_an_explicit_failure():
    with (
        patch("builder.sandbox.netns_available", return_value=False),
        patch(
            "builder.sandbox.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pytest", 2, output=b"partial"),
        ),
    ):
        result = run_pytest({"test_generated.py": "assert True\n"}, timeout=2)
    assert result["returncode"] == -9
    assert not result["passed"]
    assert "TIMEOUT after 2s" in result["output"]


def test_files_retry_and_debugger_requirements_protection(tmp_path):
    spec = {"app_name": "Notes", "slug": "notes-app", "summary": "notes", "endpoints": []}
    llm = MockLLM(
        [
            json.dumps(spec),
            "sorry I forgot the file blocks",
            "=== FILE: app/main.py ===\nx = 1\n=== END ===",
            "=== FILE: static/index.html ===\n<html></html>\n=== END ===",
            "=== FILE: tests/test_api.py ===\ndef test_ok(): assert True\n=== END ===",
            "=== FILE: app/main.py ===\nx = 2\n=== END ===\n=== FILE: requirements.txt ===\nevil==1.0\n=== END ===",
        ]
    )
    pytest_outcomes = [
        {"passed": False, "output": "FAILED t", "failures": ["t"], "summary": "1 failed", "sandbox": "tmpdir"},
        {"passed": True, "output": "1 passed", "failures": [], "summary": "1 passed", "sandbox": "tmpdir"},
    ]
    smoke_outcomes = [
        {"passed": False, "checks": [{"path": "/", "status": 500, "ok": False}], "server_log": "err"},
        {"passed": True, "checks": [{"path": "/", "status": 200, "ok": True}], "server_log": "ok"},
    ]
    with (
        patch("builder.orchestrator.run_pytest", side_effect=pytest_outcomes),
        patch("builder.orchestrator.smoke_test", side_effect=smoke_outcomes),
    ):
        built = AppBuilder(llm, out_root=tmp_path, max_debug=1).build("notes")
    assert built.passed
    assert "evil==1.0" not in built.files["requirements.txt"]
    assert built.files["app/main.py"] == "x = 2\n"


def test_cli_brief_emits_structured_summary_offline(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("APP_WORKSPACE", str(tmp_path))
    spec = {
        "app_name": "Ping App",
        "slug": "ping-app",
        "summary": "health",
        "endpoints": [{"method": "GET", "path": "/api/ping"}],
    }
    mock_llm = MockLLM(
        [
            json.dumps(spec),
            "=== FILE: app/main.py ===\napp = None\n=== END ===",
            "=== FILE: static/index.html ===\n<html></html>\n=== END ===",
            "=== FILE: tests/test_api.py ===\ndef test_a(): pass\n=== END ===",
        ]
    )
    with (
        patch("builder.cli.make_llm", return_value=mock_llm),
        patch(
            "builder.orchestrator.run_pytest",
            return_value={"passed": True, "output": "ok", "failures": [], "summary": "1 passed", "sandbox": "tmpdir"},
        ),
        patch(
            "builder.orchestrator.smoke_test",
            return_value={"passed": True, "checks": [{"path": "/", "status": 200, "ok": True}], "server_log": ""},
        ),
    ):
        cli.main(["ping service", "--max-debug", "0", "--brief"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["app"] == "Ping App"
    assert payload["endpoints"] == ["GET /api/ping"]


def test_failed_rebuild_preserves_existing_passing_workspace(tmp_path):
    existing = tmp_path / "notes-app"
    existing.mkdir()
    (existing / "sentinel.txt").write_text("keep-me", encoding="utf-8")

    spec = {"app_name": "Notes", "slug": "notes-app", "summary": "notes", "endpoints": []}
    llm = MockLLM(
        [
            json.dumps(spec),
            "=== FILE: app/main.py ===\nx = 1\n=== END ===",
            "=== FILE: static/index.html ===\n<html></html>\n=== END ===",
            "=== FILE: tests/test_api.py ===\ndef test_fail(): assert False\n=== END ===",
        ]
    )
    with (
        patch(
            "builder.orchestrator.run_pytest",
            return_value={"passed": False, "output": "FAILED", "failures": ["t"], "summary": "1 failed", "sandbox": "tmpdir"},
        ),
        patch(
            "builder.orchestrator.smoke_test",
            return_value={"passed": False, "checks": [], "server_log": "err"},
        ),
    ):
        failed = AppBuilder(llm, out_root=tmp_path, max_debug=0).build("notes")

    assert not failed.passed
    assert (existing / "sentinel.txt").read_text(encoding="utf-8") == "keep-me"
    assert Path(failed.workspace) != existing
    assert Path(failed.workspace).name.startswith("notes-app-failed-")
    assert (Path(failed.workspace) / "build_trace.json").exists()
