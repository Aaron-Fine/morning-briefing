#!/usr/bin/env python3
"""Morning Digest v2 — Staged Pipeline Orchestrator.

Replaces the monolithic digest.py with a stage-based pipeline that:
  - Executes stages in dependency order defined in config.yaml
  - Persists each stage's output as JSON artifacts in output/artifacts/{YYYY-MM-DD}/
  - Supports re-running any single stage from the command line (--stage NAME)
  - Logs timing per stage
  - Retries failed stages with exponential backoff
  - Gracefully degrades when non-critical stages fail
  - Retains artifacts for 30 days

Usage:
  python pipeline.py                         # full run (schedule mode via entrypoint)
  python pipeline.py --dry-run               # full run, skip email send
   python pipeline.py --stage cross_domain    # re-run from cross_domain onwards
  python pipeline.py --sources-only          # collect sources and dump, skip LLM
  python pipeline.py --force-friday          # force Friday mode (weekend reads)
  python pipeline.py --lookback-hours 72    # override YouTube lookback window
"""

import argparse
import json
import logging
import logging.handlers
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

log = logging.getLogger("pipeline")

_ROOT = Path(__file__).parent
_OUTPUT_DIR = _ROOT / "output"
_ARTIFACTS_BASE = _OUTPUT_DIR / "artifacts"

