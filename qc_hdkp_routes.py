"""HĐKP endline của QC (form, lưu, xuất PDF).

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
from datetime import date, datetime
from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import RedirectResponse
from typing import Dict

from app_core import core

router = APIRouter()


@router.get("/api/qc/hdkp/{dps_id}")
def api_get_qc_hdkp(dps_id: int = Path(...)):
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM public.qc_hdkp_mota WHERE qc_error_dps_id = %s", (dps_id,))
            mota = cur.fetchone()
            cur.execute(
                "SELECT * FROM public.qc_hdkp_kehoach WHERE qc_error_dps_id = %s ORDER BY section, thu_tu",
                (dps_id,),
            )
            kehoach = cur.fetchall()
            cur.execute(
                "SELECT * FROM public.qc_hdkp_chitiet WHERE qc_error_dps_id = %s ORDER BY thu_tu",
                (dps_id,),
            )
            chitiet = cur.fetchall()

    return {
        "mota": dict(mota) if mota else None,
        "kehoach": [dict(r) for r in kehoach],
        "chitiet": [dict(r) for r in chitiet],
    }


@router.get("/hdkp-form-endline/{dps_id}")
def hdkp_form_endline_page(dps_id: int = Path(...), request: Request = None):
    ma_nv = request.cookies.get("ma_nv") if request else None
    if not ma_nv:
        return RedirectResponse(url="/login", status_code=303)

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT dps.id, dps.plan_id, dps.date, dps.time_bucket, dps.loai_loi, dps.ma_loi, dps.vi_tri
                FROM public.qc_error_dps dps
                WHERE dps.id = %s
                """,
                (dps_id,),
            )
            dps_row = cur.fetchone()
            if not dps_row:
                raise HTTPException(status_code=404, detail="Khong tim thay DPS")

    return core.templates.TemplateResponse("hdkp_form_endline.html", {
        "request": request,
        "dps": dict(dps_row),
        "dps_id": dps_id,
    })


@router.post("/api/qc/hdkp/{dps_id}")
async def api_save_qc_hdkp(dps_id: int = Path(...), request: Request = None):
    ma_nv = request.cookies.get("ma_nv")
    if not ma_nv:
        raise HTTPException(status_code=401, detail="Chua dang nhap")

    payload = await request.json()

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, date FROM public.qc_error_dps WHERE id = %s",
                (dps_id,),
            )
            dps_row = cur.fetchone()
            if not dps_row:
                raise HTTPException(status_code=404, detail="Khong tim thay DPS")

            mota_data = payload.get('mota', {})
            cur.execute(
                """
                INSERT INTO public.qc_hdkp_mota (
                    qc_error_dps_id, vd_what, vd_when, vd_who, vd_where,
                    vd_how, vd_before, vd_importance, vd_image
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (qc_error_dps_id) DO UPDATE SET
                    vd_what = EXCLUDED.vd_what,
                    vd_when = EXCLUDED.vd_when,
                    vd_who = EXCLUDED.vd_who,
                    vd_where = EXCLUDED.vd_where,
                    vd_how = EXCLUDED.vd_how,
                    vd_before = EXCLUDED.vd_before,
                    vd_importance = EXCLUDED.vd_importance,
                    vd_image = EXCLUDED.vd_image,
                    updated_at = NOW()
                """,
                (
                    dps_id,
                    mota_data.get('vd_what'),
                    mota_data.get('vd_when'),
                    mota_data.get('vd_who'),
                    mota_data.get('vd_where'),
                    mota_data.get('vd_how'),
                    mota_data.get('vd_before'),
                    mota_data.get('vd_importance'),
                    mota_data.get('vd_image'),
                ),
            )

            cur.execute("DELETE FROM public.qc_hdkp_kehoach WHERE qc_error_dps_id = %s", (dps_id,))
            kehoach_list = payload.get('kehoach', [])
            for idx, item in enumerate(kehoach_list, 1):
                cur.execute(
                    """
                    INSERT INTO public.qc_hdkp_kehoach (
                        qc_error_dps_id, section, root_cause, hdkp_tuc_thoi, hd_phong_ngua,
                        tg_theo_doi, trach_nhiem, tg_thuc_hien, thu_tu
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        dps_id,
                        item.get('section'),
                        item.get('root_cause'),
                        item.get('hdkp_tuc_thoi'),
                        item.get('hd_phong_ngua'),
                        item.get('tg_theo_doi'),
                        item.get('trach_nhiem'),
                        item.get('tg_thuc_hien'),
                        idx,
                    ),
                )

            cur.execute("DELETE FROM public.qc_hdkp_chitiet WHERE qc_error_dps_id = %s", (dps_id,))
            chitiet_list = payload.get('chitiet', [])
            for idx, item in enumerate(chitiet_list, 1):
                ngay_bat_dau = date.fromisoformat(item['ngay_bat_dau']) if item.get('ngay_bat_dau') else None
                ngay_hoan_thanh = date.fromisoformat(item['ngay_hoan_thanh']) if item.get('ngay_hoan_thanh') else None
                cur.execute(
                    """
                    INSERT INTO public.qc_hdkp_chitiet (
                        qc_error_dps_id, cong_viec, trach_nhiem, ngay_bat_dau, ngay_hoan_thanh,
                        giam_sat, ket_qua, ket_luan, thu_tu
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        dps_id,
                        item.get('cong_viec'),
                        item.get('trach_nhiem'),
                        ngay_bat_dau,
                        ngay_hoan_thanh,
                        item.get('giam_sat'),
                        item.get('ket_qua'),
                        item.get('ket_luan'),
                        idx,
                    ),
                )

            conn.commit()

            pdf_url = None
            try:
                hdkp_data = prepare_qc_hdkp_data_for_pdf(dps_id, dps_row)
                pdf_url = core.create_hdkp_pdf(dps_id, hdkp_data)
                cur.execute(
                    "UPDATE public.qc_error_dps SET hdkp_pdf = %s WHERE id = %s",
                    (pdf_url, dps_id),
                )
                conn.commit()
            except Exception as e:
                core.logger.error(f"Loi khi tao PDF HDKP QC dps_id={dps_id}: {str(e)}", exc_info=True)

    return {"status": "ok", "id": dps_id, "pdf_url": pdf_url}


