# Banco de Dados - Atividade 2

Este diretorio reune os artefatos de banco da atividade, alinhados ao fluxo oficial do repositorio.

O banco local usado pela infra padrao e o PostgreSQL do `docker compose`, com configuracao lida de `.env` na raiz do projeto. O nome padrao do banco e `app_dev`.

## Estrutura

- `database/ddl_banco/ddl_atividade_2.sql`: DDL base da atividade.
- `database/oab_bench/`: arquivos locais do dataset `OAB_Bench`.
- `database/respostas_alunos/`: CSVs com respostas da Atividade 1.
- `database/dumps/`: dumps gerados a partir do banco local.
- `database/scripts_etl/`: scripts de carga de datasets e respostas.

## Preparacao da base

Antes de gerar qualquer dump, use a infraestrutura oficial da raiz:

```bash
make db-up
make db-migrate-or-create
make db-restore-validate
```

Isso garante que o PostgreSQL local esteja de pe, com o backup principal restaurado e validado.

## Cinco comandos que os desenvolvedores vao usar

### 1. Gerar apenas o dump do DDL

```bash
make db-dump-structure
```

Gera:

```text
database/dumps/dump_estrutura_vazia.sql
```

### 2. Gerar o dump das perguntas

```bash
make db-dump-questions
```

Gera:

```text
database/dumps/dump_perguntas.sql
```

### 3. Gerar o dump das respostas

```bash
make db-dump-responses
```

Gera:

```text
database/dumps/dump_respostas.sql
```

### 4. Copiar a base atual para o backup principal da raiz

```bash
make db-dump-root-backup
```

Atualiza:

```text
backup_atividade_2.sql
```

Esse arquivo da raiz e a base canonica usada por `make db-migrate-or-create`.

### 5. Gerar tudo de uma vez

```bash
make db-dump-all
```

Esse comando gera:

- `database/dumps/dump_estrutura_vazia.sql`
- `database/dumps/dump_perguntas.sql`
- `database/dumps/dump_respostas.sql`
- `backup_atividade_2.sql`

## Restore esperado

Os dumps fracionados devem ser usados nesta ordem:

1. `dump_estrutura_vazia.sql`
2. `dump_perguntas.sql`
3. `dump_respostas.sql`

Os dumps de perguntas e respostas sao `data-only`, entao assumem que a estrutura ja existe no banco de destino.

## Fluxo para incorporar respostas de um novo aluno

Exemplo: o aluno `x` gerou seus arquivos e colocou no diretorio:

```text
database/respostas_alunos/respostas_objetivas_aluno_x.csv
database/respostas_alunos/respostas_discursivas_aluno_x.csv
```

### Passo a passo

1. Suba o banco e restaure a base atual do projeto:

```bash
make db-up
make db-migrate-or-create
make db-restore-validate
```

2. Confirme que os arquivos do novo aluno estao em `database/respostas_alunos/`.

O importador descobre automaticamente todos os arquivos com estes padroes:

- `respostas_objetivas_*.csv`
- `respostas_discursivas_*.csv`

3. Reimporte as respostas para todos os modelos presentes nesses CSVs:

```bash
.venv/bin/python database/scripts_etl/importar_respostas_atividade_1.py --replace
```

Use `--replace` para reconstruir as respostas dos modelos encontrados nos CSVs e evitar duplicidade.

4. Gere um novo dump de respostas:

```bash
make db-dump-responses
```

5. Promova a base atual para o backup principal da raiz:

```bash
make db-dump-root-backup
```

6. Se voce tambem quiser atualizar todos os artefatos fracionados:

```bash
make db-dump-all
```

## Observacoes importantes sobre o importador

- Para `OAB_Exames`, o importador aceita `id_pergunta` numerico.
- Para `OAB_Bench`, o importador aceita:
  - `id_pergunta` real do banco;
  - `question_id` textual salvo em `metadados`;
  - numero sequencial da questao dentro do dataset.
- `texto_resposta` vazio e preservado como string vazia quando o modelo nao respondeu nada.

## Scripts ETL

Os scripts em `database/scripts_etl/` usam a convencao atual do projeto:

- banco padrao `app_dev`;
- arquivos lidos dentro de `database/oab_bench/` e `database/respostas_alunos/`.

### OAB_Exames

```bash
HF_HOME=.hf_cache .venv/bin/python database/scripts_etl/import_oab_exames.py --limit 100 --truncate
```

Para importar todo o split:

```bash
HF_HOME=.hf_cache .venv/bin/python database/scripts_etl/import_oab_exames.py --limit 0 --truncate
```

### OAB_Bench

```bash
.venv/bin/python database/scripts_etl/import_oab_bench.py --replace
```

### Respostas da Atividade 1

```bash
.venv/bin/python database/scripts_etl/importar_respostas_atividade_1.py --replace
```
