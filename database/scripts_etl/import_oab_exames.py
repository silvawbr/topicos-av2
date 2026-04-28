import argparse
import json
import os
from getpass import getuser

import psycopg2
from datasets import load_dataset
from psycopg2.extras import Json, execute_batch
from tqdm import tqdm


DATASET_NAME = "OAB_Exames"
DATASET_DOMAIN = "Jurídico"
HF_DATASET = "eduagarcia/oab_exams"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Importa perguntas do dataset eduagarcia/oab_exams para o PostgreSQL."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2210,
        help="Quantidade de registros a importar. Use 0 para importar todo o split.",
    )
    parser.add_argument(
        "--split",
        default="train",
        help="Split do Hugging Face Dataset. Padrão: train.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Limpa perguntas e tabelas dependentes antes da importação.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Quantidade de inserts por lote.",
    )
    return parser.parse_args()


def connect_db():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        database=os.getenv("PGDATABASE", "app_dev"),
        user=os.getenv("PGUSER", "postgres" if os.getenv("PGPASSWORD") else getuser()),
        password=os.getenv("PGPASSWORD", "postgres"),
        port=int(os.getenv("PGPORT", "5432")),
    )


def ensure_dataset(cur):
    cur.execute(
        "SELECT id_dataset FROM datasets WHERE nome_dataset = %s;",
        (DATASET_NAME,),
    )
    result = cur.fetchone()

    if result:
        cur.execute(
            """
            UPDATE datasets
            SET dominio = %s
            WHERE id_dataset = %s;
            """,
            (DATASET_DOMAIN, result[0]),
        )
        return result[0]

    cur.execute(
        """
        INSERT INTO datasets (nome_dataset, dominio)
        VALUES (%s, %s)
        RETURNING id_dataset;
        """,
        (DATASET_NAME, DATASET_DOMAIN),
    )
    return cur.fetchone()[0]


def normalize_choices(row):
    choices = row.get("choices") or {}

    if isinstance(choices, dict):
        labels = choices.get("label") or []
        texts = choices.get("text") or []
        return {label: text for label, text in zip(labels, texts)}

    if isinstance(choices, list):
        normalized = {}
        for index, item in enumerate(choices):
            if isinstance(item, dict):
                label = item.get("label") or chr(ord("A") + index)
                text = item.get("text") or item.get("value") or ""
                normalized[label] = text
            else:
                normalized[chr(ord("A") + index)] = str(item)
        return normalized

    return {}


def build_metadata(row):
    metadata = {
        "tipo_questao": "questão objetiva",
        "category": row.get("question_type"),
        "origem": "eduagarcia/oab_exams",
    }

    optional_fields = [
        "id",
        "question_number",
        "exam_id",
        "exam_year",
        "nullified",
    ]

    for field in optional_fields:
        if row.get(field) is not None:
            metadata[field] = row.get(field)

    return metadata


def load_oab_dataset(split, limit):
    selected_split = split if limit == 0 else f"{split}[:{limit}]"
    return load_dataset(HF_DATASET, split=selected_split)


def main():
    args = parse_args()

    conn = connect_db()
    try:
        with conn:
            with conn.cursor() as cur:
                if args.truncate:
                    cur.execute("TRUNCATE perguntas RESTART IDENTITY CASCADE;")

                id_dataset = ensure_dataset(cur)

                dataset = load_oab_dataset(args.split, args.limit)
                rows = []

                for row in tqdm(dataset, desc="Preparando perguntas"):
                    alternativas = normalize_choices(row)
                    alternativas_texto = "\n".join(
                        f"{label}) {texto}" for label, texto in alternativas.items()
                    )
                    enunciado = f"{row['question']}\n\n{alternativas_texto}"
                    rows.append(
                        (
                            id_dataset,
                            enunciado,
                            row["answerKey"],
                            Json(build_metadata(row), dumps=lambda value: json.dumps(value, ensure_ascii=False)),
                        )
                    )

                execute_batch(
                    cur,
                    """
                    INSERT INTO perguntas (id_dataset, enunciado, resposta_ouro, metadados)
                    VALUES (%s, %s, %s, %s);
                    """,
                    rows,
                    page_size=args.batch_size,
                )

        print(f"Inserção concluída. Total de registros: {len(rows)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
