import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.mistral.ai/v1/chat/completions"
LOG = Path(__file__).parent / "out" / "model_runs.jsonl"


def _text(content):
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content or [] if p.get("type") == "text")


def ask(model, prompt, task, system=None, max_tokens=48000, retries=2, effort="low"):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = json.dumps({"model": model, "messages": msgs, "max_tokens": max_tokens, "stream": True, **({"reasoning_effort": effort} if effort and not model.startswith(("codestral", "anthropic")) else {}), "stream_options": {"include_usage": True}}).encode()
    for attempt in range(retries + 1):
        t0 = time.time()
        req = urllib.request.Request(API, data=body, headers={"Authorization": "Bearer " + os.environ["MISTRAL_API_KEY"], "Content-Type": "application/json"})
        try:
            parts, usage = [], {}
            with urllib.request.urlopen(req, timeout=900) as resp:
                for raw in resp:
                    line = raw.decode().strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[5:])
                    usage = chunk.get("usage") or usage
                    for ch in chunk.get("choices", []):
                        c = ch.get("delta", {}).get("content")
                        if isinstance(c, str):
                            parts.append(c)
                        elif isinstance(c, list):
                            parts.append(_text(c))
            text = "".join(parts)
            _log(model, task, time.time() - t0, True, usage)
            return text
        except urllib.error.HTTPError as e:
            _log(model, task, time.time() - t0, False, {"error": e.code})
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def extract_files(text):
    files = {}
    for m in re.finditer(r"^=== FILE: (\S+) ===\n```[a-zA-Z]*\n(.*?)\n```", text, re.S | re.M):
        files[m.group(1)] = m.group(2) + "\n"
    return files


def _log(model, task, secs, ok, usage):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"model": model, "task": task, "secs": round(secs, 2), "ok": ok, "usage": usage}) + "\n")
