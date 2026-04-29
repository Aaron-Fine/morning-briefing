"""Article enrichment stage package.

The pipeline imports ``stages.enrich_articles.run`` as the stage entrypoint.
Selected private helpers remain re-exported for existing focused tests.
"""

from .canonical import _looks_like_bad_llm_summary
from .run import run
from .scheduling import _dedup_by_url

__all__ = ["_dedup_by_url", "_looks_like_bad_llm_summary", "run"]