def prepare_qc_hdkp_data_for_pdf(dps_id: int, dps_row: Dict) -> Dict:
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM public.qc_hdkp_mota WHERE qc_error_dps_id = %s", (dps_id,))
            mota = cur.fetchone()

            cur.execute(
                "SELECT * FROM public.qc_hdkp_kehoach WHERE qc_error_dps_id = %s ORDER BY section, thu_tu",
                (dps_id,),
            )
            kehoach_rows = cur.fetchall()

            cur.execute(
                "SELECT * FROM public.qc_hdkp_chitiet WHERE qc_error_dps_id = %s ORDER BY thu_tu",
                (dps_id,),
            )
            chitiet_rows = cur.fetchall()

    created_at_formatted = ''
    if mota and mota.get('created_at'):
        try:
            created_at = mota.get('created_at')
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if isinstance(created_at, datetime):
                created_at_formatted = created_at.strftime('%d/%m/%Y')
            elif isinstance(created_at, date):
                created_at_formatted = created_at.strftime('%d/%m/%Y')
        except Exception as e:
            core.logger.warning(f"Khong the format created_at QC HDKP: {e}")
            created_at_formatted = ''

    data = {
        'ma_nv': '',
        'ngay_ghi_nhan': str(dps_row.get('date', '')),
        'created_at': created_at_formatted,
        'ho_ten': '',
    }

    if mota:
        data.update({
            'vd_what': mota.get('vd_what', ''),
            'vd_when': mota.get('vd_when', ''),
            'vd_who': mota.get('vd_who', ''),
            'vd_where': mota.get('vd_where', ''),
            'vd_how': mota.get('vd_how', ''),
            'vd_before': mota.get('vd_before', ''),
            'vd_importance': mota.get('vd_importance', ''),
            'vd_image': mota.get('vd_image', ''),
        })

    section_a_items = [r for r in kehoach_rows if r.get('section') == 'A']
    section_b_items = [r for r in kehoach_rows if r.get('section') == 'B']

    for idx, item in enumerate(section_a_items, start=1):
        data.update({
            f'a_root_cause_{idx}': item.get('root_cause', ''),
            f'a_hdkp_tuc_thoi_{idx}': item.get('hdkp_tuc_thoi', ''),
            f'a_hd_phong_ngua_{idx}': item.get('hd_phong_ngua', ''),
            f'a_tg_theo_doi_{idx}': item.get('tg_theo_doi', ''),
            f'a_trach_nhiem_{idx}': item.get('trach_nhiem', ''),
            f'a_tg_thuc_hien_{idx}': item.get('tg_thuc_hien', ''),
        })

    for idx, item in enumerate(section_b_items, start=1):
        data.update({
            f'b_root_cause_{idx}': item.get('root_cause', ''),
            f'b_hdkp_tuc_thoi_{idx}': item.get('hdkp_tuc_thoi', ''),
            f'b_hd_phong_ngua_{idx}': item.get('hd_phong_ngua', ''),
            f'b_tg_theo_doi_{idx}': item.get('tg_theo_doi', ''),
            f'b_trach_nhiem_{idx}': item.get('trach_nhiem', ''),
            f'b_tg_thuc_hien_{idx}': item.get('tg_thuc_hien', ''),
        })

    for idx, item in enumerate(chitiet_rows, start=1):
        ket_qua = (item.get('ket_qua') or '').strip()
        ket_qua_dat = ''
        ket_qua_khong_dat = ''
        if ket_qua == 'Đạt':
            ket_qua_dat = 'x'
        elif ket_qua == 'Không đạt':
            ket_qua_khong_dat = 'x'

        data.update({
            f'stt_{idx}': str(idx),
            f'cong_viec_{idx}': item.get('cong_viec', ''),
            f'trach_nhiem_{idx}': item.get('trach_nhiem', ''),
            f'ngay_bat_dau_{idx}': str(item.get('ngay_bat_dau', '')) if item.get('ngay_bat_dau') else '',
            f'ngay_hoan_thanh_{idx}': str(item.get('ngay_hoan_thanh', '')) if item.get('ngay_hoan_thanh') else '',
            f'giam_sat_{idx}': item.get('giam_sat', ''),
            f'ket_qua_dat_{idx}': ket_qua_dat,
            f'ket_qua_khong_dat_{idx}': ket_qua_khong_dat,
            f'ket_luan_{idx}': item.get('ket_luan', ''),
        })

    return data
