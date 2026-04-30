"""Parse remote judge output into validated AV2 evaluations."""

from __future__ import annotations

import json
import re
from typing import Any

from .contracts import ParsedJudgeEvaluation
from .validators import ValidationError, validate_parsed_evaluation


class JudgeParseError(ValueError):
    """Raised when a judge response cannot be parsed safely."""


def parse_judge_output(text: str) -> ParsedJudgeEvaluation:
    """Parse a JSON judge response and validate score/rationale."""
    payload = _load_json_object(text)
    score = _extract_score(payload)
    rationale = _extract_rationale(payload)
    evaluation = ParsedJudgeEvaluation(
        score=score,
        rationale=rationale,
        legal_accuracy=_optional_string(payload, "legal_accuracy"),
        hallucination_risk=_optional_string(payload, "hallucination_risk"),
        rubric_alignment=_optional_string(payload, "rubric_alignment"),
        requires_human_review=bool(payload.get("requires_human_review", False)),
        criteria={
            key: value
            for key, value in payload.items()
            if key
            not in {
                "score",
                "nota",
                "rationale",
                "justificativa",
                "explanation",
                "legal_accuracy",
                "hallucination_risk",
                "rubric_alignment",
                "requires_human_review",
            }
        },
    )
    try:
        return validate_parsed_evaluation(evaluation)
    except ValidationError as error:
        raise JudgeParseError(str(error)) from error


def _load_json_object(text: str) -> dict[str, Any]:
    candidate = _strip_code_fence(text.strip())
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = _load_first_embedded_json_object(candidate)
        if parsed is None:
            raise JudgeParseError(
                "Judge response does not contain a JSON object. "
                f"Preview: {_sanitized_preview(candidate)}"
            )

    if not isinstance(parsed, dict):
        raise JudgeParseError("Judge response JSON must be an object.")
    return parsed


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and re.fullmatch(r"```\s*", lines[-1]):
        return "\n".join(lines[1:-1]).strip()
    return text


def _load_first_embedded_json_object(text: str) -> dict[str, Any] | None:
    for json_object in _iter_balanced_json_objects(text):
        try:
            parsed = json.loads(json_object)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _iter_balanced_json_objects(text: str):
    search_start = 0
    while True:
        start = text.find("{", search_start)
        if start == -1:
            return
        end = _balanced_object_end(text, start)
        if end is not None:
            yield text[start : end + 1]
            search_start = end + 1
        else:
            search_start = start + 1


def _balanced_object_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _sanitized_preview(text: str, *, limit: int = 160) -> str:
    preview = re.sub(r"\s+", " ", text).strip()
    return preview[:limit] if preview else "<empty>"


def _extract_score(payload: dict[str, Any]) -> int:
    raw_score = payload.get("score", payload.get("nota"))
    if isinstance(raw_score, bool):
        raise JudgeParseError("Judge score must be an integer between 1 and 5.")
    if isinstance(raw_score, int):
        return raw_score
    if isinstance(raw_score, str) and raw_score.strip().isdigit():
        return int(raw_score.strip())
    raise JudgeParseError("Judge score must be an integer between 1 and 5.")


def _extract_rationale(payload: dict[str, Any]) -> str:
    raw_rationale = (
        payload.get("rationale")
        or payload.get("justificativa")
        or payload.get("explanation")
    )
    if not isinstance(raw_rationale, str):
        raise JudgeParseError("Judge rationale/justificativa must be a string.")
    return raw_rationale.strip()


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
