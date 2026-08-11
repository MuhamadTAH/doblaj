-- ============================================================================
-- Migration 0004: Wayl Payment Gateway Migration
-- ============================================================================

-- Ensure app.transactions exists
CREATE TABLE IF NOT EXISTS app.transactions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references app.workspaces(id) on delete cascade,
  tier text not null,
  amount_usd integer not null,
  minutes_added integer not null,
  created_at timestamptz not null default now()
);

-- Add Wayl fields to app.transactions
ALTER TABLE app.transactions ADD COLUMN IF NOT EXISTS reference_id text UNIQUE;
ALTER TABLE app.transactions ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'pending';
ALTER TABLE app.transactions ADD COLUMN IF NOT EXISTS currency text NOT NULL DEFAULT 'IQD';
ALTER TABLE app.transactions ADD COLUMN IF NOT EXISTS total_iqd integer;

-- Index reference_id for high-performance lookup during webhooks
CREATE INDEX IF NOT EXISTS app_transactions_reference_id_idx ON app.transactions(reference_id);

-- Enable RLS
ALTER TABLE app.transactions ENABLE ROW LEVEL SECURITY;
