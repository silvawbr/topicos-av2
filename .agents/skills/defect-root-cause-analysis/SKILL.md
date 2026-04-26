---
name: defect-root-cause-analysis
description: Use when diagnosing bugs, failing tests, failed pipelines, bad data, or unexpected runtime behavior. Do not use for routine code review or simple formatting tasks.
---

# Defect Root Cause Analysis

## 1. Purpose

Diagnose defects systematically using evidence, reproduction, data-flow tracing, and targeted validation.

## 2. When to use

Use this skill when the task involves:

- failing tests;
- failed CI/pipeline logs;
- runtime errors;
- data corruption;
- unexpected output;
- broken import/export;
- authentication or environment failures;
- "find the root cause" requests.

## 3. When not to use

Do not use this skill for:

- routine PR descriptions;
- generic setup tasks;
- non-defect feature implementation;
- broad architecture planning without a concrete failure.

## 4. Required inputs

Gather:

- exact error message;
- stack trace or pipeline log;
- command that failed;
- expected behavior;
- actual behavior;
- recent changes;
- relevant input data;
- environment details.

## 5. Required commands

Start with inspection:

```bash
git status --short
git diff --stat
```

For tests:

```bash
.venv/bin/python -m pytest path/to/test.py -q
.venv/bin/python -m pytest
```

For logs:

```bash
grep -R "ERROR\|FAILED\|Traceback" path/to/logs
```

Adjust commands to the project.

## 6. Workflow

### Step 1 — Reproduce

Run the narrowest command that reproduces the failure.

Do not fix before confirming the failure unless reproduction is impossible.

### Step 2 — Classify failure

Classify as:

- test expectation issue;
- implementation regression;
- data contract mismatch;
- environment/config issue;
- dependency/tooling issue;
- nondeterminism/flake;
- external service issue.

### Step 3 — Trace data flow

Map:

- input shape;
- transformation points;
- output shape;
- serialization/deserialization;
- contract boundaries;
- failure point.

### Step 4 — Trace code path

Identify:

- entry point;
- functions called;
- return values;
- side effects;
- error paths;
- state mutations.

### Step 5 — Prove root cause

Use evidence:

- failing test;
- minimal reproduction;
- specific data state;
- specific function/branch;
- stack trace line;
- contract violation.

### Step 6 — Fix minimally

Apply the narrowest change that fixes the proven root cause.

Do not refactor stable code unless necessary.

### Step 7 — Validate

Run:

1. failing test alone;
2. related tests;
3. broader suite if relevant.

## 7. Output format

```md
## Context & Goal

## Reproduction

## Failure classification

## Data flow

## Code path

## Root cause

## Fix

## Validation performed

## Risks and follow-ups
```

## 8. Validation checklist

- [ ] Failure was reproduced or reproduction limitation is documented.
- [ ] Root cause is supported by evidence.
- [ ] Fix is minimal.
- [ ] Original failing test passes.
- [ ] Related tests pass.
- [ ] No unrelated files were changed.
- [ ] Remaining risk is documented.

## 9. Guardrails

- Do not guess root cause without evidence.
- Do not layer fixes on top of unproven assumptions.
- Do not skip reproduction when possible.
- Do not expand scope into unrelated refactors.
- Do not claim a fix is complete without validation.
- Do not hide flaky or nondeterministic behavior.
