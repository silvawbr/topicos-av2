# Atividade_2
Implementação de Framework "LLM-as-a-Judge" e Persistência em Banco de Dados Relacional

## Python Project Layout

This repository uses a reusable Python project baseline:

- `src/atividade_2/`: package source code.
- `tests/`: pytest test suite.
- `resources/`: stable input files and fixtures.
- `outputs/`: generated artifacts and runtime outputs.
- `docs/`: project documentation.

Domain and business logic should be added in focused modules under
`src/atividade_2/` only when requirements are defined.

## Setup

All Python commands must use the project virtual environment:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

If `.venv/bin/python` does not exist, create the virtual environment first with
the project-approved Python 3.11 setup command.

## Validation

```bash
.venv/bin/python -m pytest
.venv/bin/python -m atividade_2.cli --help
```
