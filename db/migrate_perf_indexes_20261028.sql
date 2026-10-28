-- Performance indexes for QC input endpoints (2026-10-28)

-- qc_defect: cover pos-summary serious/mass queries (JOIN on error_log_sp_id + GROUP BY bo_phan_id, chi_tiet_id, ma_loi_id)
CREATE INDEX IF NOT EXISTS idx_qc_defect_log_parts
    ON public.qc_defect(error_log_sp_id, bo_phan_id, chi_tiet_id, ma_loi_id);

-- qc_defect: cover quick-defect-combos-today (mo_ta_loi_id in WHERE + GROUP BY)
CREATE INDEX IF NOT EXISTS idx_qc_defect_combo
    ON public.qc_defect(error_log_sp_id, bo_phan_id, chi_tiet_id, ma_loi_id, mo_ta_loi_id);

-- qc_error_log_sp: compound for plan+date+station lookup (used in every qc-input endpoint)
CREATE INDEX IF NOT EXISTS idx_qc_error_log_sp_plan_date_station
    ON public.qc_error_log_sp(plan_id, date, station);

-- qc_output_sp_log: compound for plan+date+station (pos-summary output buckets)
CREATE INDEX IF NOT EXISTS idx_qc_output_sp_log_plan_date_station
    ON public.qc_output_sp_log(plan_id, date, station);

-- qc_error_dps: compound for plan+date+station (hdkp map query)
CREATE INDEX IF NOT EXISTS idx_qc_error_dps_plan_date_station
    ON public.qc_error_dps(plan_id, date, station);

-- qc_defect_multi: compound for plan+date+station (multi risk query)
CREATE INDEX IF NOT EXISTS idx_qc_defect_multi_plan_date_station
    ON public.qc_defect_multi(plan_id, date, station);

-- prod_plan: compound for active plan filtering (is_active + is_finished + ngay_rc)
CREATE INDEX IF NOT EXISTS idx_prod_plan_active_finished
    ON public.prod_plan(is_finished, ngay_rc DESC) WHERE COALESCE(is_active, TRUE) = TRUE;
