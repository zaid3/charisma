\set ON_ERROR_STOP on
\i deploy/postgres-isolation.sql
CREATE ROLE fixture_app LOGIN;
GRANT charisma_runtime TO fixture_app;
CREATE TABLE public.fixture_orders(tenant_id uuid, value text);
INSERT INTO public.fixture_orders VALUES('11111111-1111-4111-8111-111111111111','first'),('22222222-2222-4222-8222-222222222222','second');
GRANT SELECT,INSERT ON public.fixture_orders TO fixture_app;
ALTER TABLE public.fixture_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fixture_orders FORCE ROW LEVEL SECURITY;
CREATE POLICY fixture_existing_access ON public.fixture_orders FOR ALL TO fixture_app USING(true) WITH CHECK(true);
CREATE POLICY fixture_isolation ON public.fixture_orders AS RESTRICTIVE TO charisma_runtime
 USING(charisma_guard.scope_allowed('orders',tenant_id)) WITH CHECK(charisma_guard.scope_allowed('orders',tenant_id));
INSERT INTO charisma_guard.isolated_scopes VALUES('orders','11111111-1111-4111-8111-111111111111',now()+interval '5 minutes','Fixture isolation');
SET ROLE fixture_app;
DO $$ BEGIN
 IF (SELECT count(*) FROM public.fixture_orders)<>1 THEN RAISE EXCEPTION 'Isolation did not hide only the affected scope'; END IF;
 IF (SELECT value FROM public.fixture_orders)<>'second' THEN RAISE EXCEPTION 'Unaffected scope was altered'; END IF;
 BEGIN
   INSERT INTO public.fixture_orders VALUES('11111111-1111-4111-8111-111111111111','blocked');
   RAISE EXCEPTION 'Write was incorrectly allowed';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 BEGIN
   DELETE FROM charisma_guard.isolated_scopes;
   RAISE EXCEPTION 'Application can modify the control table';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;
RESET ROLE;
UPDATE charisma_guard.isolated_scopes SET expires_at=now()-interval '1 second';
SET ROLE fixture_app;
DO $$ BEGIN IF (SELECT count(*) FROM public.fixture_orders)<>2 THEN RAISE EXCEPTION 'Expired isolation did not restore access'; END IF; END $$;
RESET ROLE;