# Stages that are allowed to fail without aborting the pipeline.
# A failed non-critical stage produces an empty output and logs a warning.
_NON_CRITICAL_STAGES = {
    "seams",
    "compress",
    "prepare_weather",  # weather enhances but isn't required
    "prepare_spiritual",  # spiritual section is optional
    "prepare_local",  # local news is optional
    "anomaly",  # post-assembly checks — non-blocking
    "briefing_packet",  # chat context artifact — non-blocking
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config() -> dict:
    with open(_ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_log_file() -> None:
    _OUTPUT_DIR.mkdir(exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(
        _OUTPUT_DIR / "digest.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(handler)


# ---------------------------------------------------------------------------
# Artifact persistence
# ---------------------------------------------------------------------------


def _artifact_dir(run_date: str) -> Path:
    d = _ARTIFACTS_BASE / run_date
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_artifact(artifact_dir: Path, name: str, data) -> None:
    """Save a stage output value as a JSON file."""
    path = artifact_dir / f"{name}.json"
    try:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        log.warning(f"Failed to save artifact {name}.json: {e}")


def _load_artifact(artifact_dir: Path, name: str):
    """Load a previously saved artifact. Returns None if not found."""
    path = artifact_dir / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Failed to load artifact {name}.json: {e}")
    return None


def _find_most_recent_artifact_dir(before_date: str | None = None) -> Path | None:
    """Find the most recent artifact directory (optionally before a given date)."""
    if not _ARTIFACTS_BASE.exists():
        return None
    dirs = sorted(
        [d for d in _ARTIFACTS_BASE.iterdir() if d.is_dir() and len(d.name) == 10],
        reverse=True,
    )
    for d in dirs:
        if before_date and d.name >= before_date:
            continue
        return d
    return None


def _prune_artifacts(keep_days: int = 30) -> None:
    """Delete artifact directories older than keep_days."""
    if not _ARTIFACTS_BASE.exists():
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    for d in _ARTIFACTS_BASE.iterdir():
        if d.is_dir() and len(d.name) == 10 and d.name < cutoff_str:
            import shutil

            shutil.rmtree(d, ignore_errors=True)
            log.debug(f"Pruned artifact dir: {d.name}")

    # Also prune old dated HTML files in output/
    cutoff_ts = cutoff.timestamp()
    for f in _OUTPUT_DIR.glob("????-??-??.html"):
        if f.stat().st_mtime < cutoff_ts:
            f.unlink(missing_ok=True)
            log.debug(f"Pruned old digest HTML: {f.name}")


# ---------------------------------------------------------------------------
# Stage registry — maps stage name → module
# ---------------------------------------------------------------------------


def _load_stage_module(name: str):
    """Dynamically import a stage module by name."""
    import importlib

    return importlib.import_module(f"stages.{name}")


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def _run_with_retry(fn, stage_name: str, max_retries: int = 2):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt < max_retries:
                wait = 2 ** (attempt + 1) * 5  # 10s, 20s
                log.warning(
                    f"Stage '{stage_name}' failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


def _get_stage_model_config(stage_cfg: dict) -> dict | None:
    """Extract the model config dict from a stage config entry."""
    return stage_cfg.get("model")


def run_pipeline(
    dry_run: bool = False,
    sources_only: bool = False,
    force_friday: bool = False,
    lookback_hours: int | None = None,
    stage_from: str | None = None,
) -> None:
    """Execute the full pipeline.

    Args:
        dry_run:       Skip the send stage; save HTML to output/ only.
        sources_only:  Run only the collect stage and dump sources.json.
        force_friday:  Force Friday mode (weekend reads).
        lookback_hours: Override YouTube lookback window.
        stage_from:    If set, load prior artifacts and re-run from this stage onwards.
    """
    _setup_log_file()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log.info("=== Morning Digest pipeline starting ===")

    config = load_config()

    # Apply CLI overrides
    if lookback_hours is not None:
        config.setdefault("youtube", {})["lookback_hours"] = lookback_hours
        log.info(f"  Override: lookback_hours={lookback_hours}")
    if force_friday:
        log.info("  Override: forcing Friday mode")

    run_date = datetime.now().strftime("%Y-%m-%d")
    artifact_dir = _artifact_dir(run_date)
    log.info(f"  Artifact dir: {artifact_dir}")

    # Load pipeline stage manifest from config
    stage_manifest = config.get("pipeline", {}).get("stages", [])
    if not stage_manifest:
        log.error("No pipeline.stages defined in config.yaml")
        sys.exit(1)

    # Determine which stages to skip (loading from artifacts) vs. run
    stage_names = [s["name"] for s in stage_manifest]
    if stage_from and stage_from not in stage_names:
        log.error(f"Unknown stage: '{stage_from}'. Valid stages: {stage_names}")
        sys.exit(1)

    skip_before = stage_from  # stages before this are loaded from artifacts

    # Determine artifact source directory for loading prior stage outputs
    # Try today's dir first, then most recent prior run
    def _find_load_dir() -> Path | None:
        if any(
            (_artifact_dir(run_date) / f"{s}.json").exists()
            for s in ["raw_sources", "synthesis_output"]
        ):
            return artifact_dir
        return _find_most_recent_artifact_dir(before_date=run_date)

    load_dir = _find_load_dir() if stage_from else artifact_dir

    # Accumulated context: union of all stage outputs
    context: dict = {}

    # Pipeline run metadata
    run_meta = {
        "run_date": run_date,
        "started_at": datetime.now().isoformat(),
        "stage_timings": {},
        "stage_failures": [],
        "options": {
            "dry_run": dry_run,
            "sources_only": sources_only,
            "force_friday": force_friday,
            "lookback_hours": lookback_hours,
            "stage_from": stage_from,
        },
    }

    _OUTPUT_DIR.mkdir(exist_ok=True)

    for stage_cfg in stage_manifest:
        stage_name = stage_cfg["name"]
        model_config = _get_stage_model_config(stage_cfg)

        # --sources-only: stop after collect
        if sources_only and stage_name != "collect":
            break

        # --dry-run: skip send
        if dry_run and stage_name == "send":
            log.info(f"  [dry-run] Skipping stage: {stage_name}")
            continue

        # If running from a specific stage, load prior outputs from artifacts
        if skip_before and stage_name != skip_before and stage_name in stage_names:
            idx_current = stage_names.index(stage_name)
            idx_from = stage_names.index(skip_before)
            if idx_current < idx_from:
                log.info(f"  Loading cached artifact for skipped stage: {stage_name}")
                if load_dir:
                    artifact_data = _load_artifact(
                        load_dir, _stage_artifact_key(stage_name)
                    )
                    if artifact_data is not None:
                        context[_stage_artifact_key(stage_name)] = artifact_data
                continue  # don't execute this stage

        # Before cross_domain, inject previous-day context for continuity
        if stage_name == "cross_domain":
            prev_dir = _find_most_recent_artifact_dir(before_date=run_date)
            if prev_dir:
                prev_xd = _load_artifact(prev_dir, "cross_domain_output")
                if prev_xd:
                    context["previous_cross_domain"] = prev_xd
                    log.info(f"  Loaded previous cross_domain from {prev_dir.name}")

        # Execute the stage
        log.info(f"--- Stage: {stage_name} ---")
        t_start = time.monotonic()

        try:
            module = _load_stage_module(stage_name)
            extra_kwargs: dict = {}
            if stage_name == "cross_domain":
                extra_kwargs["force_friday"] = force_friday

            outputs = _run_with_retry(
                lambda m=module, ec=extra_kwargs: m.run(
                    context, config, model_config, **ec
                ),
                stage_name,
                max_retries=2,
            )

        except Exception as e:
            elapsed = time.monotonic() - t_start
            run_meta["stage_timings"][stage_name] = round(elapsed, 2)

            if stage_name in _NON_CRITICAL_STAGES:
                log.warning(
                    f"Stage '{stage_name}' failed after retries (non-critical, continuing): {e}"
                )
                run_meta["stage_failures"].append(
                    {"stage": stage_name, "error": str(e)}
                )
                # Provide safe empty outputs so downstream stages don't crash
                outputs = _empty_stage_output(stage_name)
            else:
                log.error(f"Stage '{stage_name}' failed (critical): {e}")
                run_meta["stage_failures"].append(
                    {"stage": stage_name, "error": str(e), "fatal": True}
                )
                _save_artifact(artifact_dir, "run_meta", run_meta)
                sys.exit(1)

        elapsed = time.monotonic() - t_start
        run_meta["stage_timings"][stage_name] = round(elapsed, 2)
        log.info(f"  Stage '{stage_name}' completed in {elapsed:.1f}s")

        # Merge outputs into context
        context.update(outputs)

        # Persist each output artifact
        for key, value in outputs.items():
            if key not in ("html",):  # don't double-write html; handled below
                _save_artifact(artifact_dir, key, value)

        # Special handling for assemble outputs: write HTML files
        if stage_name == "assemble":
            html = context.get("html", "")
            if html:
                (artifact_dir / "digest.html").write_text(html, encoding="utf-8")
                (_OUTPUT_DIR / "last_digest.html").write_text(html, encoding="utf-8")
                if not dry_run:
                    (_OUTPUT_DIR / f"{run_date}.html").write_text(
                        html, encoding="utf-8"
                    )

        # --sources-only: dump sources.json after collect and exit
        if sources_only and stage_name == "collect":
            out = _OUTPUT_DIR / "sources.json"
            out.write_text(
                json.dumps(context.get("raw_sources", {}), indent=2, default=str),
                encoding="utf-8",
            )
            log.info(f"=== Sources written to {out} ===")
            return

    # Finalize run metadata
    run_meta["finished_at"] = datetime.now().isoformat()
    _save_artifact(artifact_dir, "run_meta", run_meta)

    # Prune old artifacts
    _prune_artifacts(keep_days=30)

    if dry_run:
        log.info(
            f"=== Dry run complete — digest saved to {_OUTPUT_DIR / 'last_digest.html'} ==="
        )
    else:
        send_result = context.get("send_result", {})
        if send_result.get("success"):
            log.info("=== Digest sent successfully ===")
        else:
            log.error("=== Pipeline completed but digest send failed ===")
            sys.exit(1)


def _stage_artifact_key(stage_name: str) -> str:
    """Map stage name to its primary output artifact key."""
    return {
        "collect": "raw_sources",
        "compress": "compressed_transcripts",
        # "synthesize" removed — was Phase 0 legacy, replaced by analyze_domain + cross_domain
        "analyze_domain": "domain_analysis",  # Phase 1+
        "prepare_calendar": "calendar",
        "prepare_weather": "weather",
        "prepare_spiritual": "spiritual",
        "prepare_local": "local_items",
        "seams": "seam_data",
        "cross_domain": "cross_domain_output",  # Phase 3+
        "assemble": "digest_json",
        "anomaly": "anomaly_report",
        "briefing_packet": "briefing_packet",
        "send": "send_result",
    }.get(stage_name, stage_name)


def _empty_stage_output(stage_name: str) -> dict:
    """Return safe empty outputs for a failed non-critical stage."""
    return {
        "compress": {"compressed_transcripts": []},
        "seams": {
            "seam_data": {
                "contested_narratives": [],
                "coverage_gaps": [],
                "key_assumptions": [],
                "seam_count": 0,
                "quiet_day": True,
            }
        },
        "prepare_weather": {"weather": {}},
        "prepare_spiritual": {"spiritual": {}},
        "prepare_local": {"local_items": []},
        "anomaly": {
            "anomaly_report": {"anomalies": [], "checks_run": 0, "anomaly_count": 0}
        },
        "briefing_packet": {"briefing_packet": {}},
    }.get(stage_name, {})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Morning Digest v2 pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run full pipeline but save HTML to output/ instead of sending email",
    )
    parser.add_argument(
        "--sources-only",
        action="store_true",
        help="Collect sources and dump to output/sources.json; skip LLM and email",
    )
    parser.add_argument(
        "--force-friday",
        action="store_true",
        help="Force Friday mode (weekend reads) regardless of actual day",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=None,
        help="Override YouTube lookback_hours (e.g. 120 to catch older videos)",
    )
    parser.add_argument(
        "--stage",
        metavar="NAME",
        default=None,
        help="Re-run from this stage onwards, loading prior stage artifacts from disk",
    )
    args = parser.parse_args()

    run_pipeline(
        dry_run=args.dry_run,
        sources_only=args.sources_only,
        force_friday=args.force_friday,
        lookback_hours=args.lookback_hours,
        stage_from=args.stage,
    )


if __name__ == "__main__":
    main()
