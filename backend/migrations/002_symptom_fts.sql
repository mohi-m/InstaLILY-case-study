-- Add symptom_text to parts and rebuild search_vector to include it.
-- Idempotent: the DO block only runs if the column doesn't exist yet.
-- Symptoms are stored normalised in part_symptoms but we denormalise a joined
-- text blob into parts.symptom_text so the GENERATED tsvector can index them.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'parts' AND column_name = 'symptom_text'
    ) THEN
        ALTER TABLE parts ADD COLUMN symptom_text TEXT;

        -- GENERATED columns can't be altered in-place; drop and recreate.
        ALTER TABLE parts DROP COLUMN IF EXISTS search_vector;
        ALTER TABLE parts ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(ps_number, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(mfg_part_number, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(name, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(symptom_text, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'C')
        ) STORED;

        DROP INDEX IF EXISTS parts_search_idx;
        CREATE INDEX parts_search_idx ON parts USING GIN (search_vector);
    END IF;
END $$;
