"""Reusable validation helpers for the AV2 judge pipeline."""

from __future__ import annotations

from .contracts import ParsedJudgeEvaluation


class ValidationError(ValueError):
    """Raised when deterministic validation fails."""


def validate_score(score: int) -> int:
    """Validate the AV2 judge score range."""
    if isinstance(score, bool) or not isinstance(score, int):
        raise ValidationError("Judge score must be an integer.")
    if score < 1 or score > 5:
        raise ValidationError("Judge score must be between 1 and 5.")
    return score


def validate_rationale(rationale: str) -> str:
    """Validate the audit-friendly judge rationale."""
    normalized = rationale.strip()
    if not normalized:
        raise ValidationError("Judge rationale cannot be empty.")
    return normalized


def validate_parsed_evaluation(evaluation: ParsedJudgeEvaluation) -> ParsedJudgeEvaluation:
    """Validate a parsed judge output before persistence."""
    validate_score(evaluation.score)
    validate_rationale(evaluation.rationale)
    return evaluation
