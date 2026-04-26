# Atividade 2

Implementação de framework **LLM-as-a-Judge** com persistência em PostgreSQL para a disciplina de Tópicos Avançados em Engenharia de Software e Sistemas de Informação.

Este repositório está no estágio de fundação do projeto: ambiente Python, testes, PostgreSQL local, restore do backup inicial e geração de backup auditável. A pipeline completa de julgamento por LLM ainda não está implementada.

## Requisitos

- Python 3.11+
- Docker com Docker Compose v2
- `make`

## Estrutura

- `src/atividade_2/`: código Python importável.
- `tests/`: suíte pytest.
- `resources/`: entradas estáveis e fixtures.
- `outputs/`: artefatos gerados localmente.
- `outputs/backup/`: backups SQL gerados por `make db-backup`.
- `scripts/`: automações locais de banco.
- `backup_atividade_2.sql`: backup SQL inicial usado para restaurar o banco AV2.

## Setup Python

Instale o projeto em modo editável com dependências de desenvolvimento:

```bash
make install
```

Execute os testes:

```bash
make test
```

Os comandos Python usam explicitamente `.venv/bin/python`.

## Banco Local

O banco local usa PostgreSQL 18.3 via Docker Compose, para compatibilidade com o backup existente.

Crie o arquivo `.env` automaticamente e suba o PostgreSQL:

```bash
make db-up
```

O comando:

- copia `.env.example` para `.env` se necessário;
- baixa `postgres:18.3` se a imagem não existir localmente;
- sobe o container `topicos-av2-postgres`;
- valida conexão com `app_dev`;
- cria `app_test` se ainda não existir.

Conexão local padrão:

```text
postgresql://postgres:postgres@localhost:5432/app_dev
```

## Restore Inicial

Restaure o backup inicial somente quando o banco estiver vazio:

```bash
make db-migrate-or-create
```

Esse comando usa `backup_atividade_2.sql`. Se o banco já tiver tabelas públicas, o restore é ignorado para evitar sobrescrever dados locais.

Valide o restore:

```bash
make db-restore-validate
```

A validação confirma as tabelas centrais:

- `datasets`
- `modelos`
- `perguntas`
- `respostas_atividade_1`
- `avaliacoes_juiz`

## Backup

Gere um backup SQL auditável do banco local:

```bash
make db-backup
```

O arquivo gerado segue o formato:

```text
outputs/backup/atividade_2_YYYYmmdd_HHMMSS.sql
```

Backups gerados localmente são ignorados pelo Git. O backup inicial `backup_atividade_2.sql` permanece versionado.

## Comandos Make

```bash
make venv
make install
make test
make db-up
make db-migrate-or-create
make db-restore-validate
make db-backup
make db-status
make db-psql
make db-logs
make db-down
make db-reset
make clean
```

`make db-reset` remove o volume local do PostgreSQL. Use apenas quando quiser descartar o banco local e restaurar do zero.

## Fluxo Recomendado

Para validar o projeto do zero:

```bash
make install
make db-up
make db-migrate-or-create
make db-restore-validate
make db-backup
make test
make db-down
```

## Fora de Escopo Neste Estágio

- execução de modelos LLM;
- pipeline LLM-as-a-Judge;
- ORM;
- Alembic/migrations;
- importadores de datasets;
- cálculo de Spearman;
- automação via notebook.

`atividade2.ipynb` permanece como artefato separado e não é necessário para subir ou validar o ambiente local.
