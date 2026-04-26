---
name: llm-judge-rubric-design
description: Use when designing or reviewing LLM-as-a-Judge rubrics and scoring prompts for AV2. Do not use for database imports, backup/restore, or generic Python setup.
---

# LLM Judge Rubric Design

## 1. Purpose

Design explicit, auditable, domain-aware rubrics for judging candidate model answers in the legal AV2 experiment.

## 2. When to use

Use this skill when the task involves:

- creating judge rubrics;
- revising score definitions;
- designing J1 or J2 judge prompts;
- reducing LLM-as-a-Judge bias;
- adding hallucination penalties;
- documenting rubric methodology.

## 3. When not to use

Do not use this skill for:

- executing judge models;
- parsing judge outputs;
- importing database rows;
- SQL analysis;
- Python project setup.

## 4. Required inputs

Identify:

- dataset: J1 or J2;
- question type;
- official answer key or reference;
- item-specific guideline if available;
- expected scoring scale;
- legal domain or topic;
- judge output schema;
- examples of acceptable and unacceptable answers if available.

## 5. Required commands

This is mainly a design skill.

If rubrics are stored as files, inspect them:

```bash
find . -maxdepth 5 -type f \( -iname "*rubric*" -o -iname "*prompt*" -o -iname "*judge*" \) -print
git diff --stat
git diff -- prompts rubrics docs src tests
```

If tests exist:

```bash
.venv/bin/python -m pytest
```

## 6. Workflow

### Step 1 — Confirm evaluation target

For J2:

- evaluate option correctness;
- evaluate explanation coherence;
- preserve official answer key.

For J1:

- evaluate against item-specific guideline/rubric;
- do not compare candidate answers against each other as gold.

### Step 2 — Define score scale

Use explicit score anchors.

Example:

| Score | Meaning |
|---|---|
| 1 | Incorrect, unsupported, or hallucinated answer |
| 2 | Mostly incorrect with limited relevant content |
| 3 | Partially correct but incomplete or weakly justified |
| 4 | Mostly correct with minor omissions |
| 5 | Correct, well-grounded, and aligned with reference/rubric |

### Step 3 — Encode legal priorities

Prioritize:

1. legal conclusion correctness;
2. normative basis accuracy;
3. absence of fabricated law, articles, precedents, or doctrine;
4. reasoning quality;
5. alignment with expected answer;
6. concision and relevance.

### Step 4 — Reduce judge bias

Include instructions:

- do not reward verbosity by itself;
- ignore style polish when legally irrelevant;
- penalize fabricated authority;
- judge against the same reference for all candidate models;
- do not prefer the judge model's own wording or style.

### Step 5 — Define output schema

Require machine-parseable output.

Preferred:

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

### Step 6 — Version rubric and prompt

Every rubric or prompt change must produce a new version identifier.

Do not mutate prior versions without preserving auditability.

## 7. Output format

```md
## Context & Goal

## Dataset/task type

## Rubric design

## Score anchors

## Judge prompt instructions

## Output schema

## Bias controls

## Versioning notes

## Risks and follow-ups
```

## 8. Validation checklist

- [ ] Rubric is explicit and versioned.
- [ ] Score anchors are clear.
- [ ] J1 uses item-specific reference/guideline.
- [ ] J2 preserves official answer key.
- [ ] Hallucination penalty is explicit.
- [ ] Verbosity is not rewarded by itself.
- [ ] Output schema is machine-parseable.
- [ ] Human-review criteria are defined.
- [ ] Prompt/rubric version can be persisted.

## 9. Guardrails

- Do not treat a model answer as gold.
- Do not use hidden chain-of-thought as a required output.
- Do not rely on vague criteria like "good answer" without anchors.
- Do not change score semantics without versioning.
- Do not optimize the rubric only for high correlation.
- Do not hide ambiguous cases; flag them for review.
