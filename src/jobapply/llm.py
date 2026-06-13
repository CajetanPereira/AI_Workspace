"""LLM wrapper with pluggable providers (Gemini / Anthropic).

Exposes two functions used across the app:
  - complete(prompt, system, max_tokens) -> str
  - complete_json(prompt, system, max_tokens) -> dict

Provider is chosen by settings.llm_provider ("gemini" or "anthropic").
"""
from __future__ import annotations

import json

from .config import settings

_anthropic_client = None
_gemini_ready = False


# ---------- Anthropic ----------

def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic

        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (set LLM_PROVIDER=gemini to use the free option).")
        _anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


def _anthropic_complete(prompt: str, system: str, max_tokens: int) -> str:
    msg = _anthropic().messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        system=system or "You are a helpful assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


# ---------- Gemini ----------

def _gemini_configure():
    global _gemini_ready
    if not _gemini_ready:
        import google.generativeai as genai

        key = settings.gemini_api_key
        if not key or "PASTE_" in key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey "
                "and put it in the .env file."
            )
        genai.configure(api_key=settings.gemini_api_key)
        _gemini_ready = True


def _gemini_complete(prompt: str, system: str, max_tokens: int, *, json_mode: bool = False) -> str:
    import google.generativeai as genai

    _gemini_configure()
    # Gemini 2.5 models are "thinking" models: reasoning tokens count against
    # max_output_tokens, so a tight budget truncates the actual answer. Give a
    # generous floor (free tier, so cost isn't a concern).
    gen_cfg = {"max_output_tokens": max(max_tokens, 8192), "temperature": 0.4}
    if json_mode:
        gen_cfg["response_mime_type"] = "application/json"
    model = genai.GenerativeModel(
        settings.gemini_model,
        system_instruction=system or None,
        generation_config=gen_cfg,
    )
    import time

    from google.api_core import exceptions as gexc

    delay = 5.0
    for attempt in range(5):
        try:
            resp = model.generate_content(prompt)
            return (resp.text or "").strip()
        except gexc.ResourceExhausted:
            # Free-tier rate limit (429). Back off and retry.
            if attempt == 4:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60)
    return ""


# ---------- Public API ----------

def complete(prompt: str, *, system: str = "", max_tokens: int = 1500) -> str:
    if settings.llm_provider == "anthropic":
        return _anthropic_complete(prompt, system, max_tokens)
    return _gemini_complete(prompt, system, max_tokens)


def complete_json(prompt: str, *, system: str = "", max_tokens: int = 2000) -> dict:
    """Completion that must return a JSON object."""
    if settings.llm_provider == "gemini":
        # Gemini can emit raw JSON directly via response_mime_type.
        text = _gemini_complete(prompt, system, max_tokens, json_mode=True)
    else:
        text = _anthropic_complete(
            prompt + "\n\nRespond with ONLY a valid JSON object, no prose or markdown.",
            system, max_tokens,
        ).strip()

    return _parse_json(text)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise
