---
name: repository-instruction-maintenance
description: Use when creating, splitting, reviewing, or refactoring AGENTS.md, PRIMING.md, PLANS.md, or .agents/skills content. Do not use for application feature work.
---

# Repository Instruction Maintenance

## 1. Purpose

Maintain a clean context-engineering structure that minimizes context pollution and supports progressive disclosure.

## 2. When to use

Use this skill when the task involves:

- splitting overloaded `AGENTS.md`;
- creating or revising `PRIMING.md`;
- creating or revising `PLANS.md`;
- creating or revising skills;
- auditing duplicated/conflicting instructions;
- deciding whether guidance belongs in root, domain context, plan guidance, or skill.

## 3. When not to use

Do not use this skill for:

- application source-code changes;
- database schema implementation;
- judge pipeline implementation;
- general README editing unrelated to agent/context instructions.

## 4. Required inputs

Inspect:

- `AGENTS.md`;
- `PRIMING.md`;
- `PLANS.md`;
- `.agents/`;
- `.agents/skills/`;
- `.codex/`;
- `docs/`;
- `README.md`;
- package/test/build config files only when needed to understand workflows.

## 5. Required commands

```bash
find . -maxdepth 4 -type f \( -name "AGENTS.md" -o -name "PRIMING.md" -o -name "PLANS.md" -o -name "SKILL.md" -o -name "README.md" \) -print
find . -maxdepth 4 -type d \( -name ".agents" -o -name ".codex" -o -name "docs" \) -print
git status --short
```

After editing:

```bash
find . -maxdepth 4 -type f \( -name "AGENTS.md" -o -name "PRIMING.md" -o -name "PLANS.md" -o -name "SKILL.md" \) -print
git diff --stat
git diff -- AGENTS.md PRIMING.md PLANS.md .agents
```

## 6. Workflow

### Step 1 — Classify content

Classify each instruction block as:

- always-applicable global rule;
- project/domain context;
- planning workflow;
- task-specific repeatable workflow;
- deterministic validation script/command;
- outdated/duplicated/conflicting content.

### Step 2 — Route content

Use this routing:

| Content type | Target |
|---|---|
| Always-applicable engineering rules | `AGENTS.md` |
| Project/domain context | `PRIMING.md` |
| Planning/execution-plan guidance | `PLANS.md` |
| Repeatable task workflow | `.agents/skills/<skill-name>/SKILL.md` |
| Subdirectory-specific rule | nearest directory `AGENTS.md` |
| Deterministic check | script, command, or test |

### Step 3 — Avoid blind heading splits

Move content by intent, scope, applicability, and reuse pattern, not by heading alone.

### Step 4 — Keep root AGENTS concise

Root `AGENTS.md` should contain:

- global engineering principles;
- validation expectations;
- communication defaults;
- routing to skills/docs;
- warning for local skill auto-loading behavior if unvalidated.

It should not contain full task procedures.

### Step 5 — Ensure skill structure

Each `SKILL.md` must include YAML frontmatter:

```yaml
---
name: <skill-name>
description: <clear trigger description, including when to use and when not to use>
---
```

Each skill body must include:

1. Purpose
2. When to use
3. When not to use
4. Required inputs
5. Required commands, if applicable
6. Workflow
7. Output format
8. Validation checklist
9. Guardrails

### Step 6 — Preserve valuable guidance

Do not delete valuable guidance. Move, compress, or convert it into a deterministic command/script.

## 7. Output format

Before editing:

```md
## Migration plan

## Current files discovered

## Problems found

## Proposed target file tree

## Mapping table

## Risks

## Files to create

## Files to modify

## Files to leave unchanged
```

After editing:

```md
## Summary

## Files created

## Files modified

## Content migration summary

## Skills created and when each should be used

## Validation performed

## Remaining risks or follow-ups

## Suggested next command
```

## 8. Validation checklist

- [ ] Root `AGENTS.md` is concise.
- [ ] Task workflows live in skills.
- [ ] `PRIMING.md` contains domain/project context only.
- [ ] `PLANS.md` contains planning guidance only.
- [ ] Each skill has required frontmatter.
- [ ] Each skill has all required sections.
- [ ] Duplicated instructions are removed or consolidated.
- [ ] Unsupported Codex behavior is marked as requiring validation.
- [ ] No production code was changed.
- [ ] Diff is limited to instruction/context files.

## 9. Guardrails

- Do not blindly split by headings.
- Do not duplicate full skill content in `AGENTS.md`.
- Do not put domain context in root `AGENTS.md`.
- Do not put implementation procedures in `PRIMING.md`.
- Do not create directory-specific AGENTS files unless needed.
- Do not claim `.agents/skills` auto-loading works unless validated.
- Do not change application source code.
- Do not commit changes.
