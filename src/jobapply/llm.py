"""Thin Claude API wrapper for matching + tailoring."""
from __future__ import annotations

import json
from typing import Optional

from anthropic import Anthropic

from .config import settings

_client: Optional[Anthropic] = None


def client() -> Anthropic:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


def complete(prompt: str, *, system: str = "", max_tokens: int = 1500) -> str:
    """Single-turn text completion."""
    msg = client().messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        system=system or "You are a helpful assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")


def complete_json(prompt: str, *, system: str = "", max_tokens: int = 2000) -> dict:
    """Completion that must return a JSON object. Strips markdown fences if present."""
    text = complete(
        prompt + "\n\nRespond with ONLY a valid JSON object, no prose or markdown.",
        system=system,
        max_tokens=max_tokens,
    ).strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: extract the outermost {...}
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise
