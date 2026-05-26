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
    search_vector        tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(ps_number, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(mfg_part_number, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(name, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'C')
    ) STORED,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS parts_search_idx ON parts USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS parts_mfg_idx ON parts (mfg_part_number);

CREATE TABLE IF NOT EXISTS models (
    id              BIGSERIAL PRIMARY KEY,
    model_number    TEXT NOT NULL UNIQUE,
    brand           TEXT,
    appliance_type  TEXT NOT NULL CHECK (appliance_type IN ('Refrigerator', 'Dishwasher')),
    name            TEXT,
    common_symptoms JSONB NOT NULL DEFAULT '[]'::jsonb,
    url             TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Compatibility join.
CREATE TABLE IF NOT EXISTS model_parts (
    model_id BIGINT NOT NULL REFERENCES models (id) ON DELETE CASCADE,
    part_id  BIGINT NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    PRIMARY KEY (model_id, part_id)
);

CREATE TABLE IF NOT EXISTS part_symptoms (
    part_id BIGINT NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    symptom TEXT NOT NULL,
    PRIMARY KEY (part_id, symptom)
);

CREATE TABLE IF NOT EXISTS part_qa (
    id       BIGSERIAL PRIMARY KEY,
    part_id  BIGINT NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    question TEXT,
    answer   TEXT
);

-- Schematic / exploded-view diagram URLs, keyed to a model.
CREATE TABLE IF NOT EXISTS diagrams (
    id        BIGSERIAL PRIMARY KEY,
    model_id  BIGINT NOT NULL REFERENCES models (id) ON DELETE CASCADE,
    name      TEXT,
    image_url TEXT NOT NULL,
    section   TEXT
);

-- Semantic-search corpus: one row per embeddable chunk of part text.
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
