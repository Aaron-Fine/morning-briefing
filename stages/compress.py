"""Stage: compress — Pre-compress YouTube analysis transcripts via LLM.

Inputs:  raw_sources (dict)
Outputs: compressed_transcripts (list)

LLM calls run in parallel with bounded concurrency. Returns the transcript list
with 'transcript' replaced by 'compressed_transcript'. Falls back to the first
~600 words of the raw transcript if the LLM call fails.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from morning_digest.llm import call_llm
from utils.prompts import load_prompt

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("compress_system.md")
_MAX_PARALLEL_COMPRESSIONS = 4


def _target_words(word_count: int) -> int:
    """Proportional compression: 15-20% of input, min 300, max 1200."""
    target = round(word_count * 0.175)  # midpoint of 15-20%
    return max(300, min(1200, target))


def _compress_one(video: dict, model_config: dict) -> dict:
    transcript = video.get("transcript", "")
    if not transcript:
        return video

    word_count = len(transcript.split())
    target = _target_words(word_count)
    user_content = (
        f"Channel: {video['channel']}\n"
        f"Video: {video['title']}\n"
        f"Original transcript: {word_count} words. Target summary: ~{target} words.\n\n"
        f"Transcript:\n\n{transcript}"
    )

    compressed = ""
    try:
        compressed = call_llm(
            _SYSTEM_PROMPT,
            user_content,
            model_config,
            max_retries=2,
            json_mode=False,
            stream=False,
        )
    except Exception as e:
        log.warning(f"  Compression failed for {video['title']}: {e}")

    if not compressed.strip():
        log.warning(f"  Using raw fallback for {video['title']}")
        words = transcript.split()[:target]
        compressed = " ".join(words)
    else:
        compressed_words = len(compressed.split())
        log.info(
            f"  Compressed {video['channel']}: {video['title']} "
            f"({word_count} → {compressed_words} words)"
        )

    result = {k: v for k, v in video.items() if k != "transcript"}
    result["compressed_transcript"] = compressed
    result["category"] = "youtube-analysis"
    return result


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    """Compress all analysis transcripts and return compressed_transcripts artifact."""
    raw_sources = context.get("raw_sources", {})
    transcripts = raw_sources.get("analysis_transcripts", [])

    if not transcripts:
        log.info("compress: no transcripts to compress")
        return {"compressed_transcripts": []}

    effective_config = model_config or config.get("llm", {}).get("compression", {
        "provider": "fireworks",
        "model": "accounts/fireworks/models/minimax-m2p7",
        "max_tokens": 2000,
        "temperature": 0.2,
    })

    log.info(f"Compressing {len(transcripts)} transcript(s) in parallel...")
    results = [None] * len(transcripts)

    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_COMPRESSIONS) as pool:
        future_to_idx = {
            pool.submit(_compress_one, video, effective_config): i
            for i, video in enumerate(transcripts)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                log.error(f"  compress[{idx}]: failed: {e}")
                results[idx] = transcripts[idx]

    return {"compressed_transcripts": results}
