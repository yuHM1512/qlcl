BEGIN;

CREATE TABLE IF NOT EXISTS public.dm_qc_cum (
    id SERIAL PRIMARY KEY,
    loai_hang_id INTEGER NOT NULL REFERENCES public.dm_loai_hang(id) ON DELETE CASCADE,
    ten_cum TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (loai_hang_id, ten_cum)
);

CREATE INDEX IF NOT EXISTS idx_dm_qc_cum_loai_hang
    ON public.dm_qc_cum(loai_hang_id, sort_order, ten_cum);

CREATE INDEX IF NOT EXISTS idx_dm_qc_cum_active
    ON public.dm_qc_cum(is_active);

DO $$
DECLARE
    ao_vest_id INTEGER;
    quan_tay_id INTEGER;
BEGIN
    SELECT id INTO ao_vest_id
    FROM public.dm_loai_hang
    WHERE ten_loai = 'Áo vest'
    LIMIT 1;

    IF ao_vest_id IS NOT NULL THEN
        INSERT INTO public.dm_qc_cum (loai_hang_id, ten_cum, sort_order)
        VALUES
            (ao_vest_id, 'Cụm lót', 10),
            (ao_vest_id, 'Cụm thân', 20),
            (ao_vest_id, 'Cụm tay', 30),
            (ao_vest_id, 'Cụm hoàn chỉnh', 40),
            (ao_vest_id, 'Cụm hoàn thành', 50)
        ON CONFLICT (loai_hang_id, ten_cum) DO UPDATE
        SET sort_order = EXCLUDED.sort_order,
            is_active = TRUE;
    END IF;

    SELECT id INTO quan_tay_id
    FROM public.dm_loai_hang
    WHERE ten_loai = 'Quần tây'
    LIMIT 1;

    IF quan_tay_id IS NOT NULL THEN
        INSERT INTO public.dm_qc_cum (loai_hang_id, ten_cum, sort_order)
        VALUES
            (quan_tay_id, 'Cụm Inline', 10),
            (quan_tay_id, 'Cụm Endline', 20),
            (quan_tay_id, 'Cụm hoàn thành', 30)
        ON CONFLICT (loai_hang_id, ten_cum) DO UPDATE
        SET sort_order = EXCLUDED.sort_order,
            is_active = TRUE;
    END IF;
END $$;

COMMIT;
