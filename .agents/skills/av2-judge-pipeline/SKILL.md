---
name: av2-judge-pipeline
description: Use when implementing or reviewing the AV2 LLM-as-a-Judge execution pipeline. Do not use for generic Python setup, standalone SQL analysis, or rubric design without execution changes.
---

# AV2 Judge Pipeline

## 1. Purpose

Implement and validate the AV2 evaluation flow from candidate answers to structured judge outputs persisted in PostgreSQL.

## 2. When to use

Use this skill when the task involves:

- building judge prompts;
- executing judge models;
- parsing judge output;
- persisting judge evaluations;
- linking evaluations to candidate answers, rubrics, prompts, and execution metadata;
- adding or reviewing judge pipeline CLI commands.

## 3. When not to use

Do not use this skill for:

- initial Python project setup;
- pure database import validation;
- standalone SQL reporting;
- PostgreSQL backup/restore;
- generic code review;
- rubric authoring without execution work.

## 4. Required inputs

Identify:

- dataset: J1 or J2;
- question records;
- candidate answers from AV1;
- reference answer, answer key, or rubric;
- judge model identifier;
- prompt version;
- rubric version;
- expected output schema;
- database connection method;
- execution mode and parameters.

## 5. Required commands

Use project-specific commands when available.

Baseline command pattern:

```bash
.venv/bin/python -m atividade_2.cli --help
.venv/bin/python -m atividade_2.cli run-judge --help
.venv/bin/python -m pytest
```

Inspect changed files:

```bash
git diff --stat
git diff -- src tests
```

## 6. Workflow

### Step 1 — Read project context

Load `PRIMING.md`.

Confirm:

- dataset semantics;
- J1/J2 evaluation rules;
- judge output contract;
- chain-of-thought handling rule;
- database traceability expectations.

### Step 2 — Map the data flow

Document:

```text
question
  + candidate answer
  + reference/rubric
  + judge prompt version
  -> judge request
  -> raw judge response
  -> parsed structured output
  -> validated score/rationale
  -> database row
```

### Step 3 — Build prompts from explicit inputs

The judge prompt must include:

- original question;
- candidate answer;
- reference, answer key, or rubric;
- scoring scale;
- hallucination penalty instruction;
- verbosity neutrality instruction;
- machine-parseable output schema.

### Step 4 — Validate judge output

Require:

- valid JSON or explicitly parseable structure;
- integer score from 1 to 5;
- non-empty structured rationale;
- hallucination risk field;
- rubric alignment field;
- human review flag.

Reject or quarantine malformed outputs. Do not silently coerce invalid records.

### Step 5 — Persist traceable evaluation

Every persisted evaluation must link to:

- question;
- candidate answer;
- candidate model;
- judge model;
- prompt version;
- rubric version;
- score;
- rationale;
- timestamp;
- execution metadata.

### Step 6 — Test before broad execution

Add tests for:

- prompt builder;
- parser;
- invalid output handling;
- score range enforcement;
- persistence mapping;
- idempotency or duplicate behavior.

Run a small fixture before full dataset execution.

## 7. Output format

```md
## Context & Goal

## Data flow

## Inputs verified

## Implementation summary

## Judge output contract

## Persistence mapping

## Validation performed

## Risks and follow-ups
```

## 8. Validation checklist

- [ ] Judge prompt includes question, candidate answer, and reference/rubric.
- [ ] Prompt version is persisted.
- [ ] Rubric version is persisted.
- [ ] Judge model is persisted.
- [ ] Score is integer 1–5.
- [ ] Rationale is structured and non-empty.
- [ ] Hidden chain-of-thought is not required.
- [ ] Malformed outputs fail clearly or are quarantined.
- [ ] Evaluation row is traceable to original question and AV1 answer.
- [ ] Tests cover parser and validation.
- [ ] Small execution sample passes before full run.

## 9. Guardrails

- Do not evaluate answers without reference/rubric context.
- Do not compare candidate answers against each other as gold.
- Do not reward verbosity by itself.
- Do not persist hidden reasoning.
- Do not silently accept invalid JSON or invalid scores.
- Do not overwrite existing evaluations unless explicitly requested and versioned.
