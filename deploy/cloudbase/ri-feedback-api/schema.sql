-- Only for a NEW environment. Existing pilot table must NOT be recreated.
-- A failed statement rolls back the entire transaction; do not bypass role errors.
BEGIN;
CREATE TABLE public.ri_feedback_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id uuid NOT NULL,
    local_feedback_id varchar(64) NOT NULL,
    receipt_token_hash text NOT NULL CHECK (receipt_token_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 8192
    ),
    status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved', 'dismissed', 'withdrawn')),
    processing_note text NOT NULL DEFAULT '' CHECK (char_length(processing_note) <= 2000),
    state_revision bigint NOT NULL DEFAULT 0 CHECK (state_revision >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (installation_id, local_feedback_id)
);
ALTER TABLE public.ri_feedback_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.ri_feedback_requests FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ri_feedback_requests TO service_role;
COMMIT;
