import argparse
import json
import os
from getpass import getuser
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, execute_batch
from tqdm import tqdm


DATASET_NAME = "OAB_Bench"
DATASET_DOMAIN = "Jurídico"
DATASET_SOURCE = "maritaca-ai/oab-bench"
DEFAULT_QUESTIONS_PATH = Path("database/oab_bench/question.jsonl")
DEFAULT_GUIDELINES_PATH = Path("database/oab_bench/guidelines.jsonl")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Importa o dataset local maritaca-ai/oab-bench para o PostgreSQL."
    )
    parser.add_argument(
        "--questions",
        default=str(DEFAULT_QUESTIONS_PATH),
        help="Caminho do arquivo question.jsonl.",
    )
    parser.add_argument(
        "--guidelines",
        default=str(DEFAULT_GUIDELINES_PATH),
        help="Caminho do arquivo guidelines.jsonl.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Remove registros anteriores do OAB_Bench antes da importação.",
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


def read_jsonl(path):
    records = []
    with open(path, encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON inválido em {path}, linha {line_number}: {exc}") from exc

    return records


def index_guidelines(guidelines):
    indexed = {}
    for guideline in guidelines:
        question_id = guideline["question_id"]
        if question_id in indexed:
            raise ValueError(f"Guideline duplicado para question_id={question_id}")
        indexed[question_id] = guideline
    return indexed


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


def replace_dataset_rows(cur, id_dataset):
    cur.execute(
        """
        DELETE FROM avaliacoes_juiz a
        USING respostas_atividade_1 r, perguntas p
        WHERE a.id_resposta_ativa1 = r.id_resposta
          AND r.id_pergunta = p.id_pergunta
          AND p.id_dataset = %s;
        """,
        (id_dataset,),
    )
    cur.execute(
        """
        DELETE FROM respostas_atividade_1 r
        USING perguntas p
        WHERE r.id_pergunta = p.id_pergunta
          AND p.id_dataset = %s;
        """,
        (id_dataset,),
    )
    cur.execute(
        "DELETE FROM perguntas WHERE id_dataset = %s;",
        (id_dataset,),
    )


def question_kind(question_id):
    if question_id.endswith("_peca_profissional"):
        return "peça profissional"
    return "questão discursiva"


def build_enunciado(question):
    statement = question["statement"].strip()
    turns = [turn.strip() for turn in question.get("turns", []) if turn.strip()]

    if not turns:
        return statement

    itens = "\n".join(f"{chr(ord('A') + index)}) {turn}" for index, turn in enumerate(turns))
    return f"{statement}\n\nItens:\n{itens}"


def build_resposta_ouro(guideline):
    choices = guideline.get("choices") or []
    if not choices:
        raise ValueError(f"Guideline sem choices para question_id={guideline['question_id']}")

    turns = choices[0].get("turns") or []
    if len(turns) == 1:
        return turns[0].strip()

    answers = []
    for index, turn in enumerate(turns):
        label = chr(ord("A") + index)
        answers.append(f"Resposta ao item {label}:\n{turn.strip()}")

    return "\n\n".join(answers)


def build_metadata(question, guideline):
    choice = (guideline.get("choices") or [{}])[0]

    metadata = {
        "origem": DATASET_SOURCE,
        "question_id": question["question_id"],
        "category": question.get("category"),
        "tipo_questao": question_kind(question["question_id"]),
        "turns": question.get("turns", []),
        "values": question.get("values", []),
        "pontuacao_total": sum(question.get("values", []) or []),
        "system": question.get("system"),
        "guideline_answer_id": guideline.get("answer_id"),
        "guideline_model_id": guideline.get("model_id"),
        "guideline_choice_index": choice.get("index"),
    }

    if guideline.get("tstamp") is not None:
        metadata["guideline_tstamp"] = guideline.get("tstamp")

    return metadata


def validate_records(questions, guidelines_by_id):
    question_ids = []
    for question in questions:
        question_id = question["question_id"]
        question_ids.append(question_id)
        if question_id not in guidelines_by_id:
            raise ValueError(f"Sem guideline correspondente para question_id={question_id}")

    duplicates = len(question_ids) - len(set(question_ids))
    if duplicates:
        raise ValueError(f"Existem {duplicates} question_id duplicados em question.jsonl")

    extra_guidelines = set(guidelines_by_id) - set(question_ids)
    if extra_guidelines:
        sample = ", ".join(sorted(extra_guidelines)[:5])
        raise ValueError(f"Existem guidelines sem pergunta correspondente: {sample}")


def main():
    args = parse_args()
    questions = read_jsonl(args.questions)
    guidelines = read_jsonl(args.guidelines)
    guidelines_by_id = index_guidelines(guidelines)
    validate_records(questions, guidelines_by_id)

    conn = connect_db()
    try:
        with conn:
            with conn.cursor() as cur:
                id_dataset = ensure_dataset(cur)

                if args.replace:
                    replace_dataset_rows(cur, id_dataset)

                rows = []
                for question in tqdm(questions, desc="Preparando questões"):
                    guideline = guidelines_by_id[question["question_id"]]
                    rows.append(
                        (
                            id_dataset,
                            build_enunciado(question),
                            build_resposta_ouro(guideline),
                            Json(build_metadata(question, guideline), dumps=lambda value: json.dumps(value, ensure_ascii=False)),
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
