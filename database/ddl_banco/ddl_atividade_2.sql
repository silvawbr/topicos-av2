-- ============================================================
-- Atividade 2 - Modelagem PostgreSQL
-- Domínio: Jurídico
-- Objetivo: armazenar datasets, respostas da Atividade 1
-- e avaliações LLM-as-a-Judge com rastreabilidade.
-- ============================================================

-- =========================
-- 1. Tabela de Modelos
-- =========================
CREATE TABLE modelos (
    id_modelo SERIAL PRIMARY KEY,
    nome_modelo VARCHAR(100) NOT NULL,
    versao VARCHAR(50),
    parametro_precisao VARCHAR(20),
    tipo_modelo VARCHAR(20) NOT NULL
        CHECK (tipo_modelo IN ('candidato', 'juiz', 'ambos'))
);

-- =========================
-- 2. Tabela de Datasets
-- =========================
CREATE TABLE datasets (
    id_dataset SERIAL PRIMARY KEY,
    nome_dataset VARCHAR(100) NOT NULL,
    dominio VARCHAR(50) NOT NULL
);

-- =========================
-- 3. Tabela de Perguntas
-- =========================
CREATE TABLE perguntas (
    id_pergunta SERIAL PRIMARY KEY,

    id_dataset INTEGER NOT NULL
        REFERENCES datasets(id_dataset),

    enunciado TEXT NOT NULL,
    resposta_ouro TEXT NOT NULL,
    metadados JSONB
);

-- =========================
-- 4. Respostas da Atividade 1
-- =========================
CREATE TABLE respostas_atividade_1 (
    id_resposta SERIAL PRIMARY KEY,

    id_pergunta INTEGER NOT NULL
        REFERENCES perguntas(id_pergunta),

    id_modelo INTEGER NOT NULL
        REFERENCES modelos(id_modelo),

    texto_resposta TEXT NOT NULL,

    tempo_inferencia_ms FLOAT
        CHECK (tempo_inferencia_ms >= 0),

    data_geracao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- 5. Avaliações do Juiz
-- =========================
CREATE TABLE avaliacoes_juiz (
    id_avaliacao SERIAL PRIMARY KEY,

    id_resposta_ativa1 INTEGER NOT NULL
        REFERENCES respostas_atividade_1(id_resposta),

    id_modelo_juiz INTEGER NOT NULL
        REFERENCES modelos(id_modelo),

    nota_atribuida INTEGER NOT NULL
        CHECK (nota_atribuida BETWEEN 1 AND 5),

    prompt_juiz TEXT NOT NULL,
    rubrica_utilizada TEXT NOT NULL,
    chain_of_thought TEXT NOT NULL,
    status_avaliacao VARCHAR(20) DEFAULT 'success',

    data_avaliacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- Indices
-- =========================

-- Perguntas por dataset.
CREATE INDEX idx_perguntas_dataset
ON perguntas(id_dataset);

-- Respostas por pergunta.
CREATE INDEX idx_respostas_pergunta
ON respostas_atividade_1(id_pergunta);

-- Respostas por modelo candidato.
CREATE INDEX idx_respostas_modelo
ON respostas_atividade_1(id_modelo);

-- Avaliações por resposta.
CREATE INDEX idx_avaliacoes_resposta
ON avaliacoes_juiz(id_resposta_ativa1);

-- Avaliações por modelo juiz.
CREATE INDEX idx_avaliacoes_juiz
ON avaliacoes_juiz(id_modelo_juiz);
