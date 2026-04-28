import argparse
import csv
import os
from datetime import datetime, timezone
from getpass import getuser
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_batch
from tqdm import tqdm


DEFAULT_DIR = Path("database/respostas_alunos")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Importa respostas da Atividade 1 para modelos e respostas_atividade_1."
    )
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_DIR),
        help=(
            "Pasta com os CSVs de respostas. "
            "O script carrega automaticamente todos os arquivos "
            "respostas_objetivas_*.csv e respostas_discursivas_*.csv encontrados. "
            f"Padrao: {DEFAULT_DIR}"
        ),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Remove respostas anteriores dos mesmos modelos antes da importacao.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Quantidade de inserts por lote.",
    )
    return parser.parse_args()


def discover_csvs(directory):
    base = Path(directory)
    objetivas = sorted(base.glob("respostas_objetivas_*.csv"))
    discursivas = sorted(base.glob("respostas_discursivas_*.csv"))

    if not objetivas:
        raise FileNotFoundError(f"Nenhum respostas_objetivas_*.csv encontrado em '{base}'.")
    if not discursivas:
        raise FileNotFoundError(f"Nenhum respostas_discursivas_*.csv encontrado em '{base}'.")

    print(f"Objetivas   encontradas ({len(objetivas)}):  {[f.name for f in objetivas]}")
    print(f"Discursivas encontradas ({len(discursivas)}): {[f.name for f in discursivas]}")
    return objetivas, discursivas


def connect_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        database=os.getenv("PGDATABASE", "app_dev"),
        user=os.getenv("PGUSER", "postgres" if os.getenv("PGPASSWORD") else getuser()),
        password=os.getenv("PGPASSWORD", "postgres"),
        port=int(os.getenv("PGPORT", "5432")),
    )


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_csvs(paths):
    rows = []
    for path in paths:
        rows.extend(read_csv(path))
    return rows


def parse_timestamp(value):
    value = (value or "").strip()
    if not value:
        return None

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_float(value):
    value = (value or "").strip()
    if not value:
        return None
    return float(value)


def load_question_refs(cur, dataset_name):
    cur.execute(
        """
        SELECT
            p.id_pergunta,
            COALESCE(p.metadados->>'question_id', '')
        FROM perguntas p
        JOIN datasets d ON d.id_dataset = p.id_dataset
        WHERE d.nome_dataset = %s;
        """,
        (dataset_name,),
    )

    id_set = set()
    external_map = {}
    sequence_map = {}
    for index, (id_pergunta, question_id) in enumerate(cur.fetchall(), start=1):
        id_set.add(id_pergunta)
        sequence_map[index] = id_pergunta
        if question_id:
            external_map[question_id] = id_pergunta

    return id_set, external_map, sequence_map


def ensure_model(cur, nome_modelo, versao, parametro_precisao):
    cur.execute(
        """
        SELECT id_modelo
        FROM modelos
        WHERE nome_modelo = %s
          AND COALESCE(versao, '') = COALESCE(%s, '')
          AND COALESCE(parametro_precisao, '') = COALESCE(%s, '')
          AND tipo_modelo = 'candidato';
        """,
        (nome_modelo, versao, parametro_precisao),
    )
    result = cur.fetchone()

    if result:
        return result[0]

    cur.execute(
        """
        INSERT INTO modelos (nome_modelo, versao, parametro_precisao, tipo_modelo)
        VALUES (%s, %s, %s, 'candidato')
        RETURNING id_modelo;
        """,
        (nome_modelo, versao, parametro_precisao),
    )
    return cur.fetchone()[0]


def trunc(value, max_len=50):
    return value[:max_len] if value else None


def collect_model_keys(rows):
    return sorted(
        {
            (
                row["nome_modelo"].strip(),
                trunc(row.get("versao", "").strip() or None),
                trunc(row.get("parametro_precisao", "").strip() or None),
            )
            for row in rows
        }
    )


