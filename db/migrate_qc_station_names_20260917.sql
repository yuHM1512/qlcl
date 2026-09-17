-- Rename the legacy QC stations consistently across employee scope and QC history.
BEGIN;

UPDATE public.quality_employees employee
SET station = mapped.station
FROM (
    SELECT ma_nv, jsonb_agg(station_name ORDER BY first_position) AS station
    FROM (
        SELECT ma_nv, station_name, MIN(position) AS first_position
        FROM (
            SELECT employee.ma_nv,
                   item.position,
                   CASE BTRIM(item.value)
                       WHEN 'Trạm cuối chuyền' THEN 'QC kiểm thành phẩm'
                       WHEN 'Trạm trước seam' THEN 'QC trước seam'
                       WHEN 'Trạm sau seam' THEN 'QC sau seam'
                       ELSE item.value
                   END AS station_name
            FROM public.quality_employees employee
            CROSS JOIN LATERAL jsonb_array_elements_text(
                COALESCE(employee.station, '[]'::jsonb)
            ) WITH ORDINALITY AS item(value, position)
        ) values_with_new_names
        GROUP BY ma_nv, station_name
    ) unique_names
    GROUP BY ma_nv
) mapped
WHERE employee.ma_nv = mapped.ma_nv
  AND employee.station IS DISTINCT FROM mapped.station;

UPDATE public.qc_output_sp_log
SET station = CASE BTRIM(station)
    WHEN 'Trạm cuối chuyền' THEN 'QC kiểm thành phẩm'
    WHEN 'Trạm trước seam' THEN 'QC trước seam'
    WHEN 'Trạm sau seam' THEN 'QC sau seam'
END
WHERE BTRIM(station) IN ('Trạm cuối chuyền', 'Trạm trước seam', 'Trạm sau seam');

UPDATE public.qc_error_log_sp
SET station = CASE BTRIM(station)
    WHEN 'Trạm cuối chuyền' THEN 'QC kiểm thành phẩm'
    WHEN 'Trạm trước seam' THEN 'QC trước seam'
    WHEN 'Trạm sau seam' THEN 'QC sau seam'
END
WHERE BTRIM(station) IN ('Trạm cuối chuyền', 'Trạm trước seam', 'Trạm sau seam');

UPDATE public.qc_defect_multi
SET station = CASE BTRIM(station)
    WHEN 'Trạm cuối chuyền' THEN 'QC kiểm thành phẩm'
    WHEN 'Trạm trước seam' THEN 'QC trước seam'
    WHEN 'Trạm sau seam' THEN 'QC sau seam'
END
WHERE BTRIM(station) IN ('Trạm cuối chuyền', 'Trạm trước seam', 'Trạm sau seam');

UPDATE public.qc_error_dps
SET station = CASE BTRIM(station)
    WHEN 'Trạm cuối chuyền' THEN 'QC kiểm thành phẩm'
    WHEN 'Trạm trước seam' THEN 'QC trước seam'
    WHEN 'Trạm sau seam' THEN 'QC sau seam'
END
WHERE BTRIM(station) IN ('Trạm cuối chuyền', 'Trạm trước seam', 'Trạm sau seam');

COMMIT;
