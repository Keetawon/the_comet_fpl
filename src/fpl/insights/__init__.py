"""Optional evidence-bound language rendering for public dashboard analytics."""

from fpl.insights.contracts import (
    MAX_INSIGHT_BODY_BYTES,
    PROMPT_VERSION,
    InsightErrorCode,
    InsightStatus,
    InsightSummaryRequest,
    InsightSummaryResponse,
    parse_insight_request_bytes,
)
from fpl.insights.providers import InsightGenerationError, InsightProvider, ZaiGlmProvider
from fpl.insights.service import InsightService, build_insight_service

__all__ = [
    "MAX_INSIGHT_BODY_BYTES",
    "PROMPT_VERSION",
    "InsightErrorCode",
    "InsightGenerationError",
    "InsightProvider",
    "InsightService",
    "InsightStatus",
    "InsightSummaryRequest",
    "InsightSummaryResponse",
    "ZaiGlmProvider",
    "build_insight_service",
    "parse_insight_request_bytes",
]