def resolve_question_ref(raw_value, dataset_name, valid_ids, external_ids, sequence_ids):
    value = (raw_value or "").strip()
    if not value:
        raise ValueError(f"Referencia de pergunta vazia no dataset {dataset_name}.")

    if value.isdigit():
        id_pergunta = int(value)
        if id_pergunta in valid_ids:
            return id_pergunta
        if id_pergunta in sequence_ids:
            return sequence_ids[id_pergunta]

    if value in external_ids:
        return external_ids[value]

    raise ValueError(
        f"Referencia de pergunta invalida para dataset {dataset_name}: {value}"
    )


def validate_rows(rows, dataset_name, valid_ids, external_ids, sequence_ids):
    seen = set()
    for row in rows:
        id_pergunta = resolve_question_ref(
            row.get("id_pergunta"),
            dataset_name,
            valid_ids,
            external_ids,
            sequence_ids,
        )

        key = (row["nome_modelo"], id_pergunta)
        if key in seen:
            raise ValueError(
                f"Resposta duplicada para modelo={row['nome_modelo']} e id_pergunta={id_pergunta}."
            )
        seen.add(key)


def build_response_rows(rows, dataset_name, valid_ids, external_ids, sequence_ids, model_ids):
    response_rows = []

    for row in rows:
        model_key = (
            row["nome_modelo"].strip(),
            trunc(row.get("versao", "").strip() or None),
            trunc(row.get("parametro_precisao", "").strip() or None),
        )
        id_pergunta = resolve_question_ref(
            row.get("id_pergunta"),
            dataset_name,
            valid_ids,
            external_ids,
            sequence_ids,
        )
        response_rows.append(
            (
                id_pergunta,
                model_ids[model_key],
                row.get("texto_resposta") or "",
                parse_float(row.get("tempo_inferencia_ms")),
                parse_timestamp(row.get("data_geracao")),
            )
        )

    print(
        f"{dataset_name}: {len(response_rows)} respostas preparadas "
        f"para {len({row[0] for row in response_rows})} perguntas."
    )
    return response_rows


def delete_previous_responses(cur, model_ids):
    ids = sorted(set(model_ids.values()))
    if not ids:
        return

    cur.execute(
        """
        DELETE FROM avaliacoes_juiz a
        USING respostas_atividade_1 r
        WHERE a.id_resposta_ativa1 = r.id_resposta
          AND r.id_modelo = ANY(%s);
        """,
        (ids,),
    )
    cur.execute(
        "DELETE FROM respostas_atividade_1 WHERE id_modelo = ANY(%s);",
        (ids,),
    )


def main():
    args = parse_args()

    objetivas_paths, discursivas_paths = discover_csvs(args.dir)
    objetivas = read_csvs(objetivas_paths)
    discursivas = read_csvs(discursivas_paths)

    conn = connect_db()
    try:
        with conn:
            with conn.cursor() as cur:
                exames_ids, exames_external, exames_sequence = load_question_refs(cur, "OAB_Exames")
                bench_ids, bench_external, bench_sequence = load_question_refs(cur, "OAB_Bench")

                validate_rows(objetivas, "OAB_Exames", exames_ids, exames_external, exames_sequence)
                validate_rows(discursivas, "OAB_Bench", bench_ids, bench_external, bench_sequence)

                model_keys = collect_model_keys(objetivas + discursivas)
                model_ids = {
                    model_key: ensure_model(cur, *model_key)
                    for model_key in model_keys
                }

                if args.replace:
                    delete_previous_responses(cur, model_ids)

                response_rows = []
                response_rows.extend(
                    build_response_rows(
                        objetivas,
                        "OAB_Exames",
                        exames_ids,
                        exames_external,
                        exames_sequence,
                        model_ids,
                    )
                )
                response_rows.extend(
                    build_response_rows(
                        discursivas,
                        "OAB_Bench",
                        bench_ids,
                        bench_external,
                        bench_sequence,
                        model_ids,
                    )
                )

                execute_batch(
                    cur,
                    """
                    INSERT INTO respostas_atividade_1
                        (id_pergunta, id_modelo, texto_resposta, tempo_inferencia_ms, data_geracao)
                    VALUES (%s, %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP));
                    """,
                    tqdm(response_rows, desc="Inserindo respostas"),
                    page_size=args.batch_size,
                )

        print(f"Insercao concluida. Total de respostas: {len(response_rows)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
