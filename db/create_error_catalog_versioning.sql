-- Migration: version QC defect catalogs and seed QLCL-HDKT-8.9/BM3 revision 08
-- Encoding: UTF-8

BEGIN;

CREATE TABLE IF NOT EXISTS public.dm_defect_catalog (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source_file TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

INSERT INTO public.dm_defect_catalog (code, name, effective_from, effective_to, is_active, source_file)
VALUES ('legacy-before-2026-07-28', 'Bộ lỗi cũ trước QLCL-HDKT-8.9/BM3 lần 08', DATE '1900-01-01', DATE '2026-07-27', FALSE, NULL)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    effective_from = EXCLUDED.effective_from,
    effective_to = EXCLUDED.effective_to,
    is_active = EXCLUDED.is_active,
    source_file = EXCLUDED.source_file;

INSERT INTO public.dm_defect_catalog (code, name, effective_from, effective_to, is_active, source_file)
VALUES ('qlcl-hdkt-8.9-bm3-rev08', 'QLCL-HDKT-8.9/BM3 lần soát xét 08', DATE '2026-07-28', NULL, TRUE, '8.9 BM3.pdf')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    effective_from = EXCLUDED.effective_from,
    effective_to = EXCLUDED.effective_to,
    is_active = EXCLUDED.is_active,
    source_file = EXCLUDED.source_file;

ALTER TABLE public.dm_nhom_loi
    ADD COLUMN IF NOT EXISTS catalog_id INTEGER REFERENCES public.dm_defect_catalog(id);

UPDATE public.dm_nhom_loi
SET catalog_id = (SELECT id FROM public.dm_defect_catalog WHERE code = 'legacy-before-2026-07-28')
WHERE catalog_id IS NULL;

ALTER TABLE public.dm_nhom_loi
    ALTER COLUMN catalog_id SET NOT NULL;

ALTER TABLE public.dm_nhom_loi
    DROP CONSTRAINT IF EXISTS dm_nhom_loi_ten_nhom_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'dm_nhom_loi_catalog_id_ten_nhom_key'
          AND conrelid = 'public.dm_nhom_loi'::regclass
    ) THEN
        ALTER TABLE public.dm_nhom_loi
            ADD CONSTRAINT dm_nhom_loi_catalog_id_ten_nhom_key UNIQUE (catalog_id, ten_nhom);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_dm_nhom_loi_catalog_id ON public.dm_nhom_loi(catalog_id);

ALTER TABLE public.qc_defect
    ADD COLUMN IF NOT EXISTS defect_catalog_id INTEGER REFERENCES public.dm_defect_catalog(id),
    ADD COLUMN IF NOT EXISTS ma_loi_code_snapshot TEXT,
    ADD COLUMN IF NOT EXISTS mo_ta_loi_snapshot TEXT,
    ADD COLUMN IF NOT EXISTS nhom_loi_snapshot TEXT;

UPDATE public.qc_defect d
SET
    defect_catalog_id = COALESCE(
        d.defect_catalog_id,
        (
            SELECT nl.catalog_id
            FROM public.dm_ma_loi ml
            JOIN public.dm_nhom_loi nl ON nl.id = ml.nhom_loi_id
            WHERE ml.id = d.ma_loi_id
        )
    ),
    ma_loi_code_snapshot = COALESCE(
        d.ma_loi_code_snapshot,
        (SELECT ml.ten_ma FROM public.dm_ma_loi ml WHERE ml.id = d.ma_loi_id)
    ),
    mo_ta_loi_snapshot = COALESCE(
        d.mo_ta_loi_snapshot,
        (SELECT mt.ten_mo_ta FROM public.dm_mo_ta_loi mt WHERE mt.id = d.mo_ta_loi_id)
    ),
    nhom_loi_snapshot = COALESCE(
        d.nhom_loi_snapshot,
        (
            SELECT nl.ten_nhom
            FROM public.dm_ma_loi ml
            JOIN public.dm_nhom_loi nl ON nl.id = ml.nhom_loi_id
            WHERE ml.id = d.ma_loi_id
        )
    )
WHERE d.defect_catalog_id IS NULL
   OR d.ma_loi_code_snapshot IS NULL
   OR d.mo_ta_loi_snapshot IS NULL
   OR d.nhom_loi_snapshot IS NULL;

CREATE INDEX IF NOT EXISTS idx_qc_defect_catalog_id ON public.qc_defect(defect_catalog_id);

SELECT setval(
    pg_get_serial_sequence('public.dm_nhom_loi', 'id'),
    COALESCE((SELECT MAX(id) FROM public.dm_nhom_loi), 0) + 1,
    false
);

