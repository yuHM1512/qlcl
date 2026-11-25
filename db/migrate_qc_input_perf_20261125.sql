-- QC input perf (2026-11-25): quick-defect-combos joins prod_plan by loai_hang
CREATE INDEX IF NOT EXISTS idx_prod_plan_loai_hang ON public.prod_plan(loai_hang);
