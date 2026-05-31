import logging
from unittest.mock import MagicMock, patch
from morning_digest.llm import call_llm


@patch("morning_digest.llm._fireworks_client")
def test_call_llm_emits_progress(mock_client, caplog):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = '{"ok": 1}'
    resp.usage.prompt_tokens = 5
    resp.usage.completion_tokens = 2
    mock_client.return_value.chat.completions.create.return_value = resp
    with caplog.at_level(logging.INFO):
        call_llm("s", "u", {"provider": "fireworks", "model": "m", "max_tokens": 100,
                            "_obs": {"stage": "seams"}}, stream=False)
    msgs = " ".join(r.message for r in caplog.records)
    assert "seams" in msgs and "m" in msgs
