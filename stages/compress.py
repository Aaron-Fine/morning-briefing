"""Stage: compress — Pre-compress YouTube analysis transcripts via LLM.

Inputs:  raw_sources (dict)
Outputs: compressed_transcripts (list)

One LLM call per transcript, run serially. Returns the transcript list with
'transcript' replaced by 'compressed_transcript'. Falls back to the first ~600
words of the raw transcript if the LLM call fails.
"""

import logging

from llm import call_llm

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a transcript compressor. Given a YouTube video transcript, "
    "produce a dense summary that preserves:\n"
    "1. All concrete claims and factual assertions\n"
    "2. The speaker's analytical framework and conclusions\n"
    "3. Any named sources, data points, or specific examples\n"
    "4. The speaker's specific interpretive framing — how they characterize events "
    "matters as much as what events they cover\n\n"
    "Strip: filler, repetition, sponsor/ad reads, calls to action, tangents, "
    "conversational padding, verbal tics.\n\n"
    "Target: 400-800 words output regardless of input length. "
    "Output plain text, no JSON, no markdown headers."
)


def _compress_one(video: dict, model_config: dict) -> dict:
    transcript = video.get("transcript", "")
    if not transcript:
        return video

    word_count = len(transcript.split())
    user_content = (
        f"Channel: {video['channel']}\n"
        f"Video: {video['title']}\n"
        f"Transcript ({word_count} words, {len(transcript)} chars):\n\n"
        f"{transcript}"
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
        words = transcript.split()[:600]
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


def run(inputs: dict, config: dict, model_config: dict | None = None) -> dict:
    """Compress all analysis transcripts and return compressed_transcripts artifact."""
    raw_sources = inputs.get("raw_sources", {})
    transcripts = raw_sources.get("analysis_transcripts", [])

    if not transcripts:
        log.info("compress: no transcripts to compress")
        return {"compressed_transcripts": []}

    effective_config = model_config or config.get("llm", {}).get("compression", {
        "provider": "fireworks",
        "model": "accounts/fireworks/models/kimi-k2p5",
        "max_tokens": 2000,
        "temperature": 0.2,
    })

    log.info(f"Compressing {len(transcripts)} transcript(s) serially...")
    results = [_compress_one(video, effective_config) for video in transcripts]

    return {"compressed_transcripts": results}
