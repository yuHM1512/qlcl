"""Danh mục (/api/dm/*) và visual picker.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import re
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Any, Dict, List, Optional

from app_core import core

router = APIRouter()


# --- Hierarchical QC Error Reporting ---

@router.get("/api/dm/loai-hang")
def api_dm_loai_hang():
    """Lấy danh sách Loại hàng."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT lh.id, lh.ten_loai, lh.id_type, tgt.type AS type_name, tgt.target_percent
                FROM public.dm_loai_hang lh
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                ORDER BY lh.ten_loai
            """)
            return {"rows": cur.fetchall()}

@router.post("/api/dm/loai-hang", dependencies=[Depends(core.require_qa_admin_api_user)])
async def api_dm_loai_hang_create(request: Request):
    body = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            id_type = body.get("id_type")
            if id_type is None and body.get("type"):
                cur.execute("SELECT id_type FROM public.dm_loai_hang_target WHERE type = %s", (body["type"],))
                row = cur.fetchone()
                id_type = row[0] if row else None

            if id_type is None:
                raise HTTPException(status_code=400, detail="Thiếu phân loại (id_type) hơp lệ")

            cur.execute(
                "INSERT INTO public.dm_loai_hang (ten_loai, id_type) VALUES (%s, %s) RETURNING id",
                (body["ten_loai"], id_type)
            )
            new_id = cur.fetchone()[0]
            conn.commit()
    return {"id": new_id}

@router.delete("/api/dm/loai-hang/{id}", dependencies=[Depends(core.require_qa_admin_api_user)])
def api_dm_loai_hang_delete(id: int):
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.dm_loai_hang WHERE id = %s", (id,))
            conn.commit()
    return {"status": "ok"}

@router.get("/api/dm/loai-hang-target")
def api_dm_loai_hang_target():
    """Lấy danh sách phân loại loại hàng và target."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id_type, type, target_percent
                FROM public.dm_loai_hang_target
                ORDER BY id_type
            """)
            return {"rows": cur.fetchall()}

@router.get("/api/dm/bo-phan")
def api_dm_bo_phan(
    loai_hang_id: int = Query(...),
    as_of: Optional[date] = Query(None, alias="date"),
):
    """Lấy Bộ phận thuộc phiên bản visual có hiệu lực tại ngày báo cáo."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            catalog, has_versions = core.get_effective_visual_catalog(
                cur, loai_hang_id, as_of or date.today()
            )
            if catalog:
                cur.execute(
                    """
                    SELECT id, ten_bo_phan
                    FROM public.dm_bo_phan
                    WHERE loai_hang_id = %s AND visual_catalog_id = %s
                    ORDER BY ten_bo_phan, id
                    """,
                    (loai_hang_id, catalog["id"]),
                )
            elif has_versions:
                return {"rows": [], "visual_catalog": None}
            else:
                cur.execute(
                    """
                    SELECT id, ten_bo_phan
                    FROM public.dm_bo_phan
                    WHERE loai_hang_id = %s AND visual_catalog_id IS NULL
                    ORDER BY ten_bo_phan, id
                    """,
                    (loai_hang_id,),
                )
            return {"rows": cur.fetchall(), "visual_catalog": catalog}

@router.get("/api/dm/qc-cum")
def api_dm_qc_cum(
    loai_hang_id: int = Query(...),
    active_only: bool = Query(True),
):
    """Lấy danh sách cụm QC theo loại hàng."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            clauses = ["loai_hang_id = %s"]
            params: List[Any] = [loai_hang_id]
            if active_only:
                clauses.append("is_active = TRUE")
            cur.execute(
                f"""
                SELECT id, loai_hang_id, ten_cum, sort_order, is_active
                FROM public.dm_qc_cum
                WHERE {" AND ".join(clauses)}
                ORDER BY sort_order, ten_cum
                """,
                tuple(params),
            )
            return {"rows": cur.fetchall()}

@router.post("/api/dm/bo-phan", dependencies=[Depends(core.require_qa_admin_api_user)])
async def api_dm_bo_phan_create(request: Request):
    body = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            loai_hang_id = int(body["loai_hang_id"])
            catalog, _ = core.get_effective_visual_catalog(cur, loai_hang_id, date.today())
            cur.execute(
                """
                INSERT INTO public.dm_bo_phan
                    (loai_hang_id, ten_bo_phan, visual_catalog_id)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (loai_hang_id, body["ten_bo_phan"], catalog["id"] if catalog else None),
            )
            new_id = cur.fetchone()["id"]
            conn.commit()
    return {"id": new_id}

