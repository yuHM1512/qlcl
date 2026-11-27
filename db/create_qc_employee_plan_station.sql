-- Công đoạn QC được phân công theo từng MONo (đẩy từ app chuyền treo).
CREATE TABLE IF NOT EXISTS public.qc_employee_plan_station (
    don_vi     TEXT NOT NULL,
    mono       TEXT NOT NULL,
    ma_nv      TEXT NOT NULL,
    station    TEXT NOT NULL,
    synced_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (don_vi, mono, ma_nv, station)
);

CREATE INDEX IF NOT EXISTS ix_qc_employee_plan_station_ma_nv
    ON public.qc_employee_plan_station (ma_nv, don_vi);
