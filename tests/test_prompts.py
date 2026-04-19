"""Tests for trusted prompt loading helpers."""

import pytest

import utils.prompts as prompts


def test_load_prompt_returns_prompt_text(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "sample.md").write_text("Prompt body", encoding="utf-8")
    monkeypatch.setattr(prompts, "_PROMPTS_DIR", prompt_dir)

    assert prompts.load_prompt("sample.md") == "Prompt body"


def test_load_prompt_substitutes_variables_strictly(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "sample.md").write_text("Hello $name", encoding="utf-8")
    monkeypatch.setattr(prompts, "_PROMPTS_DIR", prompt_dir)

    assert prompts.load_prompt("sample.md", {"name": "Aaron"}) == "Hello Aaron"


def test_load_prompt_raises_on_missing_variable(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "sample.md").write_text("Hello $name", encoding="utf-8")
    monkeypatch.setattr(prompts, "_PROMPTS_DIR", prompt_dir)

    with pytest.raises(KeyError):
        prompts.load_prompt("sample.md", {})


def test_load_prompt_rejects_path_traversal(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("Prompt body", encoding="utf-8")
    monkeypatch.setattr(prompts, "_PROMPTS_DIR", prompt_dir)

    with pytest.raises(ValueError, match="within prompts/"):
        prompts.load_prompt("../outside.md")


def test_load_prompt_rejects_absolute_paths(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    prompt_file = prompt_dir / "sample.md"
    prompt_file.write_text("Prompt body", encoding="utf-8")
    monkeypatch.setattr(prompts, "_PROMPTS_DIR", prompt_dir)

    with pytest.raises(ValueError, match="relative path"):
        prompts.load_prompt(str(prompt_file.resolve()))
