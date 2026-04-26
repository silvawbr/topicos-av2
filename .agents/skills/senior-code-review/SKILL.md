---
name: senior-code-review
description: Use when reviewing code, diffs, or PR changes for correctness, maintainability, tests, performance, and risk. Do not use for initial implementation unless explicitly asked for review.
---

# Senior Code Review

## 1. Purpose

Perform a senior engineering review focused on correctness, maintainability, test coverage, risk, and minimal-change discipline.

## 2. When to use

Use this skill when the user asks for:

- code review;
- PR review;
- diff review;
- risk assessment;
- maintainability review;
- test gap review;
- "is this good?" analysis of code.

## 3. When not to use

Do not use this skill for:

- creating a new feature from scratch;
- debugging a failing pipeline;
- designing project instructions;
- writing broad architecture plans unless asked for review.

## 4. Required inputs

Collect or inspect:

- changed files;
- relevant tests;
- related contracts/types;
- expected behavior;
- command used to reproduce or validate;
- diff context.

Useful commands:

```bash
git status --short
git diff --stat
git diff
git diff --cached --stat
git diff --cached
```

## 5. Required commands

When in a repository:

```bash
git status --short
git diff --stat
git diff
```

For Python projects:

```bash
.venv/bin/python -m pytest
```

Only run tests when appropriate and available.

## 6. Workflow

### Step 1 — Understand scope

Determine whether the change is:

- bug fix;
- feature;
- refactor;
- test-only;
- docs/instructions;
- migration.

### Step 2 — Review correctness

Check:

- behavior matches requirement;
- edge cases are handled;
- data contracts are preserved;
- errors are explicit;
- no silent failure paths exist.

### Step 3 — Review tests

Check:

- happy path;
- edge cases;
- failure paths;
- contract tests;
- idempotency where applicable;
- no excessive mocking of deterministic logic.

### Step 4 — Review maintainability

Check:

- naming;
- function boundaries;
- duplication;
- readability;
- unnecessary abstractions;
- file size and cohesion.

### Step 5 — Review operational risk

Check:

- logging/observability;
- backward compatibility;
- rollout/rollback needs;
- data migration risk;
- performance implications.

### Step 6 — Provide actionable findings

Prioritize findings:

- blocking;
- should fix;
- optional.

Use diff-style patches when helpful.

## 7. Output format

```md
## Review summary

## Blocking issues

## Should fix

## Optional improvements

## Test gaps

## Suggested patches

## Validation recommendation

## Risk assessment
```

If no blocking issues exist, state that clearly.

## 8. Validation checklist

- [ ] Requirement is understood.
- [ ] Diff scope is inspected.
- [ ] Correctness issues are identified.
- [ ] Test gaps are identified.
- [ ] Backward compatibility is considered.
- [ ] Error handling is considered.
- [ ] Performance impact is considered where relevant.
- [ ] Suggested changes are minimal and actionable.

## 9. Guardrails

- Do not rewrite working code unnecessarily.
- Do not add dependencies unless strictly justified.
- Do not request broad refactors when a local fix is enough.
- Do not approve untested behavior changes without noting risk.
- Do not focus only on style while missing correctness.
- Do not remove code unless it is unrelated dead code or directly harmful.
