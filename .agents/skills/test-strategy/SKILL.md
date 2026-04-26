---
name: test-strategy
description: Use when designing, reviewing, or improving tests, fixtures, mocks, or validation strategy. Do not use for broad implementation unless the main task is testing.
---

# Test Strategy

## 1. Purpose

Design focused, deterministic tests that validate behavior, contracts, edge cases, and failure paths without over-mocking pure logic.

## 2. When to use

Use this skill when the task involves:

- adding tests;
- reviewing test quality;
- deciding what to stub/mock;
- creating fixtures;
- validating CLI behavior;
- testing data contracts;
- improving flaky tests.

## 3. When not to use

Do not use this skill for:

- implementing domain logic without test focus;
- SQL-only analysis;
- backup/restore operations;
- general code review unless test strategy is the main concern.

## 4. Required inputs

Identify:

- behavior under test;
- expected inputs/outputs;
- error paths;
- external I/O boundaries;
- deterministic logic boundaries;
- existing test style;
- test command.

## 5. Required commands

For Python:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pytest path/to/test.py -q
```

For repository inspection:

```bash
find tests -maxdepth 4 -type f -print
git diff --stat
git diff -- tests src
```

## 6. Workflow

### Step 1 — Identify test level

Choose the narrowest effective level:

- unit test for pure logic;
- contract test for schema/validation;
- CLI test for command behavior;
- integration test for database or external boundaries;
- end-to-end test only for critical workflows.

### Step 2 — Stub I/O, test logic

Stub:

- network;
- database;
- filesystem;
- environment;
- clock;
- randomness;
- model/provider calls.

Do not stub:

- pure transformations;
- deterministic parsers;
- mappers;
- validators;
- formatters.

Exception: stub logic only to force unreachable error paths.

### Step 3 — Define cases

Cover:

- happy path;
- edge cases;
- invalid input;
- error path;
- contract boundary;
- idempotency if applicable.

### Step 4 — Keep fixtures representative

Use real fixtures for deterministic logic.

Avoid snapshots when field-level assertions are clearer.

### Step 5 — Run scoped test first

Run the narrowest test file/case first, then broader suite when needed.

## 7. Output format

```md
## Context & Goal

## Behavior under test

## Test cases

## Stub/mock decisions

## Fixtures

## Validation commands

## Risks and follow-ups
```

## 8. Validation checklist

- [ ] Tests assert behavior, not implementation trivia.
- [ ] Pure logic uses real representative inputs.
- [ ] I/O and nondeterminism are stubbed.
- [ ] Error paths are covered.
- [ ] Contract boundaries are tested.
- [ ] Tests are deterministic.
- [ ] Scoped tests pass.
- [ ] Broader tests pass when relevant.

## 9. Guardrails

- Do not stub deterministic logic just to make tests easier.
- Do not hit real network or real external services in unit tests.
- Do not use snapshots to hide missing assertions.
- Do not make tests depend on local absolute paths.
- Do not add broad integration tests for simple pure functions.
- Do not weaken assertions to make tests pass.
