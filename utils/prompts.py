"""Trusted prompt loading helpers.

Prompt files live under ``prompts/`` and are treated as implementation assets,
not user content. Variable substitution is strict: missing keys raise.
"""

from __future__ import annotations

from pathlib import Path
from string import Template


_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _resolve_prompt_path(name: str) -> Path:
    """Resolve a prompt filename under the trusted prompts directory."""
    if not name or Path(name).is_absolute():
        raise ValueError("Prompt path must be a non-empty relative path")

    candidate = (_PROMPTS_DIR / name).resolve()
    try:
        candidate.relative_to(_PROMPTS_DIR)
    except ValueError as exc:
        raise ValueError("Prompt path must stay within prompts/") from exc

    if not candidate.is_file():
        raise FileNotFoundError(f"Prompt file not found: {name}")

    return candidate


def load_prompt(name: str, variables: dict[str, object] | None = None) -> str:
    """Load a prompt file and apply strict ``$var`` substitution."""
    path = _resolve_prompt_path(name)
    text = path.read_text(encoding="utf-8")
    if variables is None:
        return text
    return Template(text).substitute({k: str(v) for k, v in variables.items()})
