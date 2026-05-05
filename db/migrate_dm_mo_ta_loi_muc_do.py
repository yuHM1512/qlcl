import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Load .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

DATA = [
    {
        "code": "C1",
        "description": "Sót chỉ/bụi bông",
        "severity": {"Nặng": True, "Nhẹ": "Không thấy rõ (2-5mm)"},
    },
    {
        "code": "C2",
        "description": "Tẩy/bẩn/ố vàng/dính dầu, keo",
        "severity": {"Nặng": True, "Nhẹ": "Không thấy rõ / Lỗ số mặt trong"},
    },
    {"code": "C3", "description": "Đường may rút chỉ, không ôm", "severity": {"Nặng": True}},
    {"code": "C4", "description": "Thừa thiếu bo, đường may, chi tiết", "severity": {"Nặng": True}},
    {
        "code": "C5",
        "description": "Ủi không đạt",
        "severity": {"Nặng": "Mặt ngoài", "Nhẹ": "Mặt trong"},
    },
    {
        "code": "C6",
        "description": "Sai nguyên phụ liệu",
        "severity": {"Nặng": True, "Nghiêm trọng": "NPL về thành phần/xuất xứ"},
    },
    {"code": "C7", "description": "Tréo ống", "severity": {"Nặng": True}},
    {
        "code": "C8",
        "description": "Lỗ chỉ, chỉ lược",
        "severity": {"Nặng": "Mặt ngoài", "Nhẹ": "Mặt trong"},
    },
    {"code": "C9", "description": "Bung xì / kẹp / thấm thân", "severity": {"Nặng": True}},
    {
        "code": "C10",
        "description": "Thiếu mũi / quá mũi",
        "severity": {"Nặng": True, "Nhẹ": "Quá mũi 1 mũi"},
    },
    {
        "code": "C11",
        "description": "Không lại mũi, lại mũi không trùng",
        "severity": {"Nặng": True},
    },
    {"code": "S1", "description": "Đứt chỉ, hở", "severity": {"Nặng": True}},
    {
        "code": "S2",
        "description": "Lệ mép, nhốt vải",
        "severity": {"Nặng": "Mặt ngoài", "Nhẹ": "Mặt trong"},
    },
    {"code": "S3", "description": "Chúi / sole / lệch", "severity": {"Nặng": True}},
    {
        "code": "S4",
        "description": "Can, diễu xấu",
        "severity": {"Nặng": "Mặt ngoài", "Nhẹ": "Mặt trong"},
    },
    {
        "code": "S5",
        "description": "Thụng, lún, móp",
        "severity": {"Nặng": True, "Nhẹ": "Mặt trong"},
    },
    {"code": "S6", "description": "Vặn, kẹp/nhíu", "severity": {"Nặng": True}},
    {"code": "S7", "description": "Chồng, hở, gồng", "severity": {"Nặng": True}},
    {
        "code": "S8",
        "description": "Xiên, nghiêng",
        "severity": {"Nặng": True, "Nhẹ": "0.1-0.3cm"},
    },
    {"code": "S9", "description": "Tà bật, vểnh", "severity": {"Nặng": True}},
    {"code": "S10", "description": "Túi góc, đầu ruồi", "severity": {"Nặng": True}},
    {"code": "S11", "description": "Gãy, đá, ngửa, biến dạng", "severity": {"Nặng": True}},
    {
        "code": "F3",
        "description": "Lỗi do in / ép / thêu",
        "severity": {"Nghiêm trọng": "Sai thông tin hình in", "Nặng": True},
    },
    {"code": "T10", "description": "Keo tape lan ra ngoài", "severity": {"Nặng": True}},
]

SQL_ADD_COLUMN = """
ALTER TABLE public.dm_mo_ta_loi
    ADD COLUMN IF NOT EXISTS muc_do JSONB;
"""


def ensure_group(cur):
    cur.execute("SELECT id FROM public.dm_nhom_loi WHERE ten_nhom = %s", ("Chung",))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO public.dm_nhom_loi (ten_nhom) VALUES (%s) RETURNING id", ("Chung",))
    return cur.fetchone()[0]


def ensure_ma_loi(cur, code, nhom_id):
    cur.execute("SELECT id FROM public.dm_ma_loi WHERE ten_ma = %s", (code,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO public.dm_ma_loi (nhom_loi_id, ten_ma) VALUES (%s, %s) RETURNING id",
        (nhom_id, code),
    )
    return cur.fetchone()[0]


def upsert_mo_ta(cur, ma_loi_id, description, severity):
    cur.execute(
        "SELECT id FROM public.dm_mo_ta_loi WHERE ma_loi_id = %s AND ten_mo_ta = %s",
        (ma_loi_id, description),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE public.dm_mo_ta_loi SET muc_do = %s WHERE id = %s",
            (psycopg2.extras.Json(severity), row[0]),
        )
        return row[0]
    cur.execute(
        "INSERT INTO public.dm_mo_ta_loi (ma_loi_id, ten_mo_ta, muc_do) VALUES (%s, %s, %s) RETURNING id",
        (ma_loi_id, description, psycopg2.extras.Json(severity)),
    )
    return cur.fetchone()[0]


def main():
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_ADD_COLUMN)
            nhom_id = ensure_group(cur)
            for item in DATA:
                ma_loi_id = ensure_ma_loi(cur, item["code"], nhom_id)
                upsert_mo_ta(cur, ma_loi_id, item["description"], item["severity"])
        conn.commit()
    print("Migration applied: dm_mo_ta_loi.muc_do + seed data")


if __name__ == "__main__":
    main()
