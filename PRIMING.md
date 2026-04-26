# PRIMING.md

## Purpose

This file contains project/product/domain context. It should be loaded only when the task depends on AV2, legal datasets, LLM-as-a-Judge evaluation, PostgreSQL persistence, or experiment reproducibility.

Do not place task-specific workflows here. Put repeatable workflows in `.agents/skills/`.

## Project mission

This repository implements AV2 for the graduate course "Tópicos Avançados em Engenharia de Software e Sistemas de Informação".

The goal is to build an auditable LLM-as-a-Judge evaluation framework backed by PostgreSQL.

The system must:

- ingest original legal datasets;
- import AV1 model answers;
- execute judge models using explicit rubrics;
- persist scores and structured rationales;
- support SQL-based statistical analysis;
- calculate and interpret Spearman correlation when applicable;
- produce reproducible scripts, prompts, README instructions, backup, and restore evidence.

## Domain

The project targets the legal domain for Equipe 4.

Datasets:

| Dataset | Source | Role |
|---|---|---|
| J1 | `maritaca-ai/oab-bench` | Open-ended OAB questions |
| J2 | `eduagarcia/oab_exams` | Multiple-choice OAB questions |

## Core experiment workflow

Preserve this pipeline:

```text
raw dataset
  -> normalized questions
  -> imported AV1 model answers
  -> judge prompt builder
  -> judge execution
  -> structured judge output
  -> PostgreSQL persistence
  -> SQL analysis
  -> Spearman correlation
  -> error analysis
  -> README/PDF/video evidence
```

The judge must not evaluate a candidate answer in isolation. The prompt must include:

- original question;
- candidate answer;
- reference, answer key, or rubric;
- judge instructions;
- expected output schema.

## Database role

The database is the audit source for the experiment, not temporary storage.

Minimum expected entities:

- datasets;
- models;
- questions;
- AV1 candidate answers;
- judge prompts;
- rubrics;
- judge evaluations;
- execution metadata.

Every judge evaluation must be traceable to:

- original question;
- candidate model;
- candidate answer;
- judge model;
- prompt version;
- rubric version;
- assigned score;
- structured rationale;
- execution timestamp.

## Recommended tables

The exact schema may evolve, but the model should preserve these responsibilities:

| Table | Responsibility |
|---|---|
| `datasets` | Register J1, J2, and domain metadata |
| `modelos` or `models` | Register candidate and judge models |
| `perguntas` or `questions` | Store prompt, answer key/reference, and metadata |
| `respostas_atividade_1` or `av1_answers` | Store AV1 candidate answers |
| `rubricas` or `rubrics` | Store rubric versions |
| `prompts_juiz` or `judge_prompts` | Version judge prompts |
| `avaliacoes_juiz` or `judge_evaluations` | Store individual judge scores and rationales |
| `execucoes` or `executions` | Track execution metadata |
| `decisoes_finais` or `final_decisions` | Optional aggregation or 2+1 judge decisions |

## Chain-of-thought handling

The assignment may use the term "Chain-of-Thought". In implementation, store concise auditable rationale, not hidden reasoning.

If a database column is named `chain_of_thought` for assignment compatibility, treat it as `judge_rationale`.

## Judge output contract

Judge output should be machine-parseable.

Preferred JSON shape:

```json
{
  "score": 1,
  "rationale": "...",
  "legal_accuracy": "...",
  "hallucination_risk": "...",
  "rubric_alignment": "...",
  "requires_human_review": false
}
```

Scores must be integers from 1 to 5.

## Legal rubric priorities

The judge should prioritize:

1. correctness of the legal conclusion;
2. accuracy of legal basis;
3. absence of fabricated laws, articles, precedents, or doctrines;
4. reasoning quality;
5. alignment with expected answer/rubric;
6. concision and relevance.

The judge must not reward verbosity by itself.

## J2 rule

For J2, preserve the official answer key.

Candidate answers should be evaluated by:

- whether the selected option is correct;
- whether the explanation is legally coherent;
- whether hallucinated legal basis appears.

For correlation analysis, the human reference can be mapped to an ordinal score when needed:

- `5` when the candidate selected the correct option;
- `1` when the candidate selected the wrong option.

## J1 rule

For J1, evaluate each answer against the item-specific guideline/rubric.

Do not compare one model answer against another as if it were gold. All candidate answers must be judged independently against the same reference.

## Recommended execution strategy

Prefer this implementation order:

1. J2 first, because multiple-choice has an objective answer key and is easier to validate.
2. J1 second, because open-ended questions require richer rubrics.
3. Add 2+1 judge review only after the single-judge pipeline is stable.
4. Persist every prompt, rubric, judge output, score, rationale, and execution metadata.
5. Treat error analysis as a core deliverable, not a stretch goal.

## Python infrastructure baseline

Python tooling should follow a `src/` package layout with `pyproject.toml` as the single packaging/config entry point.

Use:

```bash
make install
make test
```

Generated artifacts belong under `outputs/`.
Stable input files belong under `resources/`.
Source code belongs under `src/`.
Tests belong under `tests/`.

## Local PostgreSQL baseline

Local PostgreSQL must be reproducible through Make and Docker Compose.

Use PostgreSQL 18.3 by default because `backup_atividade_2.sql` was produced by PostgreSQL 18.3.

Core commands:

```bash
make db-up
make db-migrate-or-create
make db-restore-validate
make db-backup
make db-down
```

The root `backup_atividade_2.sql` is the initial restore artifact. Timestamped backups generated by `make db-backup` belong under `outputs/backup/` and are local generated artifacts.

`atividade2.ipynb` is not part of the reproducible setup path. Prefer deterministic Make/script workflows for professor and teammate validation.

## Reproducibility expectations

The final project should include:

- PostgreSQL DDL;
- data import scripts;
- judge prompt templates;
- SQL analysis queries;
- Spearman correlation calculation;
- `.sql` or `.dump` backup;
- restore instructions;
- validation query after restore;
- README explaining methodology, database, execution, rubric, and analysis.
