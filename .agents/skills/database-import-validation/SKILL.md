---
name: database-import-validation
description: Use when importing datasets, AV1 answers, prompts, rubrics, or judge outputs into PostgreSQL and validating referential integrity. Do not use for judge prompt design or pure Python project setup.
---

# Database Import Validation

## 1. Purpose

Ensure imported data is deterministic, duplicate-safe, referentially valid, and auditable in PostgreSQL.

## 2. When to use

Use this skill when the task involves:

- importing J1/J2 questions;
- importing AV1 candidate answers;
- importing model metadata;
- importing rubrics or prompt versions;
- validating foreign keys;
- checking duplicates;
- designing or testing idempotent import commands.

## 3. When not to use

Do not use this skill for:

- generating judge prompts;
- executing judge models;
- backup and restore validation;
- generic code review;
- standalone statistical analysis.

## 4. Required inputs

Identify:

- source file paths;
- source format: JSONL, CSV, Parquet, SQL, or JSON;
- target tables;
- primary keys or natural keys;
- expected row counts;
- duplicate policy;
- foreign key relationships;
- required metadata fields.

## 5. Required commands

Use project-specific commands when available.

Generic inspection:

```bash
find resources -maxdepth 3 -type f -print
find outputs -maxdepth 4 -type f -print
.venv/bin/python -m atividade_2.cli --help
.venv/bin/python -m pytest
```

Database validation examples:

```bash
psql "$DATABASE_URL" -c "\dt"
psql "$DATABASE_URL" -f path/to/validation.sql
```

## 6. Workflow

### Step 1 — Identify source contracts

Document for each source:

- file path;
- format;
- schema/fields;
- key fields;
- nullable fields;
- expected row count.

### Step 2 — Identify target contracts

Document for each target table:

- columns;
- primary key;
- unique keys;
- foreign keys;
- JSONB metadata fields;
- insert/update behavior.

### Step 3 — Normalize before insert

Normalize records into typed Python contracts before writing to PostgreSQL.

Validate:

- required fields;
- dataset labels;
- model identifiers;
- question identifiers;
- answer text presence;
- metadata shape.

### Step 4 — Preserve idempotency

Imports should be duplicate-safe.

Use one of:

- natural key upsert;
- deterministic IDs;
- unique constraints;
- explicit duplicate rejection with clear error.

Do not rely on row order alone.

### Step 5 — Validate referential integrity

Check:

```text
dataset -> question
question -> candidate answer
candidate answer -> judge evaluation
rubric -> judge evaluation
prompt -> judge evaluation
execution -> judge evaluation
```

### Step 6 — Add validation queries or scripts

Create deterministic checks for:

- row counts;
- duplicate natural keys;
- orphan records;
- missing answer text;
- missing model IDs;
- invalid dataset values;
- invalid score values when evaluations exist.

## 7. Output format

```md
## Context & Goal

## Sources inspected

## Target tables

## Import strategy

## Idempotency policy

## Validation queries/scripts

## Validation performed

## Risks and follow-ups
```

## 8. Validation checklist

- [ ] Source schemas are documented.
- [ ] Target tables are identified.
- [ ] Required fields are validated.
- [ ] Import is duplicate-safe.
- [ ] Foreign keys preserve question → answer → evaluation.
- [ ] Invalid records fail with clear errors.
- [ ] Validation query checks row counts.
- [ ] Validation query checks duplicates.
- [ ] Validation query checks orphan records.
- [ ] Tests or scripts cover malformed input.

## 9. Guardrails

- Do not silently ignore malformed records.
- Do not hardcode local absolute paths.
- Do not infer missing model/question IDs without evidence.
- Do not treat generated outputs as source fixtures.
- Do not disable foreign keys to make imports pass.
- Do not overwrite existing data without explicit versioning.
