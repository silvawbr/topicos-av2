"""Prompt Juizes persistence and UI service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from .config import load_settings
from .contracts import JudgePromptConfigRecord, JudgePromptTemplate, ModelSpec
from .db import connect
from .prompts import build_judge_prompt

DATASET_ALIASES = {
    "J1": "OAB_Bench",
    "J2": "OAB_Exames",
}


class JudgePromptConfigService:
    """Manage versioned judge prompt configuration records."""

    def __init__(
        self,
        *,
        settings_loader: Callable[[], Any] = load_settings,
        connect_func: Callable[[str], Any] = connect,
        repository_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self._settings_loader = settings_loader
        self._connect = connect_func
        self._repository_factory = repository_factory

    def options(self) -> dict[str, list[dict[str, str | None]]]:
        connection = self._connect(self._settings_loader().database_url)
        try:
            repository = self._make_repository(connection)
            repository.ensure_schema()
            return {"datasets": repository.list_prompt_datasets()}
        finally:
            connection.close()

    def get(self, *, dataset: str) -> dict[str, Any]:
        connection = self._connect(self._settings_loader().database_url)
        try:
            repository = self._make_repository(connection)
            repository.ensure_schema()
            record = repository.get_prompt_config(dataset=dataset)
            versions = repository.list_prompt_config_versions(dataset=dataset, limit=25)
            preview = self._build_preview(repository=repository, dataset=dataset, record=record)
        finally:
            connection.close()
        return {
            "record": asdict(record) if record is not None else None,
            "versions": versions,
            "preview": preview,
        }

    def save(
        self,
        *,
        dataset: str,
        prompt: str,
        persona: str,
        context: str,
        rubric: str,
        output: str,
        changed_by: str,
    ) -> dict[str, Any]:
        connection = self._connect(self._settings_loader().database_url)
        try:
            repository = self._make_repository(connection)
            repository.ensure_schema()
            saved = repository.create_prompt_config_version(
                dataset=dataset,
                prompt=prompt,
                persona=persona,
                context=context,
                rubric=rubric,
                output=output,
                changed_by=changed_by,
            )
            versions = repository.list_prompt_config_versions(dataset=dataset, limit=25)
            preview = self._build_preview(repository=repository, dataset=dataset, record=saved)
        finally:
            connection.close()
        return {
            "record": asdict(saved),
            "versions": versions,
            "preview": preview,
        }

    def _make_repository(self, connection: Any) -> Any:
        if self._repository_factory is not None:
            return self._repository_factory(connection)
        from .repositories import JudgeRepository

        return JudgeRepository(connection)

    def _build_preview(
        self,
        *,
        repository: Any,
        dataset: str,
        record: JudgePromptConfigRecord | None,
    ) -> dict[str, Any] | None:
        context = repository.get_prompt_preview_context(dataset=dataset)
        if context is None:
            return None
        rendered_prompt = None
        if record is not None:
            rendered_prompt = build_judge_prompt(
                context,
                judge_model=ModelSpec(requested="preview", provider_model="preview"),
                template=to_prompt_template(record),
            )
        return {
            "dataset": _dataset_label_for_preview(context.dataset_name),
            "question_id": context.question_id,
            "answer_id": context.answer_id,
            "candidate_model": context.candidate_model,
            "question_text": context.question_text,
            "reference_answer": context.reference_answer,
            "candidate_answer": context.candidate_answer,
            "rendered_prompt": rendered_prompt,
            "prompt_id": record.prompt_id if record is not None else None,
            "version": record.version if record is not None else None,
        }


def resolve_prompt_dataset_name(value: str) -> str:
    """Resolve UI dataset aliases into persisted dataset names."""
    normalized = value.strip()
    return DATASET_ALIASES.get(normalized.upper(), normalized)


def to_prompt_template(record: JudgePromptConfigRecord) -> JudgePromptTemplate:
    """Convert UI/storage record to prompt builder template."""
    return JudgePromptTemplate(
        prompt_id=record.prompt_id,
        dataset_name=record.dataset,
        version=record.version,
        created_by=record.created_by,
        prompt_text=record.prompt,
        persona=record.persona,
        context_text=record.context,
        rubric_text=record.rubric,
        output_text=record.output,
    )


def _dataset_label_for_preview(dataset_name: str) -> str:
    if dataset_name == "OAB_Bench":
        return "J1"
    if dataset_name == "OAB_Exames":
        return "J2"
    return dataset_name
