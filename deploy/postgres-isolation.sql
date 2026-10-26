-- Run once as a database administrator in an authorised PostgreSQL database.
-- This adds an isolated control schema; it does not alter application tables.
BEGIN;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='charisma_security_admin') THEN CREATE ROLE charisma_security_admin NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='charisma_runtime') THEN CREATE ROLE charisma_runtime NOLOGIN; END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS charisma_guard;
REVOKE ALL ON SCHEMA charisma_guard FROM PUBLIC;
CREATE TABLE IF NOT EXISTS charisma_guard.isolated_scopes (
  service text NOT NULL CHECK (service ~ '^[a-z][a-z0-9_-]{0,39}$'),
  scope_id uuid NOT NULL,
  expires_at timestamptz NOT NULL CHECK(expires_at <= CURRENT_TIMESTAMP + interval '1 hour'),
  reason text NOT NULL CHECK(length(reason) BETWEEN 3 AND 200),
  PRIMARY KEY(service,scope_id)
);
REVOKE ALL ON charisma_guard.isolated_scopes FROM PUBLIC;
GRANT USAGE ON SCHEMA charisma_guard TO charisma_runtime, charisma_security_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON charisma_guard.isolated_scopes TO charisma_security_admin;
CREATE OR REPLACE FUNCTION charisma_guard.scope_allowed(service_name text, scope uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, charisma_guard
AS $$ SELECT NOT EXISTS(SELECT 1 FROM charisma_guard.isolated_scopes WHERE service=service_name AND scope_id=scope AND expires_at>statement_timestamp()) $$;
REVOKE ALL ON FUNCTION charisma_guard.scope_allowed(text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION charisma_guard.scope_allowed(text,uuid) TO charisma_runtime;
CREATE TABLE IF NOT EXISTS charisma_guard.scope_events (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT clock_timestamp(),
  login_name text NOT NULL,
  action text NOT NULL,
  previous jsonb,
  current_value jsonb
);
REVOKE ALL ON charisma_guard.scope_events FROM PUBLIC;
GRANT SELECT ON charisma_guard.scope_events TO charisma_security_admin;
CREATE OR REPLACE FUNCTION charisma_guard.record_scope_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, charisma_guard
AS $$ BEGIN
  INSERT INTO charisma_guard.scope_events(login_name,action,previous,current_value)
  VALUES(session_user,TG_OP,CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END,CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW) END);
  RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION charisma_guard.record_scope_change() FROM PUBLIC;
DROP TRIGGER IF EXISTS charisma_scope_history ON charisma_guard.isolated_scopes;
CREATE TRIGGER charisma_scope_history AFTER INSERT OR UPDATE OR DELETE ON charisma_guard.isolated_scopes
FOR EACH ROW EXECUTE FUNCTION charisma_guard.record_scope_change();
COMMIT;
-- For each existing application table, an administrator must add an explicit
-- AS RESTRICTIVE policy. Keep your existing tenant/ownership policy in place.
-- Example, adapt identifiers to the real schema:
-- ALTER TABLE app.orders ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE app.orders FORCE ROW LEVEL SECURITY;
-- CREATE POLICY charisma_isolation ON app.orders AS RESTRICTIVE
--   TO charisma_runtime
--   USING (charisma_guard.scope_allowed('orders', tenant_id))
--   WITH CHECK (charisma_guard.scope_allowed('orders', tenant_id));
-- GRANT charisma_runtime TO your_app_login;
-- Application logins must not be superusers, BYPASSRLS roles or table owners.