@router.delete("/api/dm/bo-phan/{id}", dependencies=[Depends(core.require_qa_admin_api_user)])
def api_dm_bo_phan_delete(id: int):
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.dm_bo_phan WHERE id = %s", (id,))
            conn.commit()
    return {"status": "ok"}

@router.get("/api/dm/chi-tiet")
def api_dm_chi_tiet(bo_phan_id: int = Query(...)):
    """Lấy danh sách Chi tiết theo bo_phan_id."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, ten_chi_tiet FROM public.dm_chi_tiet WHERE bo_phan_id = %s ORDER BY ten_chi_tiet", (bo_phan_id,))
            return {"rows": cur.fetchall()}

@router.post("/api/dm/chi-tiet", dependencies=[Depends(core.require_qa_admin_api_user)])
async def api_dm_chi_tiet_create(request: Request):
    body = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO public.dm_chi_tiet (bo_phan_id, ten_chi_tiet) VALUES (%s, %s) RETURNING id", 
                        (body["bo_phan_id"], body["ten_chi_tiet"]))
            new_id = cur.fetchone()[0]
            conn.commit()
    return {"id": new_id}

@router.delete("/api/dm/chi-tiet/{id}", dependencies=[Depends(core.require_qa_admin_api_user)])
def api_dm_chi_tiet_delete(id: int):
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.dm_chi_tiet WHERE id = %s", (id,))
            conn.commit()
    return {"status": "ok"}


# Visual position picker: returns nhóm -> khối (image) -> hotspots (codes).
# Used by /qc-input for loại hàng that has been "số hoá" (e.g. Áo vest).
NHOM_LABELS = {"chinh": "Chính", "lot": "Lót", "nhan_dien": "Nhận diện",
               "lop_1": "Lớp 1", "lop_2": "Lớp 2", "lop_3": "Lớp 3"}

@router.get("/api/qc/visual-picker")
def api_qc_visual_picker(
    loai_hang_id: int = Query(...),
    as_of: Optional[date] = Query(None, alias="date"),
):
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            catalog, has_versions = core.get_effective_visual_catalog(
                cur, loai_hang_id, as_of or date.today()
            )
            if catalog:
                catalog_clause = "bp.visual_catalog_id = %s"
                params = (loai_hang_id, catalog["id"])
            elif has_versions:
                return {"has_visual_picker": False, "nhoms": [], "visual_catalog": None}
            else:
                catalog_clause = "bp.visual_catalog_id IS NULL"
                params = (loai_hang_id,)
            cur.execute(
                f"""
                SELECT bp.id AS bo_phan_id, bp.ten_bo_phan, bp.nhom, bp.image_png, bp.image_svg, bp.sort_order,
                       ct.id AS chi_tiet_id, ct.ma_vi_tri, ct.ten_chi_tiet,
                       ct.x_pct, ct.y_pct, ct.w_pct, ct.h_pct, ct.rotation
                FROM public.dm_bo_phan bp
                LEFT JOIN public.dm_chi_tiet ct ON ct.bo_phan_id = bp.id
                WHERE bp.loai_hang_id = %s AND {catalog_clause}
                ORDER BY bp.sort_order, bp.id, ct.ma_vi_tri NULLS LAST, ct.id
                """,
                params,
            )
            rows = cur.fetchall()

    has_picker = any(r["image_png"] and r["nhom"] for r in rows)
    if not has_picker:
        return {"has_visual_picker": False, "nhoms": [], "visual_catalog": catalog}

    by_nhom: Dict[str, Dict[int, dict]] = {}
    for r in rows:
        # Legacy catalog blocks can coexist with digitized blocks for a product.
        # They have no image/coordinate frame and must not become empty picker cards.
        if not r["image_png"] or not r["nhom"]:
            continue
        nhom = r["nhom"] or "khac"
        bp_id = r["bo_phan_id"]
        if nhom not in by_nhom:
            by_nhom[nhom] = {}
        if bp_id not in by_nhom[nhom]:
            by_nhom[nhom][bp_id] = {
                "bo_phan_id": bp_id,
                "ten_khoi": r["ten_bo_phan"],
                "image_png": f"/api/images/{r['image_png']}" if r["image_png"] else None,
                "image_svg": f"/api/images/{r['image_svg']}" if r["image_svg"] else None,
                "sort_order": r["sort_order"],
                "hotspots": [],
            }
        if r["chi_tiet_id"] is not None:
            by_nhom[nhom][bp_id]["hotspots"].append({
                "chi_tiet_id": r["chi_tiet_id"],
                "ma_vi_tri": r["ma_vi_tri"],
                "label": r["ten_chi_tiet"],
                "x_pct": float(r["x_pct"]) if r["x_pct"] is not None else None,
                "y_pct": float(r["y_pct"]) if r["y_pct"] is not None else None,
                "w_pct": float(r["w_pct"]) if r["w_pct"] is not None else None,
                "h_pct": float(r["h_pct"]) if r["h_pct"] is not None else None,
                "rotation": float(r["rotation"]) if r["rotation"] is not None else 0.0,
            })

    nhom_order = ["chinh", "lot", "nhan_dien", "lop_1", "lop_2", "lop_3"]
    nhoms = []
    for key in nhom_order:
        if key not in by_nhom:
            continue
        khoi_list = sorted(by_nhom[key].values(), key=lambda x: (x["sort_order"], x["bo_phan_id"]))
        nhoms.append({"nhom": key, "label": NHOM_LABELS.get(key, key), "khoi": khoi_list})
    # Any other nhom (e.g. NULL) goes last
    for key, bps in by_nhom.items():
        if key in nhom_order:
            continue
        khoi_list = sorted(bps.values(), key=lambda x: (x["sort_order"], x["bo_phan_id"]))
        nhoms.append({"nhom": key, "label": NHOM_LABELS.get(key, key.title()), "khoi": khoi_list})

    # PDF-sourced visuals print the position codes on the image itself, so the UI
    # overlays transparent tap areas instead of drawing its own code badges.
    labels_in_image = bool(catalog and str(catalog.get("source_file") or "").lower().endswith(".pdf"))
    return {"has_visual_picker": True, "nhoms": nhoms, "visual_catalog": catalog,
            "labels_in_image": labels_in_image}


@router.get("/api/qc/visual-picker/loai-hang-list")
def api_qc_visual_picker_loai_hang_list():
    """Liệt kê loại hàng có visual picker để hiển thị trong selector admin."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT lh.id, lh.ten_loai
                FROM public.dm_loai_hang lh
                JOIN public.dm_bo_phan bp ON bp.loai_hang_id = lh.id
                WHERE bp.image_png IS NOT NULL AND bp.nhom IS NOT NULL
                ORDER BY lh.ten_loai
                """
            )
            return {"rows": cur.fetchall()}


@router.patch("/api/qc/visual-picker/hotspots-batch")
async def api_qc_visual_picker_update_hotspots(
    request: Request,
    _user: Dict = Depends(core.require_qa_admin_api_user),
):
    """Bulk update x_pct/y_pct cho 1 nhóm chi_tiet (1 khoi). Chỉ QA_ADMIN.
    Body: {"items": [{"chi_tiet_id": int, "x_pct": float, "y_pct": float}, ...]}
    """
    body = await request.json()
    items = body.get("items") or []
    if not items:
        return {"status": "ok", "updated": 0}
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            for it in items:
                cid = int(it["chi_tiet_id"])
                x = max(0.0, min(1.0, float(it["x_pct"])))
                y = max(0.0, min(1.0, float(it["y_pct"])))
                cur.execute(
                    "UPDATE public.dm_chi_tiet SET x_pct = %s, y_pct = %s WHERE id = %s",
                    (x, y, cid),
                )
            conn.commit()
    return {"status": "ok", "updated": len(items)}


@router.get("/qc/settings/visual-picker")
def qc_settings_visual_picker_page(request: Request):
    user = core.get_authenticated_user(request)
    if not user:
        return core.redirect_to_login_for_current_path(request)
    if core.get_qc_role(user) not in core.QC_SETTINGS_ROLES:
        return core.templates.TemplateResponse(
            "qc_settings_visual_picker.html",
            core.build_qc_template_context(request, user, forbidden=True, page_subtitle="Sắp xếp vị trí", active_page="settings_visual"),
            status_code=403,
        )
    return core.templates.TemplateResponse(
        "qc_settings_visual_picker.html",
        core.build_qc_template_context(request, user, forbidden=False, page_subtitle="Sắp xếp vị trí", active_page="settings_visual"),
    )


@router.get("/api/dm/khach-hang")
def api_dm_khach_hang():
    """Lấy danh sách Khách hàng."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, ten_khach_hang FROM public.dm_khach_hang ORDER BY ten_khach_hang")
            return {"rows": cur.fetchall()}

