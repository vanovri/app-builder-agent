"""LLM providers (same pattern as agentic-rag): OpenAI-compatible API, headless Grok CLI, mock."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


def _default_grok() -> str:
    p = Path.home() / ".local/bin/grok"
    return os.getenv("GROK_BIN") or (str(p) if p.exists() else "grok")


class OpenAICompatLLM:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL", "https://api.x.ai/v1"),
                             api_key=os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("MODEL", "grok-4")

    def complete(self, prompt: str) -> str:
        r = self.client.chat.completions.create(model=self.model, temperature=0,
                                                messages=[{"role": "user", "content": prompt}])
        return r.choices[0].message.content or ""


class GrokCLILLM:
    """Headless logged-in Grok CLI (SuperGrok subscription, no API key)."""

    def __init__(self):
        self.bin, self.timeout = _default_grok(), int(os.getenv("GROK_TIMEOUT", "400"))

    def complete(self, prompt: str) -> str:
        prompt = ("You are a pure text-completion backend. Do NOT use any tools, do not read or write "
                  "files, do not run commands. Reply with text only, exactly in the requested format.\n\n" + prompt)
        with tempfile.TemporaryDirectory() as cwd:
            p = subprocess.run([self.bin, "--no-auto-update", "-p", prompt, "--output-format", "json"],
                               cwd=cwd, capture_output=True, text=True, timeout=self.timeout)
        if p.returncode != 0:
            raise RuntimeError(f"grok CLI failed ({p.returncode}): {p.stderr[-500:]}")
        try:
            return json.loads(p.stdout)["text"]
        except (json.JSONDecodeError, KeyError):
            return p.stdout


class MockLLM:
    def __init__(self, responder: Callable[[str], str] | list[str]):
        self.responder, self.prompts = responder, []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responder(prompt) if callable(self.responder) else self.responder.pop(0)


def make_llm(provider: str | None = None):
    provider = provider or os.getenv("LLM_PROVIDER") or ("openai" if os.getenv("OPENAI_API_KEY") else "grok-cli")
    return OpenAICompatLLM() if provider == "openai" else GrokCLILLM()


def parse_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        depth += ch == "{"
        depth -= ch == "}"
        if depth == 0:
            return json.loads(text[start:i + 1])
    raise ValueError(f"no JSON object in: {text[:200]}")


FILE_RE = re.compile(r"^=== FILE: (.+?) ===[ \t]*\n(.*?)^=== END ===", re.M | re.S)
FORMAT_HELP = ("Output every file as:\n=== FILE: relative/path.py ===\n<full file content>\n=== END ===\n"
               "No markdown fences, no commentary outside the blocks.")


def parse_files(text: str) -> dict[str, str]:
    out = {}
    for m in FILE_RE.finditer(text):
        body = m.group(2)
        lines = body.strip("\n").splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            body = "\n".join(lines) + "\n"
        out[m.group(1).strip()] = body
    return out
