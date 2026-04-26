---
name: backup-restore-validation
description: Use when creating, documenting, or validating PostgreSQL backup and restore artifacts for AV2. Do not use for judge execution, rubric design, or Python project setup.
---

# Backup and Restore Validation

## 1. Purpose

Ensure the AV2 PostgreSQL experiment can be backed up, restored, and audited by another person.

## 2. When to use

Use this skill when the task involves:

- generating `.sql` or `.dump` backups;
- documenting restore commands;
- validating restored database content;
- preparing professor/auditor reproducibility artifacts;
- checking backup completeness.

## 3. When not to use

Do not use this skill for:

- schema design before implementation;
- data import logic;
- judge execution;
- SQL analysis unrelated to restore validation;
- generic repository setup.

## 4. Required inputs

Identify:

- database name;
- connection method;
- backup format: plain SQL or custom dump;
- output backup path;
- expected tables;
- expected row counts;
- validation queries;
- restore target database name.

## 5. Required commands

Plain SQL backup:

```bash
pg_dump "$DATABASE_URL" > outputs/backup/av2_backup.sql
```

Custom dump backup:

```bash
pg_dump -Fc "$DATABASE_URL" -f outputs/backup/av2_backup.dump
```

Restore plain SQL:

```bash
createdb av2_restore_test
psql av2_restore_test < outputs/backup/av2_backup.sql
```

Restore custom dump:

```bash
createdb av2_restore_test
pg_restore -d av2_restore_test outputs/backup/av2_backup.dump
```

Run validation:

```bash
psql av2_restore_test -f sql/restore_validation.sql
```

## 6. Workflow

### Step 1 — Confirm backup target

Choose one:

- plain SQL `.sql` for readability;
- custom `.dump` for robust restore workflows.

Document the choice.

### Step 2 — Generate backup

Store under:

```text
outputs/backup/
```

Do not store backup under `src/`.

### Step 3 — Create restore instructions

Document:

- required PostgreSQL version if known;
- database creation command;
- restore command;
- validation command;
- expected success criteria.

### Step 4 — Validate restored database

Validation should check:

- required tables exist;
- expected row counts;
- no orphan evaluations;
- prompts/rubrics exist;
- evaluations have valid scores;
- execution metadata exists.

### Step 5 — Document limitations

If restore was not executed locally, state clearly that it is documented but not tested.

## 7. Output format

```md
## Context & Goal

## Backup format

## Backup command

## Restore command

## Restore validation query

## Validation performed

## Files created or updated

## Risks and follow-ups
```

## 8. Validation checklist

- [ ] Backup artifact exists under `outputs/backup/`.
- [ ] Restore instructions are documented.
- [ ] Validation query exists.
- [ ] Required tables are present after restore.
- [ ] Row counts are reasonable.
- [ ] Foreign-key relationships are preserved.
- [ ] Scores are within valid range.
- [ ] Prompt and rubric versions are present.
- [ ] If restore was not tested, this is explicitly reported.

## 9. Guardrails

- Do not include credentials in backup files or docs.
- Do not overwrite backups without clear naming.
- Do not store backups under source directories.
- Do not claim restore was tested unless it was executed.
- Do not disable constraints to make restore pass.
- Do not omit validation query from restore docs.
