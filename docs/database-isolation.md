# PostgreSQL scope isolation

The SQL integration can deny reads and writes for a selected tenant scope while leaving other scopes accessible. It is not an automatic schema discovery or database backup system. A database administrator must map the policy to each application table and test the application's real roles and queries.

## Install the control schema

Review and run `deploy/postgres-isolation.sql` once as an authorised database administrator. It creates:

* `charisma_guard.isolated_scopes`, keyed by service and tenant UUID, with an expiry and reason.
* `charisma_guard.scope_allowed(service_name, scope)`, a narrowly scoped security-definer predicate with a fixed search path.
* `charisma_guard.scope_events`, recording control changes, database login and previous/current values.
* `charisma_runtime`, which may call the predicate, and `charisma_security_admin`, which may manage isolation rows and read the audit table.

Both roles are created with `NOLOGIN`. Grant them only to the intended existing logins. The application must never receive the security administrator role. Only a database administrator should own the schema/functions. Check existing objects and privileges before applying the script to a database with pre-existing names.

## Add restrictive policies

Keep your existing tenant/ownership policy. The Charisma policy must be `AS RESTRICTIVE` so it narrows existing access instead of accidentally providing new access. Example for an existing `app.orders` table with a non-null `tenant_id uuid`:

```sql
ALTER TABLE app.orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.orders FORCE ROW LEVEL SECURITY;

CREATE POLICY charisma_isolation ON app.orders AS RESTRICTIVE
TO charisma_runtime
USING (charisma_guard.scope_allowed('orders', tenant_id))
WITH CHECK (charisma_guard.scope_allowed('orders', tenant_id));

GRANT charisma_runtime TO your_existing_application_login;
```

These identifiers are examples. Do not replace your existing permissive ownership policy with `USING (true)`. Application logins must not be superusers, `BYPASSRLS` roles or table owners. Review views, security-definer functions, connection pools and any other access path that could bypass row policies. Cover every relevant table and avoid null/unmapped scope identifiers.

## Isolate and release a scope

Through a separate authorised control login:

```sql
INSERT INTO charisma_guard.isolated_scopes(service, scope_id, expires_at, reason)
VALUES ('orders', '11111111-1111-4111-8111-111111111111',
        now() + interval '10 minutes', 'Investigating an affected tenant scope')
ON CONFLICT (service, scope_id) DO UPDATE
SET expires_at = EXCLUDED.expires_at, reason = EXCLUDED.reason;
```

The UUID is a fixture example, not a real tenant. New/updated leases cannot exceed one hour from the database transaction time. Expiry allows access again through the predicate without a cleanup job. To resume sooner:

```sql
DELETE FROM charisma_guard.isolated_scopes
WHERE service = 'orders'
  AND scope_id = '11111111-1111-4111-8111-111111111111';
```

Use bound parameters when integrating these operations into application tooling. Keep reasons free of customer data. Ordinary application users cannot modify the control table or its audit trail through the granted runtime role. A database administrator remains able to change stored data; this is not protection against a compromised DBA.

The dashboard's service isolation and this database scope isolation are separate controls. The current dashboard does not execute SQL against your external PostgreSQL database. Your control application must integrate that deliberately if needed.

## Verify your integration

CI uses a real PostgreSQL service to test that one scope is hidden, another remains visible, writes into the isolated scope fail, runtime users cannot modify control rows and expiry restores access. The fixture's permissive policy is intentionally simple for testing; it is not a production tenant-access policy.

Before live use, test your own application's roles, read/write paths, long-running transactions, jobs, cache behaviour and recovery access. A row policy does not delete malicious data, disconnect an attacker from other services or restore a damaged database. Set retention and monitoring for expired control rows and `scope_events` using your database administration process.
