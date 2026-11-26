-- Run once in the existing environment. Does not touch feedback records.
-- All account mutations share one row lock and re-check the actor in the same transaction.
BEGIN;
CREATE TABLE IF NOT EXISTS public.ri_team_accounts (
    username text PRIMARY KEY CHECK (username ~ '^[a-z][a-z0-9_.-]{2,49}$'),
    password_hash text NOT NULL CHECK (password_hash ~ '^scrypt[$][0-9a-f]{32}[$][0-9a-f]{64}$'),
    role text NOT NULL CHECK (role IN ('owner', 'admin')),
    enabled boolean NOT NULL DEFAULT true,
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.ri_team_account_guard (
    id integer PRIMARY KEY CHECK (id = 1)
);
INSERT INTO public.ri_team_account_guard VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.ri_team_account_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor text NOT NULL, target text NOT NULL, action text NOT NULL,
    account_revision bigint NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.ri_team_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ri_team_account_guard ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ri_team_account_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.ri_team_accounts, public.ri_team_account_guard,
    public.ri_team_account_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.ri_team_accounts TO service_role;

CREATE OR REPLACE FUNCTION public.ri_team_bootstrap(p_username text, p_password_hash text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target public.ri_team_accounts%ROWTYPE;
BEGIN
    PERFORM id FROM public.ri_team_account_guard WHERE id = 1 FOR UPDATE;
    IF EXISTS (SELECT 1 FROM public.ri_team_accounts) THEN
        RETURN jsonb_build_object('error', 'ALREADY_INITIALIZED');
    END IF;
    IF p_username IS NULL OR p_username !~ '^[a-z][a-z0-9_.-]{2,49}$'
        OR p_password_hash IS NULL OR p_password_hash !~ '^scrypt[$][0-9a-f]{32}[$][0-9a-f]{64}$' THEN
        RETURN jsonb_build_object('error', 'INVALID_INPUT');
    END IF;
    INSERT INTO public.ri_team_accounts(username, password_hash, role)
        VALUES(p_username, p_password_hash, 'owner') RETURNING * INTO target;
    INSERT INTO public.ri_team_account_events(actor, target, action, account_revision)
        VALUES(p_username, p_username, 'bootstrap', target.revision);
    RETURN jsonb_build_object('account', to_jsonb(target) - 'password_hash');
END;
$$;
REVOKE ALL ON FUNCTION public.ri_team_bootstrap(text, text) FROM PUBLIC, anon, authenticated, service_role;
-- Only the database owner who created the function bootstraps the first owner via SQL console.

CREATE OR REPLACE FUNCTION public.ri_team_manage(
    p_actor text, p_actor_revision bigint, p_action text, p_username text,
    p_expected_revision bigint DEFAULT NULL, p_password_hash text DEFAULT NULL,
    p_role text DEFAULT NULL, p_enabled boolean DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    actor public.ri_team_accounts%ROWTYPE;
    target public.ri_team_accounts%ROWTYPE;
    next_role text;
    next_enabled boolean;
BEGIN
    PERFORM id FROM public.ri_team_account_guard WHERE id = 1 FOR UPDATE;
    SELECT * INTO actor FROM public.ri_team_accounts WHERE username = p_actor;
    IF NOT FOUND OR NOT actor.enabled OR p_actor_revision IS NULL OR actor.revision <> p_actor_revision THEN
        RETURN jsonb_build_object('error', 'UNAUTHORIZED');
    END IF;
    IF p_action IS NULL OR p_action NOT IN ('create', 'update', 'password')
        OR p_username IS NULL OR p_username !~ '^[a-z][a-z0-9_.-]{2,49}$'
        OR (p_password_hash IS NOT NULL AND p_password_hash !~ '^scrypt[$][0-9a-f]{32}[$][0-9a-f]{64}$')
        OR (p_role IS NOT NULL AND p_role NOT IN ('owner', 'admin')) THEN
        RETURN jsonb_build_object('error', 'INVALID_INPUT');
    END IF;
    IF p_action = 'password' THEN
        IF p_username <> actor.username OR p_password_hash IS NULL OR p_role IS NOT NULL OR p_enabled IS NOT NULL THEN
            RETURN jsonb_build_object('error', 'FORBIDDEN');
        END IF;
    ELSIF actor.role <> 'owner' THEN
        RETURN jsonb_build_object('error', 'FORBIDDEN');
    END IF;
    IF p_action = 'create' THEN
        IF p_password_hash IS NULL OR p_role IS NULL OR p_enabled IS DISTINCT FROM true THEN
            RETURN jsonb_build_object('error', 'INVALID_INPUT');
        END IF;
        IF EXISTS (SELECT 1 FROM public.ri_team_accounts WHERE username = p_username) THEN
            RETURN jsonb_build_object('error', 'ACCOUNT_EXISTS');
        END IF;
        IF (SELECT count(*) FROM public.ri_team_accounts) >= 200 THEN
            RETURN jsonb_build_object('error', 'INVALID_INPUT');
        END IF;
        INSERT INTO public.ri_team_accounts(username, password_hash, role, enabled)
            VALUES(p_username, p_password_hash, p_role, true) RETURNING * INTO target;
    ELSE
        SELECT * INTO target FROM public.ri_team_accounts WHERE username = p_username;
        IF NOT FOUND THEN RETURN jsonb_build_object('error', 'NOT_FOUND'); END IF;
        IF p_action <> 'password' AND p_username = actor.username AND p_password_hash IS NOT NULL THEN
            RETURN jsonb_build_object('error', 'FORBIDDEN');
        END IF;
        IF p_expected_revision IS NULL OR target.revision <> p_expected_revision THEN
            RETURN jsonb_build_object('error', 'STATE_CONFLICT');
        END IF;
        next_role := coalesce(p_role, target.role);
        next_enabled := coalesce(p_enabled, target.enabled);
        IF target.username = actor.username AND (NOT next_enabled OR next_role <> actor.role) THEN
            RETURN jsonb_build_object('error', 'SELF_DISABLE');
        END IF;
        IF target.enabled AND target.role = 'owner' AND (NOT next_enabled OR next_role <> 'owner')
            AND (SELECT count(*) FROM public.ri_team_accounts WHERE enabled AND role = 'owner') <= 1 THEN
            RETURN jsonb_build_object('error', 'LAST_OWNER');
        END IF;
        UPDATE public.ri_team_accounts SET password_hash = coalesce(p_password_hash, password_hash),
            role = next_role, enabled = next_enabled, revision = revision + 1, updated_at = now()
            WHERE username = p_username RETURNING * INTO target;
    END IF;
    INSERT INTO public.ri_team_account_events(actor, target, action, account_revision)
        VALUES(actor.username, target.username, p_action, target.revision);
    RETURN jsonb_build_object('account', to_jsonb(target) - 'password_hash');
END;
$$;
REVOKE ALL ON FUNCTION public.ri_team_manage(text, bigint, text, text, bigint, text, text, boolean)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ri_team_manage(text, bigint, text, text, bigint, text, text, boolean)
    TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
