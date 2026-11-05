from __future__ import annotations

import json
import re
import time
from typing import Callable

import httpx

_RETRYABLE = {429, 500, 502, 503, 504}


class MistralLLM:
    def __init__(self, api_key: str, http: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=60.0)
        self.sleep = sleep
        self.url = "https://api.mistral.ai/v1/chat/completions"

    def complete_json(self, model: str, prompt: str) -> dict:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2000,
            "reasoning_effort": "low",
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(3):
            resp = self.http.post(self.url, json=body, headers=headers)
            if resp.status_code in _RETRYABLE and attempt < 2:
                self.sleep(2**attempt)
                continue
            resp.raise_for_status()
            break
        content = resp.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if p.get("type") == "text")
        return parse_json(content)


def parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
