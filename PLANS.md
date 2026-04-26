# PLANS.md

## Purpose

This file defines how to plan larger, risky, architectural, or multi-step work.

Do not use this file as a replacement for task-specific skills. Use it to structure execution plans and risk control.

## When to create a plan

Create a plan when the task:

- changes database schema;
- changes import or persistence behavior;
- changes judge scoring semantics;
- touches multiple files or directories;
- affects reproducibility;
- has unclear blast radius;
- requires migration or backfill;
- involves external services or model execution;
- could invalidate previous experiment results.

For small localized edits, provide only a concise inline plan.

## Scope classification

Classify work before implementation:

| Scope | Definition |
|---|---|
| `[MINOR]` | Small localized change, usually 1 file or mechanical update |
| `[MODERATE]` | Multiple related files or behavior changes with limited blast radius |
| `[MAJOR]` | Schema, architecture, pipeline, or reproducibility-impacting change |

## Required planning sections

For non-trivial work, produce:

1. Problem statement
2. Assumptions
3. Constraints
4. Scope classification
5. Impacted files
6. Data flow
7. Risks
8. Implementation slices
9. Validation gates
10. Rollback or recovery strategy

## Data flow expectations

When changing data ingestion, persistence, evaluation, or analysis, map:

- input source;
- input shape;
- transformation logic;
- output shape;
- validation points;
- database write path;
- generated artifacts;
- failure modes.

## Implementation slices

Prefer small, functional slices.

Example sequence:

1. Add or update typed contract.
2. Add failing tests or validation fixtures.
3. Implement minimal logic.
4. Add CLI command or script.
5. Add deterministic validation.
6. Update README only if behavior or usage changed.

Each slice should be independently reviewable when possible.

## Approval checkpoints

Ask for explicit approval before implementation when:

- schema changes are destructive;
- existing outputs would be invalidated;
- task requires broad refactoring;
- task changes scoring semantics;
- task changes dataset interpretation;
- task introduces new external service behavior;
- narrower implementation options are not viable.

For low-risk localized changes, proceed with explicit assumptions.

## Validation gates

Use deterministic validation whenever possible.

Common gates:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m atividade_2.cli --help
```

For database changes, prefer project-specific commands such as:

```bash
psql "$DATABASE_URL" -f path/to/schema.sql
psql "$DATABASE_URL" -f path/to/validation.sql
```

For repository instruction changes:

```bash
find . -maxdepth 4 -type f \( -name "AGENTS.md" -o -name "PRIMING.md" -o -name "PLANS.md" -o -name "SKILL.md" \) -print
git diff --stat
git diff -- AGENTS.md PRIMING.md PLANS.md .agents
```

## Risk categories

Track risks using these categories:

- data loss;
- duplicate imports;
- broken foreign keys;
- invalid judge output;
- non-reproducible execution;
- hidden prompt changes;
- scoring drift;
- model/provider nondeterminism;
- slow or flaky tests;
- overfitted rubric;
- context pollution.

## Plan output format

Use this format:

```md
## Context & Goal

## Assumptions

## Constraints

## Scope

## Impacted files

## Proposed implementation slices

## Validation plan

## Risks

## Open questions
```

## Execution summary format

After implementation, respond with:

```md
## Summary

## Files created

## Files modified

## Validation performed

## Remaining risks or follow-ups

## Suggested next command
```
