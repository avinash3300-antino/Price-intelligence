-- System role templates.
--
-- Three starting points, chosen so the common cases need no per-user fiddling:
--
--   Viewer   — read the numbers, change nothing.
--   Analyst  — do the actual mapping work, but cannot delete a seller and its
--              whole option set, and cannot manage users. This is the default
--              for a destination head.
--   Admin    — everything.
--
-- Admins bypass permission checks entirely in the API, so the Admin template
-- exists mainly so the admin screen has something coherent to show rather
-- than an empty checklist.
--
-- Templates are a starting point, never a cage: per-user overrides in
-- user_permissions can add or remove any individual permission on top.
-- is_system marks these three as undeletable; admins can add their own.

BEGIN;

INSERT INTO role_templates (name, description, is_system, created_at) VALUES
    ('Viewer',  'Read-only access to mapped pairs, the workspace and the portfolio view.', TRUE, NOW()::TEXT),
    ('Analyst', 'Full mapping work within scope. Cannot delete sellers or manage users.',  TRUE, NOW()::TEXT),
    ('Admin',   'Unrestricted access, including user management.',                          TRUE, NOW()::TEXT)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    is_system   = EXCLUDED.is_system;

-- Viewer: look, do not touch.
INSERT INTO role_template_permissions (template_id, permission_key)
SELECT t.id, p.key
FROM role_templates t
CROSS JOIN permissions p
WHERE t.name = 'Viewer'
  AND p.key IN ('mapped.view', 'mapping.view', 'comparison.view', 'export.data')
ON CONFLICT DO NOTHING;

-- Analyst: everything except the destructive pair and user management.
INSERT INTO role_template_permissions (template_id, permission_key)
SELECT t.id, p.key
FROM role_templates t
CROSS JOIN permissions p
WHERE t.name = 'Analyst'
  AND p.key NOT IN ('competitor.delete_option', 'competitor.delete_seller', 'admin.users')
ON CONFLICT DO NOTHING;

-- Admin: the lot.
INSERT INTO role_template_permissions (template_id, permission_key)
SELECT t.id, p.key
FROM role_templates t
CROSS JOIN permissions p
WHERE t.name = 'Admin'
ON CONFLICT DO NOTHING;

COMMIT;
