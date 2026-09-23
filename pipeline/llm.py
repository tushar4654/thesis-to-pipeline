"""One helper for JSON-schema chat calls to OpenRouter."""

from __future__ import annotations

import json
import os

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
FALLBACK_MODEL = "qwen/qwen3.8-27b:free"


def strict_schema(schema: dict) -> dict:
    """Inline $defs and forbid extra keys, which strict JSON schema mode expects."""
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            node = {k: walk(v) for k, v in node.items() if k != "title"}
            if node.get("type") == "object":
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def chat_json(system: str, user: str, schema: dict, name: str, max_tokens: int = 16000) -> tuple[dict, dict]:
    """Returns (parsed JSON, raw response data)."""
    model = os.getenv("LLM_MODEL") or DEFAULT_MODEL
    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={
            "models": [model, FALLBACK_MODEL],
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": name, "strict": True, "schema": strict_schema(schema)}},
            "provider": {"require_parameters": True},
        },
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter returned {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"OpenRouter error: {data['error']}")
    raw = data["choices"][0]["message"]["content"].strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw), data
