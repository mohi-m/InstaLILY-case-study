-- PartSelect agent schema. Idempotent: safe to run on every backend boot.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS parts (
    id                   BIGSERIAL PRIMARY KEY,
    ps_number            TEXT NOT NULL UNIQUE,
    mfg_part_number      TEXT,
    name                 TEXT NOT NULL,
    brand                TEXT,
    appliance_type       TEXT NOT NULL CHECK (appliance_type IN ('Refrigerator', 'Dishwasher')),
    price                NUMERIC(10, 2),
    stock_status         TEXT,
    description          TEXT,
    install_instructions TEXT,
    url                  TEXT,
    symptom_text         TEXT,
    image_url            TEXT,
    install_difficulty   TEXT,
    install_time         TEXT,
    search_vector        tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(ps_number, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(mfg_part_number, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(name, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(symptom_text, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'C')
    ) STORED,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS parts_search_idx ON parts USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS parts_mfg_idx ON parts (mfg_part_number);

CREATE TABLE IF NOT EXISTS models (
    id             BIGSERIAL PRIMARY KEY,
    model_number   TEXT NOT NULL UNIQUE,
    brand          TEXT,
    appliance_type TEXT NOT NULL CHECK (appliance_type IN ('Refrigerator', 'Dishwasher')),
    name           TEXT,
    url            TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_parts (
    model_id BIGINT NOT NULL REFERENCES models (id) ON DELETE CASCADE,
    part_id  BIGINT NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    PRIMARY KEY (model_id, part_id)
);

CREATE TABLE IF NOT EXISTS part_chunks (
    id         BIGSERIAL PRIMARY KEY,
    part_id    BIGINT NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    chunk_type TEXT NOT NULL CHECK (chunk_type IN ('description', 'install', 'qa', 'symptom')),
    content    TEXT NOT NULL,
    embedding  vector(1536)
);

CREATE INDEX IF NOT EXISTS part_chunks_part_idx ON part_chunks (part_id);
CREATE INDEX IF NOT EXISTS part_chunks_embedding_idx
    ON part_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS symptoms (
    id             BIGSERIAL PRIMARY KEY,
    model_id       BIGINT NOT NULL REFERENCES models (id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    url            TEXT,
    name_embedding vector(1536),
    UNIQUE (model_id, name)
);

CREATE INDEX IF NOT EXISTS symptoms_model_idx ON symptoms (model_id);
CREATE INDEX IF NOT EXISTS symptoms_embedding_idx
    ON symptoms USING ivfflat (name_embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS symptom_parts (
    symptom_id    BIGINT NOT NULL REFERENCES symptoms (id) ON DELETE CASCADE,
    part_id       BIGINT NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    effectiveness NUMERIC(5, 2),
    PRIMARY KEY (symptom_id, part_id)
);

CREATE TABLE IF NOT EXISTS model_qa (
    id                 BIGSERIAL PRIMARY KEY,
    model_id           BIGINT NOT NULL REFERENCES models (id) ON DELETE CASCADE,
    question           TEXT,
    answer             TEXT,
    question_embedding vector(1536)
);

CREATE INDEX IF NOT EXISTS model_qa_model_idx ON model_qa (model_id);
CREATE INDEX IF NOT EXISTS model_qa_embedding_idx
    ON model_qa USING ivfflat (question_embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS qa_parts (
    qa_id   BIGINT NOT NULL REFERENCES model_qa (id) ON DELETE CASCADE,
    part_id BIGINT NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    PRIMARY KEY (qa_id, part_id)
);