@router.post("/api/dm/khach-hang", dependencies=[Depends(core.require_qa_admin_api_user)])
async def api_dm_khach_hang_create(request: Request):
    body = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO public.dm_khach_hang (ten_khach_hang) VALUES (%s) RETURNING id", (body["ten_khach_hang"],))
            new_id = cur.fetchone()[0]
            conn.commit()
    return {"id": new_id}

@router.delete("/api/dm/khach-hang/{id}", dependencies=[Depends(core.require_qa_admin_api_user)])
def api_dm_khach_hang_delete(id: int):
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.dm_khach_hang WHERE id = %s", (id,))
            conn.commit()
    return {"status": "ok"}

@router.get("/api/dm/ma-hang")
def api_dm_ma_hang(khach_hang_id: int = Query(...)):
    """Lấy danh sách Mã hàng theo khach_hang_id."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, ten_ma_hang FROM public.dm_ma_hang WHERE khach_hang_id = %s ORDER BY ten_ma_hang", (khach_hang_id,))
            return {"rows": cur.fetchall()}

@router.post("/api/dm/ma-hang", dependencies=[Depends(core.require_qa_admin_api_user)])
async def api_dm_ma_hang_create(request: Request):
    body = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO public.dm_ma_hang (khach_hang_id, ten_ma_hang) VALUES (%s, %s) RETURNING id", 
                        (body["khach_hang_id"], body["ten_ma_hang"]))
            new_id = cur.fetchone()[0]
            conn.commit()
    return {"id": new_id}

@router.delete("/api/dm/ma-hang/{id}", dependencies=[Depends(core.require_qa_admin_api_user)])
def api_dm_ma_hang_delete(id: int):
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.dm_ma_hang WHERE id = %s", (id,))
            conn.commit()
    return {"status": "ok"}

# --- Error Classification ---

@router.get("/api/dm/nhom-loi")
def api_dm_nhom_loi(date_str: Optional[str] = Query(None, alias="date")):
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            catalog_id = core.get_effective_defect_catalog_id(cur, date_str)
            cur.execute(
                """
                SELECT id, ten_nhom
                FROM public.dm_nhom_loi
                WHERE catalog_id = %s
                ORDER BY ten_nhom
                """,
                (catalog_id,),
            )
            return {"rows": cur.fetchall()}

@router.post("/api/dm/nhom-loi", dependencies=[Depends(core.require_qa_admin_api_user)])
async def api_dm_nhom_loi_create(request: Request):
    body = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            catalog_id = core.get_effective_defect_catalog_id(cur)
            cur.execute(
                "INSERT INTO public.dm_nhom_loi (catalog_id, ten_nhom) VALUES (%s, %s) RETURNING id",
                (catalog_id, body["ten_nhom"]),
            )
            new_id = cur.fetchone()[0]
            conn.commit()
    return {"id": new_id}

@router.delete("/api/dm/nhom-loi/{id}", dependencies=[Depends(core.require_qa_admin_api_user)])
def api_dm_nhom_loi_delete(id: int):
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.dm_nhom_loi WHERE id = %s", (id,))
            conn.commit()
    return {"status": "ok"}

@router.get("/api/dm/ma-loi")
def api_dm_ma_loi(nhom_loi_id: int = Query(...)):
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, ten_ma FROM public.dm_ma_loi WHERE nhom_loi_id = %s ORDER BY ten_ma", (nhom_loi_id,))
            return {"rows": cur.fetchall()}

@router.post("/api/dm/ma-loi", dependencies=[Depends(core.require_qa_admin_api_user)])
async def api_dm_ma_loi_create(request: Request):
    body = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO public.dm_ma_loi (nhom_loi_id, ten_ma) VALUES (%s, %s) RETURNING id", 
                        (body["nhom_loi_id"], body["ten_ma"]))
            new_id = cur.fetchone()[0]
            conn.commit()
    return {"id": new_id}

@router.delete("/api/dm/ma-loi/{id}", dependencies=[Depends(core.require_qa_admin_api_user)])
def api_dm_ma_loi_delete(id: int):
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.dm_ma_loi WHERE id = %s", (id,))
            conn.commit()
    return {"status": "ok"}

@router.get("/api/dm/mo-ta-loi")
def api_dm_mo_ta_loi(ma_loi_id: int = Query(...)):
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, ten_mo_ta FROM public.dm_mo_ta_loi WHERE ma_loi_id = %s ORDER BY ten_mo_ta", (ma_loi_id,))
            return {"rows": cur.fetchall()}

@router.post("/api/dm/mo-ta-loi", dependencies=[Depends(core.require_qa_admin_api_user)])
async def api_dm_mo_ta_loi_create(request: Request):
    body = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO public.dm_mo_ta_loi (ma_loi_id, ten_mo_ta) VALUES (%s, %s) RETURNING id", 
                        (body["ma_loi_id"], body["ten_mo_ta"]))
            new_id = cur.fetchone()[0]
            conn.commit()
    return {"id": new_id}

@router.delete("/api/dm/mo-ta-loi/{id}", dependencies=[Depends(core.require_qa_admin_api_user)])
def api_dm_mo_ta_loi_delete(id: int):
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.dm_mo_ta_loi WHERE id = %s", (id,))
            conn.commit()
    return {"status": "ok"}

@router.get("/api/dm/ma-loi-options")
def api_dm_ma_loi_options(date_str: Optional[str] = Query(None, alias="date")):
    """
    Lấy danh sách Mã lỗi + Mô tả lỗi dạng gộp theo catalog hiệu lực.
    """
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            catalog_id = core.get_effective_defect_catalog_id(cur, date_str)
            cur.execute("""
                SELECT 
                    dc.id AS catalog_id,
                    dc.code AS catalog_code,
                    nl.ten_nhom,
                    ml.id AS ma_loi_id,
                    mt.id AS mo_ta_loi_id,
                    ml.ten_ma,
                    mt.ten_mo_ta,
                    mt.muc_do
                FROM public.dm_ma_loi ml
                JOIN public.dm_nhom_loi nl ON nl.id = ml.nhom_loi_id
                JOIN public.dm_defect_catalog dc ON dc.id = nl.catalog_id
                JOIN public.dm_mo_ta_loi mt ON mt.ma_loi_id = ml.id
                WHERE dc.id = %s
                ORDER BY ml.ten_ma, mt.ten_mo_ta
            """, (catalog_id,))
            rows = cur.fetchall()

            def _sort_key(ten_ma: str):
                if not ten_ma:
                    return ("", 0, ten_ma)
                m = re.match(r"([A-Za-z]+)(\d+)", ten_ma.strip())
                if m:
                    return (m.group(1), int(m.group(2)), ten_ma)
                return (ten_ma, 0, ten_ma)

            rows.sort(key=lambda r: _sort_key(r.get("ten_ma")))
            for r in rows:
                r["label"] = f"{r['ten_ma']}. {r['ten_mo_ta']}"
            return {"rows": rows, "catalog_id": catalog_id}
