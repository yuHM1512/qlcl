-- Version product visual catalogs by business effective date.
-- Existing rows remain valid and keep their IDs; data assignment is handled by
-- scripts/deploy_co2_visual_catalog.py after this schema migration.

CREATE TABLE IF NOT EXISTS public.dm_visual_catalog (
    id SERIAL PRIMARY KEY,
    loai_hang_id INTEGER NOT NULL
        REFERENCES public.dm_loai_hang(id) ON DELETE CASCADE,
    version_code VARCHAR(100) NOT NULL,
    name TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dm_visual_catalog_effective_range_check
        CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT dm_visual_catalog_product_version_key
        UNIQUE (loai_hang_id, version_code)
);

CREATE INDEX IF NOT EXISTS idx_dm_visual_catalog_effective
    ON public.dm_visual_catalog(loai_hang_id, effective_from, effective_to);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dm_visual_catalog_open_version
    ON public.dm_visual_catalog(loai_hang_id)
    WHERE effective_to IS NULL;

ALTER TABLE public.dm_bo_phan
    ADD COLUMN IF NOT EXISTS visual_catalog_id INTEGER
        REFERENCES public.dm_visual_catalog(id);

CREATE INDEX IF NOT EXISTS idx_dm_bo_phan_visual_catalog
    ON public.dm_bo_phan(visual_catalog_id, sort_order, id);
