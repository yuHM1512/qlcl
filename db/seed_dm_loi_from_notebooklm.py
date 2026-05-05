import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

# Helper to build severity json

def sev(*levels):
    return {level: True for level in levels}

DATA = [
    {"code": "C1", "description": "Sót chỉ / bụi bông", "severity": sev("Nặng", "Nhẹ")},
    {"code": "C2", "description": "Tẩy bẩn, ố vàng / dính dầu, dính keo", "severity": sev("Nặng", "Nhẹ")},
    {"code": "C3", "description": "Đường may rút chỉ, không ôm bờ", "severity": sev("Nặng")},
    {"code": "C4", "description": "Thừa / thiếu bọ, đường may, chi tiết", "severity": sev("Nặng")},
    {"code": "C5", "description": "Ủi không đạt", "severity": sev("Nặng", "Nhẹ")},
    {"code": "C6", "description": "Sai nguyên phụ liệu (về thành phần, xuất xứ hoặc loại)", "severity": sev("Nghiêm trọng", "Nặng")},
    {"code": "C7", "description": "Tréo ống", "severity": sev("Nặng")},
    {"code": "C8", "description": "Lộ chỉ, chỉ lược", "severity": sev("Nặng", "Nhẹ")},
    {"code": "C9", "description": "Bung xì / Kẹp / thấm thân", "severity": sev("Nặng")},
    {"code": "C10", "description": "Thiếu mũi / quá mũi", "severity": sev("Nặng", "Nhẹ")},
    {"code": "C11", "description": "Không lại mũi, lại mũi không trùng", "severity": sev("Nặng")},
    {"code": "C12", "description": "Cắt / may / sai quy cách", "severity": sev("Nặng")},
    {"code": "C13", "description": "Keo bị tràn, bị bong tróc", "severity": sev("Nặng")},
    {"code": "C14", "description": "Nút chưa quần chân / chồng hở / lỏng chặt", "severity": sev("Nặng")},
    {"code": "C15", "description": "Sụp mí", "severity": sev("Nặng")},
    {"code": "C16", "description": "Cắt / may sai vị trí", "severity": sev("Nặng")},
    {"code": "S1", "description": "Đứt chỉ, hở", "severity": sev("Nặng")},
    {"code": "S2", "description": "Le mép, nhốt vải", "severity": sev("Nặng", "Nhẹ")},
    {"code": "S3", "description": "Chúi / sole / lệch", "severity": sev("Nặng")},
    {"code": "S4", "description": "Can, diễu xấu", "severity": sev("Nặng", "Nhẹ")},
    {"code": "S5", "description": "Thụng, lún, móp", "severity": sev("Nặng", "Nhẹ")},
    {"code": "S6", "description": "Vặn, kẹp / nhíu", "severity": sev("Nặng")},
    {"code": "S7", "description": "Chồng, hở / gồng", "severity": sev("Nặng")},
    {"code": "S8", "description": "Xiên, nghiêng", "severity": sev("Nặng", "Nhẹ")},
    {"code": "S9", "description": "Tà bật, vểnh", "severity": sev("Nặng")},
    {"code": "S10", "description": "Tù góc, đầu ruồi", "severity": sev("Nặng")},
    {"code": "S11", "description": "Gãy, đá, ngửa, biến dạng", "severity": sev("Nặng")},
    {"code": "S12", "description": "Nhăn đùn / căng / giựt", "severity": sev("Nặng")},
    {"code": "S13", "description": "Thân bị đổ, chảy", "severity": sev("Nặng")},
    {"code": "S14", "description": "Phồng, dộp", "severity": sev("Nặng")},
    {"code": "F1", "description": "Lỗi vải / lủng vải", "severity": sev("Nghiêm trọng")},
    {"code": "F2", "description": "Vải loang màu, khác màu", "severity": sev("Nghiêm trọng")},
    {"code": "F3", "description": "Lỗi do in / ép / thêu (sai thông tin, mất nét, thừa/thiếu...)", "severity": sev("Nghiêm trọng", "Nặng")},
    {"code": "F4", "description": "Lỗi do nguyên phụ liệu", "severity": sev("Nghiêm trọng")},
    {"code": "F5", "description": "Nấm mốc / côn trùng", "severity": sev("Nghiêm trọng")},
    {"code": "F6", "description": "Lỗi thông số (đặc biệt là thông số quan trọng)", "severity": sev("Nghiêm trọng", "Nặng")},
    {"code": "F7", "description": "Lỗi gấp xếp", "severity": sev("Nặng")},
    {"code": "F8", "description": "Lỗi bao bì, đóng gói", "severity": sev("Nặng")},
    {"code": "F9", "description": "Lỗi do cắt", "severity": sev("Nghiêm trọng")},
    {"code": "F10", "description": "Có kim loại, phụ liệu hoặc vật sắc bén", "severity": sev("Nghiêm trọng")},
    {"code": "F11", "description": "Sai các yêu cầu về an toàn (đặc biệt hàng trẻ em)", "severity": sev("Nghiêm trọng")},
    {"code": "F12", "description": "Có hóa chất cấm, chất gây dị ứng", "severity": sev("Nghiêm trọng")},
    {"code": "M1", "description": "Đường may cong gãy, nhăn", "severity": sev("Nặng")},
    {"code": "M2", "description": "Bỏ mũi", "severity": sev("Nặng")},
    {"code": "M3", "description": "Mật độ chỉ không đều / lỏng chỉ, chặt chỉ", "severity": sev("Nặng", "Nhẹ")},
    {"code": "M4", "description": "Đường may cuốn bờ, tưa vải", "severity": sev("Nặng")},
    {"code": "M5", "description": "Khuy hoặc nút không đạt", "severity": sev("Nặng")},
    {"code": "M6", "description": "Gùi chỉ", "severity": sev("Nặng")},
    {"code": "M7", "description": "Lỗ kim, bể vải", "severity": sev("Nặng")},
]

# Expand ranges: T1-T8 (Nặng), T12-T14 (Nhẹ)
for i in range(1, 9):
    DATA.append({
        "code": f"T{i}",
        "description": "Các lỗi về Seam (sót chỉ, hụt, lệch, gấp nếp, xoắn, co rút, bong tróc...)",
        "severity": sev("Nặng"),
    })
for i in range(12, 15):
    DATA.append({
        "code": f"T{i}",
        "description": "Seam bị xếp ly, có dấu dừng máy",
        "severity": sev("Nhẹ"),
    })

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


def main():
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # Ensure column exists
            cur.execute(SQL_ADD_COLUMN)

            # Clear existing data in dm_mo_ta_loi and dm_ma_loi
            cur.execute("DELETE FROM public.dm_mo_ta_loi")
            cur.execute("DELETE FROM public.dm_ma_loi")

            nhom_id = ensure_group(cur)

            for item in DATA:
                cur.execute(
                    "INSERT INTO public.dm_ma_loi (nhom_loi_id, ten_ma) VALUES (%s, %s) RETURNING id",
                    (nhom_id, item["code"]),
                )
                ma_loi_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO public.dm_mo_ta_loi (ma_loi_id, ten_mo_ta, muc_do) VALUES (%s, %s, %s)",
                    (ma_loi_id, item["description"], psycopg2.extras.Json(item["severity"])),
                )
        conn.commit()
    print("Seeded dm_ma_loi & dm_mo_ta_loi from NotebookLM list.")


if __name__ == "__main__":
    main()
