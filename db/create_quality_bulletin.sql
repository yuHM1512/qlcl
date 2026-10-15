CREATE TABLE IF NOT EXISTS public.bulletin_source_records (
    id BIGSERIAL PRIMARY KEY,
    source_type VARCHAR(40) NOT NULL,
    source_id TEXT NOT NULL,
    source_no TEXT,
    source_date DATE,
    unit_name TEXT,
    product_type TEXT,
    topic TEXT,
    description TEXT,
    source_status TEXT,
    source_deadline DATE,
    source_owner TEXT,
    source_url TEXT,
    inspected_count NUMERIC,
    failed_count NUMERIC,
    rate NUMERIC,
    target NUMERIC,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bulletin_source UNIQUE (source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_bulletin_source_period
    ON public.bulletin_source_records (source_type, source_date);
CREATE INDEX IF NOT EXISTS idx_bulletin_source_status
    ON public.bulletin_source_records (source_type, source_status) WHERE is_active;

CREATE TABLE IF NOT EXISTS public.quality_bulletins (
    id BIGSERIAL PRIMARY KEY,
    week_start DATE NOT NULL UNIQUE,
    week_end DATE NOT NULL,
    iso_year INTEGER NOT NULL,
    iso_week INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'verified')),
    version INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    verified_by TEXT,
    verified_at TIMESTAMPTZ,
    saved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_bulletins_week
    ON public.quality_bulletins (iso_year DESC, iso_week DESC);

CREATE TABLE IF NOT EXISTS public.quality_bulletin_items (
    id BIGSERIAL PRIMARY KEY,
    bulletin_id BIGINT NOT NULL REFERENCES public.quality_bulletins(id) ON DELETE CASCADE,
    source_record_id BIGINT REFERENCES public.bulletin_source_records(id) ON DELETE SET NULL,
    source_type VARCHAR(40) NOT NULL,
    source_id TEXT NOT NULL,
    source_no TEXT,
    topic TEXT,
    unit_name TEXT,
    description TEXT,
    source_status TEXT,
    status TEXT NOT NULL DEFAULT 'Chưa tiếp nhận',
    status_origin VARCHAR(16) NOT NULL DEFAULT 'manual'
        CHECK (status_origin IN ('manual', 'source')),
    deadline DATE,
    owner_ma_nv TEXT,
    owner_name TEXT,
    source_url TEXT,
    carried_from_item_id BIGINT REFERENCES public.quality_bulletin_items(id) ON DELETE SET NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_quality_bulletin_item UNIQUE (bulletin_id, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_quality_bulletin_items_open
    ON public.quality_bulletin_items (bulletin_id, status);

CREATE TABLE IF NOT EXISTS public.quality_bulletin_entries (
    id BIGSERIAL PRIMARY KEY,
    bulletin_id BIGINT NOT NULL REFERENCES public.quality_bulletins(id) ON DELETE CASCADE,
    entry_type VARCHAR(24) NOT NULL CHECK (entry_type IN ('reminder', 'quality_alert')),
    title TEXT NOT NULL,
    content TEXT,
    due_date DATE,
    assignee TEXT,
    level VARCHAR(16) NOT NULL DEFAULT 'warning'
        CHECK (level IN ('info', 'warning', 'critical')),
    status TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_bulletin_entries
    ON public.quality_bulletin_entries (bulletin_id, entry_type, sort_order, id);

CREATE TABLE IF NOT EXISTS public.quality_bulletin_metrics (
    id BIGSERIAL PRIMARY KEY,
    bulletin_id BIGINT REFERENCES public.quality_bulletins(id) ON DELETE CASCADE,
    period_type VARCHAR(16) NOT NULL CHECK (period_type IN ('weekly', 'monthly')),
    source_type VARCHAR(24) NOT NULL CHECK (source_type IN ('final', 'endline')),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    unit_name TEXT NOT NULL DEFAULT '',
    product_type TEXT NOT NULL DEFAULT '',
    inspected_count NUMERIC,
    failed_count NUMERIC,
    rate NUMERIC,
    target NUMERIC,
    passed BOOLEAN,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_quality_bulletin_metric UNIQUE
        (bulletin_id, period_type, source_type, period_start, unit_name, product_type)
);

CREATE TABLE IF NOT EXISTS public.quality_bulletin_kpis (
    id BIGSERIAL PRIMARY KEY,
    bulletin_id BIGINT NOT NULL REFERENCES public.quality_bulletins(id) ON DELETE CASCADE,
    kpi_key TEXT NOT NULL,
    category TEXT,
    label TEXT NOT NULL,
    value_numeric NUMERIC,
    value_text TEXT,
    target_numeric NUMERIC,
    unit TEXT,
    status TEXT,
    source_url TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_quality_bulletin_kpi UNIQUE (bulletin_id, kpi_key)
);

CREATE TABLE IF NOT EXISTS public.quality_bulletin_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    trigger_type VARCHAR(16) NOT NULL DEFAULT 'manual',
    triggered_by TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'success', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT
);
