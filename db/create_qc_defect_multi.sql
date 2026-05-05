CREATE TABLE IF NOT EXISTS public.qc_defect_multi (
    id SERIAL PRIMARY KEY,
    plan_id INT NOT NULL,
    date DATE NOT NULL,
    time TIME NOT NULL,
    bo_phan TEXT,
    chi_tiet TEXT,
    ma_loi TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qc_defect_multi_plan_date
ON public.qc_defect_multi (plan_id, date);
