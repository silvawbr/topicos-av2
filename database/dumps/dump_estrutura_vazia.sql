--
-- PostgreSQL database dump
--

\restrict onCd4pMPZlbX93pXplbbdGd4H1g7OpDcL4AuTBLNN2CGiQEakHmTfCpDcgh6epA

-- Dumped from database version 18.3 (Debian 18.3-1.pgdg13+1)
-- Dumped by pg_dump version 18.3 (Debian 18.3-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: avaliacoes_juiz; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.avaliacoes_juiz (
    id_avaliacao integer NOT NULL,
    id_resposta_ativa1 integer NOT NULL,
    id_modelo_juiz integer NOT NULL,
    nota_atribuida integer NOT NULL,
    chain_of_thought text NOT NULL,
    data_avaliacao timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    papel_juiz character varying(20),
    rodada_julgamento character varying(30),
    motivo_acionamento text,
    status_avaliacao character varying(20) DEFAULT 'success'::character varying,
    id_prompt_juiz integer NOT NULL,
    CONSTRAINT avaliacoes_juiz_nota_atribuida_check CHECK (((nota_atribuida >= 1) AND (nota_atribuida <= 5)))
);


ALTER TABLE public.avaliacoes_juiz OWNER TO postgres;

--
-- Name: avaliacoes_juiz_id_avaliacao_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.avaliacoes_juiz_id_avaliacao_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.avaliacoes_juiz_id_avaliacao_seq OWNER TO postgres;

--
-- Name: avaliacoes_juiz_id_avaliacao_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.avaliacoes_juiz_id_avaliacao_seq OWNED BY public.avaliacoes_juiz.id_avaliacao;


--
-- Name: datasets; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.datasets (
    id_dataset integer NOT NULL,
    nome_dataset character varying(100) NOT NULL,
    dominio character varying(50) NOT NULL
);


ALTER TABLE public.datasets OWNER TO postgres;

--
-- Name: datasets_id_dataset_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.datasets_id_dataset_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.datasets_id_dataset_seq OWNER TO postgres;

--
-- Name: datasets_id_dataset_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.datasets_id_dataset_seq OWNED BY public.datasets.id_dataset;


--
-- Name: modelos; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.modelos (
    id_modelo integer NOT NULL,
    nome_modelo character varying(100) NOT NULL,
    versao character varying(50),
    parametro_precisao character varying(20),
    tipo_modelo character varying(20) NOT NULL,
    CONSTRAINT modelos_tipo_modelo_check CHECK (((tipo_modelo)::text = ANY ((ARRAY['candidato'::character varying, 'juiz'::character varying, 'ambos'::character varying])::text[])))
);


ALTER TABLE public.modelos OWNER TO postgres;

--
-- Name: modelos_id_modelo_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.modelos_id_modelo_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.modelos_id_modelo_seq OWNER TO postgres;

--
-- Name: modelos_id_modelo_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.modelos_id_modelo_seq OWNED BY public.modelos.id_modelo;


--
-- Name: perguntas; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.perguntas (
    id_pergunta integer NOT NULL,
    id_dataset integer NOT NULL,
    enunciado text NOT NULL,
    resposta_ouro text NOT NULL,
    metadados jsonb
);


ALTER TABLE public.perguntas OWNER TO postgres;

--
-- Name: perguntas_id_pergunta_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.perguntas_id_pergunta_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.perguntas_id_pergunta_seq OWNER TO postgres;

--
-- Name: perguntas_id_pergunta_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.perguntas_id_pergunta_seq OWNED BY public.perguntas.id_pergunta;


--
-- Name: prompt_juizes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.prompt_juizes (
    id_prompt_juiz integer CONSTRAINT prompt_juizes_id_prompt_juiz_not_null1 NOT NULL,
    id_dataset integer CONSTRAINT prompt_juizes_id_dataset_not_null1 NOT NULL,
    versao integer NOT NULL,
    ds_prompt text CONSTRAINT prompt_juizes_ds_prompt_not_null1 NOT NULL,
    ds_persona text CONSTRAINT prompt_juizes_ds_persona_not_null1 NOT NULL,
    ds_contexto text CONSTRAINT prompt_juizes_ds_contexto_not_null1 NOT NULL,
    ds_rubrica text CONSTRAINT prompt_juizes_ds_rubrica_not_null1 NOT NULL,
    ds_saida text CONSTRAINT prompt_juizes_ds_saida_not_null1 NOT NULL,
    created_at timestamp without time zone DEFAULT now() CONSTRAINT prompt_juizes_created_at_not_null1 NOT NULL,
    created_by character varying(120) DEFAULT 'system'::character varying NOT NULL,
    ativo boolean DEFAULT false NOT NULL
);


ALTER TABLE public.prompt_juizes OWNER TO postgres;

--
-- Name: prompt_juizes_id_prompt_juiz_seq1; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.prompt_juizes_id_prompt_juiz_seq1
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.prompt_juizes_id_prompt_juiz_seq1 OWNER TO postgres;

--
-- Name: prompt_juizes_id_prompt_juiz_seq1; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.prompt_juizes_id_prompt_juiz_seq1 OWNED BY public.prompt_juizes.id_prompt_juiz;


--
-- Name: respostas_atividade_1; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.respostas_atividade_1 (
    id_resposta integer NOT NULL,
    id_pergunta integer NOT NULL,
    id_modelo integer NOT NULL,
    texto_resposta text NOT NULL,
    tempo_inferencia_ms double precision,
    data_geracao timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT respostas_atividade_1_tempo_inferencia_ms_check CHECK ((tempo_inferencia_ms >= (0)::double precision))
);


ALTER TABLE public.respostas_atividade_1 OWNER TO postgres;

--
-- Name: respostas_atividade_1_id_resposta_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.respostas_atividade_1_id_resposta_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.respostas_atividade_1_id_resposta_seq OWNER TO postgres;

--
-- Name: respostas_atividade_1_id_resposta_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.respostas_atividade_1_id_resposta_seq OWNED BY public.respostas_atividade_1.id_resposta;


--
-- Name: stage_respostas_disc_import; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stage_respostas_disc_import (
    nome_modelo text,
    versao text,
    parametro_precisao text,
    id_pergunta text,
    texto_resposta text,
    tempo_inferencia_ms text,
    data_geracao text
);


ALTER TABLE public.stage_respostas_disc_import OWNER TO postgres;

--
-- Name: stage_respostas_obj_import; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stage_respostas_obj_import (
    nome_modelo text,
    versao text,
    parametro_precisao text,
    id_pergunta text,
    texto_resposta text,
    tempo_inferencia_ms text,
    data_geracao text
);


ALTER TABLE public.stage_respostas_obj_import OWNER TO postgres;

--
-- Name: avaliacoes_juiz id_avaliacao; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.avaliacoes_juiz ALTER COLUMN id_avaliacao SET DEFAULT nextval('public.avaliacoes_juiz_id_avaliacao_seq'::regclass);


--
-- Name: datasets id_dataset; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.datasets ALTER COLUMN id_dataset SET DEFAULT nextval('public.datasets_id_dataset_seq'::regclass);


--
-- Name: modelos id_modelo; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.modelos ALTER COLUMN id_modelo SET DEFAULT nextval('public.modelos_id_modelo_seq'::regclass);


--
-- Name: perguntas id_pergunta; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.perguntas ALTER COLUMN id_pergunta SET DEFAULT nextval('public.perguntas_id_pergunta_seq'::regclass);


--
-- Name: prompt_juizes id_prompt_juiz; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.prompt_juizes ALTER COLUMN id_prompt_juiz SET DEFAULT nextval('public.prompt_juizes_id_prompt_juiz_seq1'::regclass);


--
-- Name: respostas_atividade_1 id_resposta; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.respostas_atividade_1 ALTER COLUMN id_resposta SET DEFAULT nextval('public.respostas_atividade_1_id_resposta_seq'::regclass);


--
-- Name: avaliacoes_juiz avaliacoes_juiz_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.avaliacoes_juiz
    ADD CONSTRAINT avaliacoes_juiz_pkey PRIMARY KEY (id_avaliacao);


--
-- Name: datasets datasets_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_pkey PRIMARY KEY (id_dataset);


--
-- Name: modelos modelos_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.modelos
    ADD CONSTRAINT modelos_pkey PRIMARY KEY (id_modelo);


--
-- Name: perguntas perguntas_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.perguntas
    ADD CONSTRAINT perguntas_pkey PRIMARY KEY (id_pergunta);


--
-- Name: prompt_juizes prompt_juizes_id_dataset_versao_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.prompt_juizes
    ADD CONSTRAINT prompt_juizes_id_dataset_versao_key UNIQUE (id_dataset, versao);


--
-- Name: prompt_juizes prompt_juizes_pkey1; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.prompt_juizes
    ADD CONSTRAINT prompt_juizes_pkey1 PRIMARY KEY (id_prompt_juiz);


--
-- Name: respostas_atividade_1 respostas_atividade_1_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.respostas_atividade_1
    ADD CONSTRAINT respostas_atividade_1_pkey PRIMARY KEY (id_resposta);


--
-- Name: idx_avaliacoes_juiz; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_avaliacoes_juiz ON public.avaliacoes_juiz USING btree (id_modelo_juiz);


--
-- Name: idx_avaliacoes_resposta; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_avaliacoes_resposta ON public.avaliacoes_juiz USING btree (id_resposta_ativa1);


--
-- Name: idx_perguntas_dataset; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_perguntas_dataset ON public.perguntas USING btree (id_dataset);


--
-- Name: idx_prompt_juizes_active_per_dataset; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_prompt_juizes_active_per_dataset ON public.prompt_juizes USING btree (id_dataset) WHERE ativo;


--
-- Name: idx_respostas_modelo; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_respostas_modelo ON public.respostas_atividade_1 USING btree (id_modelo);


--
-- Name: idx_respostas_pergunta; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_respostas_pergunta ON public.respostas_atividade_1 USING btree (id_pergunta);


--
-- Name: avaliacoes_juiz avaliacoes_juiz_id_modelo_juiz_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.avaliacoes_juiz
    ADD CONSTRAINT avaliacoes_juiz_id_modelo_juiz_fkey FOREIGN KEY (id_modelo_juiz) REFERENCES public.modelos(id_modelo);


--
-- Name: avaliacoes_juiz avaliacoes_juiz_id_prompt_juiz_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.avaliacoes_juiz
    ADD CONSTRAINT avaliacoes_juiz_id_prompt_juiz_fkey FOREIGN KEY (id_prompt_juiz) REFERENCES public.prompt_juizes(id_prompt_juiz);


--
-- Name: avaliacoes_juiz avaliacoes_juiz_id_resposta_ativa1_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.avaliacoes_juiz
    ADD CONSTRAINT avaliacoes_juiz_id_resposta_ativa1_fkey FOREIGN KEY (id_resposta_ativa1) REFERENCES public.respostas_atividade_1(id_resposta);


--
-- Name: perguntas perguntas_id_dataset_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.perguntas
    ADD CONSTRAINT perguntas_id_dataset_fkey FOREIGN KEY (id_dataset) REFERENCES public.datasets(id_dataset);


--
-- Name: prompt_juizes prompt_juizes_id_dataset_fkey1; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.prompt_juizes
    ADD CONSTRAINT prompt_juizes_id_dataset_fkey1 FOREIGN KEY (id_dataset) REFERENCES public.datasets(id_dataset);


--
-- Name: respostas_atividade_1 respostas_atividade_1_id_modelo_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.respostas_atividade_1
    ADD CONSTRAINT respostas_atividade_1_id_modelo_fkey FOREIGN KEY (id_modelo) REFERENCES public.modelos(id_modelo);


--
-- Name: respostas_atividade_1 respostas_atividade_1_id_pergunta_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.respostas_atividade_1
    ADD CONSTRAINT respostas_atividade_1_id_pergunta_fkey FOREIGN KEY (id_pergunta) REFERENCES public.perguntas(id_pergunta);


--
-- PostgreSQL database dump complete
--

\unrestrict onCd4pMPZlbX93pXplbbdGd4H1g7OpDcL4AuTBLNN2CGiQEakHmTfCpDcgh6epA

