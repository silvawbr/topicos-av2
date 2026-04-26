---
name: sql-analysis-and-spearman
description: Use when creating SQL reports, model rankings, disagreement analysis, or Spearman correlation for AV2. Do not use for judge execution or Python project bootstrap.
---

# SQL Analysis and Spearman Correlation

## 1. Purpose

Produce reproducible SQL and statistical analysis over persisted AV2 evaluation results.

## 2. When to use

Use this skill when the task involves:

- average scores by candidate model;
- average scores by judge model;
- score distributions;
- model rankings;
- disagreement cases;
- hallucination-risk cases;
- human-review queues;
- Spearman correlation between judge scores and human/reference scores.

## 3. When not to use

Do not use this skill for:

- importing raw data;
- designing rubrics;
- executing judge models;
- creating Python project structure;
- validating backup/restore.

## 4. Required inputs

Identify:

- database schema/table names;
- candidate model table/column;
- judge model table/column;
- dataset table/column;
- question IDs;
- score columns;
- human/reference score mapping;
- filters for J1/J2;
- expected output artifact path.

## 5. Required commands

Inspect schema:

```bash
psql "$DATABASE_URL" -c "\dt"
psql "$DATABASE_URL" -c "\d+ avaliacoes_juiz"
```

Run analysis SQL:

```bash
psql "$DATABASE_URL" -f sql/analysis.sql
```

Run Python correlation script if present:

```bash
.venv/bin/python -m atividade_2.cli compute-spearman --help
.venv/bin/python -m pytest
```

## 6. Workflow

### Step 1 — Confirm analysis question

Examples:

- Which candidate model has the best average judge score?
- Which judge model is stricter?
- Which dataset has more disagreement?
- Which records require human review?
- Does judge score correlate with human/reference score?

### Step 2 — Confirm scoring basis

For J2:

- map official correctness to ordinal reference score if needed;
- example: correct = 5, incorrect = 1.

For J1:

- use human/reference rubric score if available;
- do not fabricate reference scores.

### Step 3 — Create SQL queries

Include queries for:

- average score by candidate model;
- average score by judge model;
- score distribution by dataset;
- low-score cases;
- high-score cases with hallucination risk;
- disagreement cases;
- human-review cases;
- candidate ranking.

### Step 4 — Compute Spearman correlation

Use deterministic input extraction.

Document:

- variables compared;
- dataset filter;
- sample size;
- null handling;
- tie handling if implemented;
- interpretation limits.

### Step 5 — Persist artifacts

Store generated analysis under `outputs/`.

Recommended:

```text
outputs/analysis/
  model_rankings.csv
  disagreement_cases.csv
  spearman_summary.json
```

## 7. Output format

```md
## Context & Goal

## Tables/columns used

## SQL queries added or updated

## Spearman methodology

## Generated artifacts

## Validation performed

## Interpretation notes

## Risks and follow-ups
```

## 8. Validation checklist

- [ ] SQL joins preserve question → answer → evaluation traceability.
- [ ] Candidate model grouping is correct.
- [ ] Judge model grouping is correct.
- [ ] Dataset filters are explicit.
- [ ] Null scores are handled intentionally.
- [ ] Reference score mapping is documented.
- [ ] Spearman sample size is reported.
- [ ] Generated artifacts live under `outputs/`.
- [ ] Interpretation does not overclaim causality.

## 9. Guardrails

- Do not compute correlation against fabricated human scores.
- Do not mix J1 and J2 unless explicitly intended.
- Do not hide nulls or missing evaluations.
- Do not rank models without stating the scoring basis.
- Do not treat high correlation as proof of judge correctness.
- Do not overwrite analysis artifacts without versioning or clear naming.
