"""Multi-provider LLM client for the Morning Digest pipeline.

Supports:
  - provider: "fireworks"  — OpenAI-compatible API via Fireworks AI
  - provider: "anthropic"  — Native Anthropic SDK (system prompt as top-level field)

Each stage passes a model_config dict:
  {
    "provider": "fireworks" | "anthropic",
    "model":    "<model id>",
    "max_tokens": int,
    "temperature": float,
  }
"""

import json
import logging
import os
import time

log = logging.getLogger(__name__)

# Lazy imports so the package only needs to be installed if that provider is used
_openai_client_cache: dict = {}
_anthropic_client_cache: dict = {}


def _fireworks_client():
    if "client" not in _openai_client_cache:
        import openai
        _openai_client_cache["client"] = openai.OpenAI(
            api_key=os.environ["FIREWORKS_API_KEY"],
            base_url="https://api.fireworks.ai/inference/v1",
        )
    return _openai_client_cache["client"]


def _anthropic_client():
    if "client" not in _anthropic_client_cache:
        import anthropic
        _anthropic_client_cache["client"] = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
    return _anthropic_client_cache["client"]


def call_llm(
    system_prompt: str,
    user_content: str,
    model_config: dict,
    max_retries: int = 2,
    json_mode: bool = True,
    stream: bool = True,
) -> dict | str:
    """Call an LLM and return parsed response.

    Args:
        system_prompt: The system/instruction prompt.
        user_content:  The user turn content.
        model_config:  Dict with provider, model, max_tokens, temperature.
        max_retries:   Number of retry attempts on transient errors.
        json_mode:     If True, request JSON output and parse it; otherwise return raw text.
        stream:        If True, use streaming (better for long responses).

    Returns:
        Parsed dict if json_mode=True, raw string otherwise.

    Raises:
        On non-retryable API errors or after all retries exhausted.
    """
    provider = model_config.get("provider", "fireworks")

    if provider == "anthropic":
        return _call_anthropic(system_prompt, user_content, model_config, max_retries, json_mode)
    else:
        return _call_fireworks(system_prompt, user_content, model_config, max_retries, json_mode, stream)


def _call_fireworks(
    system_prompt: str,
    user_content: str,
    model_config: dict,
    max_retries: int,
    json_mode: bool,
    stream: bool,
) -> dict | str:
    import openai

    client = _fireworks_client()
    model = model_config.get("model", "accounts/fireworks/models/kimi-k2p5")
    max_tokens = model_config.get("max_tokens", 12000)
    temperature = model_config.get("temperature", 0.4)

    create_kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    if json_mode:
        create_kwargs["response_format"] = {"type": "json_object"}

    raw = _retry_loop(
        lambda: _fireworks_call(client, create_kwargs, stream),
        max_retries,
        (openai.APIStatusError, openai.APIConnectionError),
        model,
    )
    return _parse_response(raw, json_mode, model)


def _fireworks_call(client, create_kwargs: dict, stream: bool) -> str:
    if stream:
        kwargs = {**create_kwargs, "stream": True}
        chunks = []
        with client.chat.completions.create(**kwargs) as resp:
            for chunk in resp:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    chunks.append(delta)
        return "".join(chunks).strip()
    else:
        kwargs = {**create_kwargs, "stream": False}
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()


def _call_anthropic(
    system_prompt: str,
    user_content: str,
    model_config: dict,
    max_retries: int,
    json_mode: bool,
) -> dict | str:
    import anthropic

    client = _anthropic_client()
    model = model_config.get("model", "claude-sonnet-4-6")
    max_tokens = model_config.get("max_tokens", 8192)
    temperature = model_config.get("temperature", 0.3)

    def _do_call() -> str:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return resp.content[0].text.strip()

    raw = _retry_loop(
        _do_call,
        max_retries,
        (anthropic.APIStatusError, anthropic.APIConnectionError),
        model,
    )
    return _parse_response(raw, json_mode, model)


def _retry_loop(fn, max_retries: int, retryable_errors: tuple, model: str) -> str:
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait = 2 ** attempt * 5  # 10s, 20s
                log.info(f"Retrying in {wait}s (attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait)
            log.info(f"Calling LLM ({model})...")
            return fn()
        except retryable_errors as e:
            log.warning(f"LLM error (attempt {attempt + 1}): {e}")
            if attempt == max_retries:
                raise
            # Don't retry on 4xx client errors (bad request, auth, etc.)
            status = getattr(e, "status_code", None)
            if status and 400 <= status < 500:
                raise
    raise RuntimeError("Retry loop exhausted without returning")  # unreachable


def _parse_response(raw: str, json_mode: bool, model: str) -> dict | str:
    if not json_mode:
        return raw

    # Strip markdown fences if model returned them despite json_mode
    text = raw
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse LLM response as JSON: {e}")
        log.error(f"Raw response (first 500 chars): {raw[:500]}")
        raise
