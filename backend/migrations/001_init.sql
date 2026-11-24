CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Mock CRM ------------------------------------------------------------------
CREATE TABLE customers (
    id              text PRIMARY KEY,
    name            text NOT NULL,
    pin             text NOT NULL,
    tier            text NOT NULL CHECK (tier IN ('free', 'pro', 'enterprise')),
    contract_status text NOT NULL CHECK (contract_status IN ('active', 'expired', 'past_due')),
    email           text NOT NULL,
    phone           text NOT NULL,
    billing_contact text NOT NULL,
    chaos_flags     jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE invoices (
    id           text PRIMARY KEY,
    customer_id  text NOT NULL REFERENCES customers (id),
    amount_cents integer NOT NULL CHECK (amount_cents >= 0),
    issued_at    date NOT NULL,
    description  text NOT NULL
);

-- Single source of truth for refund limits. The corpus must agree; ingest checks it.
CREATE TABLE policy_limits (
    tier             text PRIMARY KEY CHECK (tier IN ('free', 'pro', 'enterprise')),
    max_refund_cents integer NOT NULL,
    window_days      integer NOT NULL
);

CREATE TABLE refunds (
    id              bigserial PRIMARY KEY,
    invoice_id      text NOT NULL REFERENCES invoices (id),
    customer_id     text NOT NULL REFERENCES customers (id),
    amount_cents    integer NOT NULL CHECK (amount_cents > 0),
    reason          text NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Knowledge base --------------------------------------------------------------
CREATE TABLE policy_chunks (
    id           bigserial PRIMARY KEY,
    doc_id       text NOT NULL,
    section_path text NOT NULL,
    tier         text NOT NULL CHECK (tier IN ('all', 'free', 'pro', 'enterprise')),
    doc_type     text NOT NULL CHECK (doc_type IN ('policy', 'troubleshooting')),
    content      text NOT NULL,
    embed_text   text NOT NULL,
    content_hash text NOT NULL UNIQUE,
    embedding    vector(1536) NOT NULL
);
CREATE INDEX policy_chunks_embedding_idx ON policy_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX policy_chunks_tier_idx ON policy_chunks (tier);

-- Conversations ----------------------------------------------------------------
CREATE TABLE sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    customer_id     text REFERENCES customers (id),
    verify_failures integer NOT NULL DEFAULT 0,
    escalation      jsonb,
    chaos           jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE messages (
    id          bigserial PRIMARY KEY,
    session_id  uuid NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    turn_id     text NOT NULL,
    channel     text NOT NULL CHECK (channel IN ('chat', 'voice')),
    role        text NOT NULL CHECK (role IN ('user', 'assistant')),
    content     text NOT NULL,
    interrupted boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_session_idx ON messages (session_id, id);

CREATE SEQUENCE ticket_seq START WITH 100;
CREATE TABLE tickets (
    id          text PRIMARY KEY,
    session_id  uuid NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    customer_id text REFERENCES customers (id),
    summary     text NOT NULL,
    category    text NOT NULL,
    priority    text NOT NULL CHECK (priority IN ('low', 'normal', 'high')),
    reason      text NOT NULL,
    turns       jsonb NOT NULL DEFAULT '[]',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE traces (
    turn_id    text PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    channel    text NOT NULL,
    status     text NOT NULL,
    spans      jsonb NOT NULL DEFAULT '[]',
    usage      jsonb NOT NULL DEFAULT '[]',
    latency    jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX traces_session_idx ON traces (session_id, created_at);

CREATE TABLE spend (
    day date PRIMARY KEY,
    usd numeric(12, 6) NOT NULL DEFAULT 0
);