SELECT setval(
    pg_get_serial_sequence('public.dm_ma_loi', 'id'),
    COALESCE((SELECT MAX(id) FROM public.dm_ma_loi), 0) + 1,
    false
);

SELECT setval(
    pg_get_serial_sequence('public.dm_mo_ta_loi', 'id'),
    COALESCE((SELECT MAX(id) FROM public.dm_mo_ta_loi), 0) + 1,
    false
);

DO $$
DECLARE
    v_catalog_id INTEGER;
    v_group_id INTEGER;
    v_ma_id INTEGER;
    rec RECORD;
BEGIN
    SELECT id INTO v_catalog_id
    FROM public.dm_defect_catalog
    WHERE code = 'qlcl-hdkt-8.9-bm3-rev08';

    FOR rec IN
        SELECT *
        FROM (VALUES
            ('C', 'Lỗi do bất cẩn', 'C1', 'Sót chỉ/bụi bông', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C2', 'Tẩy/bẩn, ố vàng/dính dầu, dính keo', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C3', 'Đường may rút chỉ, không ôm bờ', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C4', 'Thừa/thiếu bọ, đường may, chi tiết', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C5', 'Ủi không đạt', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C6', 'Sai nguyên phụ liệu (về thành phần, xuất xứ hoặc loại)', '{"Nghiêm trọng": true, "Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C7', 'Tréo ống', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C8', 'Lộ chỉ, chỉ lược', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C9', 'Bung xì/Kẹp/thấm thân', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C10', 'Thiếu mũi/quá mũi', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C11', 'Không lại mũi, lại mũi không trùng', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C12', 'Cắt/may/sai qui cách', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C13', 'Keo bị tràn, bị bong tróc', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C14', 'Nút chưa quấn chân/chồng hở/lỏng chặt', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C15', 'Sụp mí', '{"Nặng": true}'::jsonb),
            ('C', 'Lỗi do bất cẩn', 'C16', 'Cắt/may sai vị trí', '{"Nặng": true}'::jsonb),

            ('E', 'Lỗi do kỹ thuật may', 'E1', 'Đứt chỉ, hở', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E2', 'Le mép, nhốt vải', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E3', 'Chúi/sole/lệch', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E4', 'Can, diễu xấu', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E5', 'Thụng, lún, móp', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E6', 'Vặn, kẹp/nhíu', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E7', 'Chồng, hở/gồng', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E8', 'Xiên, nghiêng', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E9', 'Tà bật, vểnh', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E10', 'Tù góc, đầu ruồi', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E11', 'Gãy, đá, ngửa, biến dạng', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E12', 'Nhăn đùn/căng/giựt', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E13', 'Thân bị đổ, chảy', '{"Nặng": true}'::jsonb),
            ('E', 'Lỗi do kỹ thuật may', 'E14', 'Phồng, dộp', '{"Nặng": true}'::jsonb),

            ('M', 'Lỗi do máy móc', 'M1', 'Đường may cong gãy, nhăn', '{"Nặng": true}'::jsonb),
            ('M', 'Lỗi do máy móc', 'M2', 'Bỏ mũi', '{"Nặng": true}'::jsonb),
            ('M', 'Lỗi do máy móc', 'M3', 'Mật độ chỉ không đều/Lỏng chỉ, chặt chỉ', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('M', 'Lỗi do máy móc', 'M4', 'Đường may cuốn bờ, tưa vải', '{"Nặng": true}'::jsonb),
            ('M', 'Lỗi do máy móc', 'M5', 'Khuy hoặc nút không đạt', '{"Nặng": true}'::jsonb),
            ('M', 'Lỗi do máy móc', 'M6', 'Gùi chỉ', '{"Nặng": true}'::jsonb),

            ('O', 'Lỗi vải và lỗi khác', 'O1', 'Lỗi vải/lủng vải', '{"Nghiêm trọng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O2', 'Vải loang màu/khác màu', '{"Nặng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O3', 'Lỗi do in/ép/thêu (sai thông tin, mất chữ/mất nét, thừa/thiếu thông tin...)', '{"Nghiêm trọng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O4', 'Lỗi do nguyên phụ liệu', '{"Nặng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O5', 'Nấm mốc/côn trùng', '{"Nghiêm trọng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O6', 'Lỗi thông số (đặc biệt thông số quan trọng)', '{"Nghiêm trọng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O7', 'Lỗi gấp xếp', '{"Nặng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O8', 'Lỗi bao bì, đóng gói', '{"Nặng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O9', 'Lỗi do cắt', '{"Nặng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O10', 'Kim loại; phụ liệu/vật sắc bén', '{"Nghiêm trọng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O11', 'Sai các yêu cầu về an toàn đối với sản phẩm dành cho trẻ em', '{"Nghiêm trọng": true}'::jsonb),
            ('O', 'Lỗi vải và lỗi khác', 'O12', 'Có hóa chất cấm, chất gây dị ứng', '{"Nghiêm trọng": true}'::jsonb),

            ('S', 'Lỗi ép seam (trạm may)', 'S1', 'Nếp gấp', '{"Nặng": true}'::jsonb),
            ('S', 'Lỗi ép seam (trạm may)', 'S2', 'Chỉ thừa', '{"Nặng": true}'::jsonb),
            ('S', 'Lỗi ép seam (trạm may)', 'S3', 'Đường may không đều', '{"Nhẹ": true}'::jsonb),
            ('S', 'Lỗi ép seam (trạm may)', 'S4', 'Bờ đường may sai', '{"Nặng": true}'::jsonb),

            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D1', 'Chỉ thừa trong đường ép', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D2', 'Ép seam bị hụt', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D3', 'Đường ép bị lệch tâm', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D4', 'Gấp/xếp ly đường ép', '{"Nặng": true, "Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D5', 'Đường may bị vặn', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D6', 'Nhăn nhíu đường ép', '{"Nặng": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D7', 'Bong bóng khí trong đường ép', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D8', 'Bong seam', '{"Nặng": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D9', 'Đường ép cấn bóng/cháy rách', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D10', 'Lộ điểm dừng đường ép', '{"Nặng": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D11', 'Gấp đầu cuối cắt seam', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D12', 'Vết hằn mép seam', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D13', 'Trầy mặt tráng su do vật sắc nhọn/sửa lỗi ép seam', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D14', 'Ép lên mặt phải vải', '{"Nhẹ": true}'::jsonb),
            ('D', 'Lỗi ép seam (tại trạm ép seam)', 'D15', 'Seam 3L: keo tràn 2 bên mép seam nhiều và không đều', '{"Nhẹ": true}'::jsonb),

            ('L', 'Lỗi ép seam (test nước)', 'L1', 'Rò rỉ mép đường ép', '{"Nhẹ": true}'::jsonb),
            ('L', 'Lỗi ép seam (test nước)', 'L2', 'Rò rỉ trong đường ép seam', '{"Nặng": true}'::jsonb),
            ('L', 'Lỗi ép seam (test nước)', 'L3', 'Rò rỉ ngã 3,4', '{"Nặng": true}'::jsonb),
            ('L', 'Lỗi ép seam (test nước)', 'L4', 'Rò rỉ do bong keo', '{"Nặng": true}'::jsonb),
            ('F', 'Lỗi ép seam (test nước)', 'F1', 'Rò rỉ < 3 GIỌT', '{"Nặng": true}'::jsonb),
            ('F', 'Lỗi ép seam (test nước)', 'F2', 'Rò rỉ >= 3 GIỌT', '{"Nhẹ": true}'::jsonb),
            ('F', 'Lỗi ép seam (test nước)', 'F3', 'Rò rỉ trên đường nếp gấp vải', '{"Nhẹ": true}'::jsonb),
            ('F', 'Lỗi ép seam (test nước)', 'F4', 'Xì nước dạng tia/chảy nước lớn trên vải', '{"Nhẹ": true}'::jsonb)
        ) AS seed(prefix, ten_nhom, ten_ma, ten_mo_ta, muc_do)
        ORDER BY prefix, ten_ma
    LOOP
        INSERT INTO public.dm_nhom_loi (catalog_id, ten_nhom)
        VALUES (v_catalog_id, rec.ten_nhom)
        ON CONFLICT (catalog_id, ten_nhom) DO NOTHING;

        SELECT id INTO v_group_id
        FROM public.dm_nhom_loi
        WHERE catalog_id = v_catalog_id
          AND ten_nhom = rec.ten_nhom;

        INSERT INTO public.dm_ma_loi (nhom_loi_id, ten_ma)
        VALUES (v_group_id, rec.ten_ma)
        ON CONFLICT (nhom_loi_id, ten_ma) DO NOTHING;

        SELECT id INTO v_ma_id
        FROM public.dm_ma_loi
        WHERE nhom_loi_id = v_group_id
          AND ten_ma = rec.ten_ma;

        INSERT INTO public.dm_mo_ta_loi (ma_loi_id, ten_mo_ta, muc_do)
        VALUES (v_ma_id, rec.ten_mo_ta, rec.muc_do)
        ON CONFLICT (ma_loi_id, ten_mo_ta) DO UPDATE SET
            muc_do = EXCLUDED.muc_do;
    END LOOP;
END $$;

COMMIT;
