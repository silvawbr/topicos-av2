---
name: python-project-bootstrap
description: Use when creating, reviewing, or standardizing Python project infrastructure. Do not use for domain-specific implementation, business logic, or application feature design.
---

# Python Project Bootstrap

## 1. Purpose

Define a reusable Python infrastructure/tooling pattern that can be copied into a new project without copying domain-specific code.

Focus on packaging, layout, CLI execution, testing, contracts, and generated artifact organization.

## 2. When to use

Use this skill when the task involves:

- creating a new Python repository skeleton;
- reviewing Python project structure;
- migrating scripts into a package layout;
- adding or validating `pyproject.toml`;
- creating a module CLI with `argparse`;
- setting up `pytest`;
- separating source, inputs, and generated outputs;
- standardizing local command execution through `.venv/bin/python`.

## 3. When not to use

Do not use this skill for:

- implementing domain-specific business logic;
- designing legal/LLM evaluation rubrics;
- writing production database schema beyond tooling support;
- debugging a specific runtime failure;
- reviewing production code quality.

## 4. Required inputs

Identify:

- target package name;
- minimum Python version;
- expected CLI module name;
- runtime dependencies;
- dev dependencies;
- generated artifact directories;
- whether the project requires JSON, CSV, Parquet, database, or API contracts.

## 5. Required commands

Use `.venv/bin/python` for every Python command.

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -m atividade_2.cli --help
```

Do not use:

```bash
python
python3
pip
pip3
```

If `.venv` does not exist, stop and report the setup requirement. Do not fall back to system Python.

## 6. Workflow

### Step 1 — Inspect current repository

```bash
find . -maxdepth 4 -type f \( -name "pyproject.toml" -o -name "setup.py" -o -name "requirements.txt" -o -name "*.py" \) -print
find . -maxdepth 3 -type d \( -name "src" -o -name "tests" -o -name "resources" -o -name "outputs" \) -print
```

### Step 2 — Choose package name

Infer from existing source or repository name. If ambiguous, document the assumption and proceed with the safest normalized package name.

### Step 3 — Create or validate layout

Recommended skeleton:

```text
new_project/
  pyproject.toml
  README.md
  docs/
  resources/
  outputs/
  src/
    new_package/
      __init__.py
      cli.py
      contracts.py
      validators.py
      io_utils.py
  tests/
    __init__.py
    test_contracts.py
    test_cli.py
```

### Step 4 — Define `pyproject.toml`

Use `pyproject.toml` as the single packaging/config entry point.

Baseline:

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<project-name>"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pydantic",
]

[project.optional-dependencies]
dev = [
  "pytest",
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

### Step 5 — Keep CLI thin

Create `src/<package_name>/cli.py`.

Use `argparse`.
Expose `main()`.
Keep business logic in importable modules.

### Step 6 — Model contracts explicitly

Use typed modules for persisted or exchanged data shapes:

```text
src/<package_name>/contracts.py
src/<package_name>/validators.py
```

Use `pydantic` when runtime validation is required.

### Step 7 — Add focused tests

Recommended tests:

```text
tests/test_contracts.py
tests/test_cli.py
```

Test:

- package import;
- CLI help;
- contract validation;
- invalid inputs.

## 7. Output format

```md
## Context & Goal

## Current Python/tooling files discovered

## Proposed package name

## Files to create

## Files to modify

## Implementation summary

## Validation performed

## Risks and follow-ups
```

## 8. Validation checklist

- [ ] `pyproject.toml` is the single packaging/config entry point.
- [ ] Source code lives under `src/<package_name>/`.
- [ ] Tests live under `tests/`.
- [ ] CLI runs through `.venv/bin/python -m <package_name>.cli`.
- [ ] Editable install works.
- [ ] Pytest passes.
- [ ] CLI help works.
- [ ] Runtime contracts are typed and tested.
- [ ] Generated artifacts are under `outputs/`.
- [ ] Stable inputs are under `resources/`.
- [ ] No domain-specific implementation was copied.

## 9. Guardrails

- Do not copy domain logic from another project.
- Do not add dependencies without concrete use.
- Do not place generated artifacts under `src/`.
- Do not make the CLI responsible for business logic.
- Do not fall back to system Python.
- Do not create placeholder abstractions without near-term purpose.
