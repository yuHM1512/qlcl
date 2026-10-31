"""Dựng PDF báo cáo HĐKP (Hachiba-QT-10.1/BM1) trực tiếp bằng reportlab.

Trước đây biểu mẫu được điền vào file Excel rồi nhờ Excel chuyển sang PDF.
Cách đó buộc máy chủ phải cài Excel và điều khiển nó qua COM, lại vướng chuyện
AutoFit của Excel bỏ qua ô đã merge nên nội dung dài bị cắt ngang. Dựng thẳng
ở đây thì chiều cao hàng tự giãn theo nội dung.

Bố cục, cỡ chữ và màu lấy đúng theo file 10.1-bm1.xlsx.
"""
import html
import os
from typing import Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

FONT_REGULAR = "HDKPSerif"
FONT_BOLD = "HDKPSerif-Bold"
FONT_ITALIC = "HDKPSerif-Italic"

# Times New Roman để khớp bản Excel gốc; các bộ còn lại chỉ là lối thoát
# khi chạy ngoài Windows.
_FONT_SETS = (
    ("times.ttf", "timesbd.ttf", "timesi.ttf"),
    ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf"),
    ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf", "LiberationSerif-Italic.ttf"),
)
_FONT_DIRS = (
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/TTF",
)

HEADING_COLOR = colors.HexColor("#0000CC")
HEADER_FILL = colors.HexColor("#FFFF00")
GRID_COLOR = colors.black
GRID_WIDTH = 0.75

# Độ rộng 10 cột A..J trong file Excel; chỉ dùng tỉ lệ nên đơn vị không quan
# trọng. Cột E và G..J không khai báo riêng nên lấy defaultColWidth của sheet
# (14.45), không phải 8.43 như mặc định thường thấy của Excel.
COLUMN_WEIGHTS = (14.27, 33.54, 14.45, 7.73, 14.45, 14.45, 14.45, 14.45, 14.45, 14.45)

MIN_CAUSE_ROWS = 3  # biểu mẫu luôn chừa 3 dòng cho mỗi mục A và B
MIN_TODO_ROWS = 4

_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    for regular, bold, italic in _FONT_SETS:
        for directory in _FONT_DIRS:
            paths = [os.path.join(directory, name) for name in (regular, bold, italic)]
            if not all(os.path.exists(p) for p in paths):
                continue
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, paths[0]))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, paths[1]))
            pdfmetrics.registerFont(TTFont(FONT_ITALIC, paths[2]))
            pdfmetrics.registerFontFamily(
                FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD, italic=FONT_ITALIC
            )
            _fonts_ready = True
            return
    raise RuntimeError(
        "Không tìm thấy font chữ có dấu tiếng Việt để dựng PDF "
        "(cần Times New Roman, DejaVu Serif hoặc Liberation Serif)"
    )


def _style(name: str, size: float, **kwargs) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName=kwargs.pop("fontName", FONT_REGULAR),
        fontSize=size,
        leading=size * 1.22,
        **kwargs,
    )


def _styles() -> Dict[str, ParagraphStyle]:
    return {
        "doc_title": _style("doc_title", 16, fontName=FONT_BOLD, alignment=1),
        "doc_meta": _style("doc_meta", 12, textColor=HEADING_COLOR),
        "section": _style("section", 16, fontName=FONT_BOLD, alignment=1,
                          textColor=HEADING_COLOR),
        "label": _style("label", 12),
        "value": _style("value", 12),
        "col_head": _style("col_head", 12, fontName=FONT_BOLD, alignment=1),
        "cell": _style("cell", 11, alignment=1),
        "cell_left": _style("cell_left", 11),
        "note": _style("note", 12, fontName=FONT_ITALIC),
        "sign": _style("sign", 11, fontName=FONT_ITALIC, alignment=1),
        "sign_left": _style("sign_left", 11, fontName=FONT_ITALIC),
    }


def _para(text, style: ParagraphStyle) -> Paragraph:
    """Một ô văn bản; xuống dòng thủ công được giữ nguyên.

    Ô rỗng vẫn nhận một khoảng trắng để hàng giữ được chiều cao của biểu mẫu
    thay vì dẹt xuống gần bằng không.
    """
    safe = html.escape("" if text is None else str(text)).replace("\n", "<br/>")
    return Paragraph(safe if safe.strip() else " ", style)


def _column_widths(total_width: float) -> List[float]:
    span = sum(COLUMN_WEIGHTS)
    return [total_width * w / span for w in COLUMN_WEIGHTS]


def _merge(widths: List[float], first: int, last: int) -> float:
    return sum(widths[first:last + 1])


# Hai hàm chuẩn bị dữ liệu đặt tên khác nhau cho cùng một cột: luồng Final nội
# bộ và HĐKP thường viết có dấu ("a_hđkp_tuc_thoi"), luồng endline viết không
# dấu. Nhận cả hai để không luồng nào mất cột.
_FIELD_ALIASES = {
    "a_hdkp_tuc_thoi": ("a_hdkp_tuc_thoi", "a_hđkp_tuc_thoi"),
    "a_hd_phong_ngua": ("a_hd_phong_ngua", "a_hđ_phong_ngua"),
    "b_hdkp_tuc_thoi": ("b_hdkp_tuc_thoi", "b_hđkp_tuc_thoi"),
    "b_hd_phong_ngua": ("b_hd_phong_ngua", "b_hđ_phong_ngua"),
}


def _numbered(data: Dict, prefix: str, index: int) -> str:
    for name in _FIELD_ALIASES.get(prefix, (prefix,)):
        value = data.get(f"{name}_{index}")
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _count_items(data: Dict, probe_prefixes, minimum: int) -> int:
    """Số dòng cần vẽ: đủ chỗ cho dữ liệu, nhưng không ít hơn biểu mẫu gốc."""
    count = 0
    index = 1
    while True:
        if not any(_numbered(data, prefix, index) for prefix in probe_prefixes):
            break
        count = index
        index += 1
    return max(count, minimum)


def _logo_flowable(logo_path: Optional[str], width: float, height: float):
    if not logo_path or not os.path.exists(logo_path):
        return ""
    try:
        logo = Image(logo_path)
        ratio = logo.imageWidth / float(logo.imageHeight or 1)
        draw_h = min(height, width / ratio)
        logo.drawHeight = draw_h
        logo.drawWidth = draw_h * ratio
        logo.hAlign = "CENTER"
        return logo
    except Exception:
        return ""


def _problem_image(url: str, images_dir: Optional[str], max_width: float,
                   max_height: float):
    if not url or not str(url).strip() or not images_dir:
        return ""
    name = str(url).strip()
    for prefix in ("/api/images/", "api/images/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    path = name if os.path.isabs(name) else os.path.join(images_dir, name)
    if not os.path.exists(path):
        return ""
    try:
        picture = Image(path)
        ratio = picture.imageWidth / float(picture.imageHeight or 1)
        draw_h = min(max_height, max_width / ratio)
        picture.drawHeight = draw_h
        picture.drawWidth = draw_h * ratio
        picture.hAlign = "LEFT"
        return picture
    except Exception:
        return ""


def _grid(extra=()) -> TableStyle:
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), GRID_WIDTH, GRID_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        *extra,
    ])


def _header_block(data: Dict, widths: List[float], st, logo_path) -> Table:
    logo_width = _merge(widths, 0, 1)
    rows = [
        [_logo_flowable(logo_path, logo_width - 10, 62),
         _para("BÁO CÁO HÀNH ĐỘNG\nKHẮC PHỤC PHÒNG NGỪA", st["doc_title"]),
         _para("Kí mã hiệu: Hachiba-QT-10.1/BM1", st["doc_meta"])],
        ["", "", _para("Lần soát xét 01/02", st["doc_meta"])],
        ["", "", _para("Ngày hiệu lực: 10/6/2022", st["doc_meta"])],
    ]
    table = Table(
        rows,
        colWidths=[logo_width, _merge(widths, 2, 6), _merge(widths, 7, 9)],
        rowHeights=[23.25, 23.25, 23.25],
    )
    table.setStyle(_grid([
        ("SPAN", (0, 0), (0, 2)),
        ("SPAN", (1, 0), (1, 2)),
    ]))
    return table


def _describe_block(data: Dict, widths: List[float], st, images_dir) -> List:
    label_width = _merge(widths, 0, 1)
    value_width = _merge(widths, 2, 9)

    title = Table([[_para("I. Mô tả vấn đề", st["section"])]],
                  colWidths=[sum(widths)], rowHeights=[42.75])
    title.setStyle(_grid())

    questions = (
        ("1- Vấn đề gì đã xảy ra?", "vd_what"),
        ("2- Vấn đề phát hiện ra khi nào?", "vd_when"),
        ("3- Ai là người phát hiện ra vấn đề?", "vd_who"),
        ("4- Vấn đề xảy ra ở đâu? Bộ phận nào?", "vd_where"),
        ("5- Vấn đề xảy ra như thế nào? Mô tả tình huống", "vd_how"),
        ("6- Vấn đề đã từng xảy ra chưa?", "vd_before"),
        ("7- Tại sao vấn đề này lại nghiêm trọng?", "vd_importance"),
    )
    rows = [[_para(label, st["label"]), _para(data.get(key, ""), st["value"])]
            for label, key in questions]
    rows.append([
        _para("8- Hình ảnh, nếu có", st["label"]),
        _problem_image(data.get("vd_image", ""), images_dir, value_width - 10, 150),
    ])

    body = Table(rows, colWidths=[label_width, value_width])
    body.setStyle(_grid())
    return [title, body]


def _plan_block(data: Dict, widths: List[float], st) -> List:
    title = Table([[_para("II. Kế hoạch khắc phục, phòng ngừa", st["section"])]],
                  colWidths=[sum(widths)], rowHeights=[42.75])
    title.setStyle(_grid())

    col_widths = [
        widths[0], widths[1], _merge(widths, 2, 4), _merge(widths, 5, 6),
        widths[7], widths[8], widths[9],
    ]
    head = [
        _para("Phân tích nguyên nhân (*)", st["col_head"]),
        _para("Nguyên nhân cuối cùng", st["col_head"]),
        _para("Hành động \nkhắc phục tức thời", st["col_head"]),
        _para("Hành động \nphòng ngừa", st["col_head"]),
        _para("Thời gian \ntheo dõi", st["col_head"]),
        _para("Trách nhiệm \nthực hiện", st["col_head"]),
        _para("Thời gian thực hiện (từ…đến)", st["col_head"]),
    ]

    sections = (
        ("A", "A/ Tại sao vấn đề này xảy ra"),
        ("B", "B/ Tại sao vấn đề này không được phát hiện từ trước"),
    )
    rows = [head]
    spans = []
    for key, caption in sections:
        prefixes = (f"{key.lower()}_root_cause", f"{key.lower()}_hdkp_tuc_thoi",
                    f"{key.lower()}_hd_phong_ngua")
        count = _count_items(data, prefixes, MIN_CAUSE_ROWS)
        start = len(rows)
        for index in range(1, count + 1):
            prefix = key.lower()
            rows.append([
                _para(caption, st["cell"]) if index == 1 else "",
                _para(_numbered(data, f"{prefix}_root_cause", index), st["cell"]),
                _para(_numbered(data, f"{prefix}_hdkp_tuc_thoi", index), st["cell"]),
                _para(_numbered(data, f"{prefix}_hd_phong_ngua", index), st["cell"]),
                _para(_numbered(data, f"{prefix}_tg_theo_doi", index), st["cell_left"]),
                _para(_numbered(data, f"{prefix}_trach_nhiem", index), st["cell_left"]),
                _para(_numbered(data, f"{prefix}_tg_thuc_hien", index), st["cell_left"]),
            ])
        spans.append(("SPAN", (0, start), (0, start + count - 1)))

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(_grid([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        *spans,
    ]))

    note = Table([[_para(
        "(*): Người/bộ phận được phân công có trách nhiệm phân tích nguyên nhân cho 2 mục "
        "A và B theo hướng dẫn kèm theo QT-10.1/BM1, sau đó ghi nguyên nhân cuối cùng vào "
        "biểu mẫu này và đề ra biện pháp khắc phục, phòng ngừa thích hợp cho mỗi nguyên "
        "nhân. Trường hợp lãnh đạo công ty hoặc khách hàng có yêu cầu thì phải gởi bảng "
        "phân tích nguyên nhân kèm theo báo cáo hành động khắc phục phòng ngừa",
        st["note"])]], colWidths=[sum(widths)])
    note.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [title, table, note]


def _todo_block(data: Dict, widths: List[float], st) -> List:
    title = Table([[_para("III: Chi tiết kế hoạch khắc phục phòng ngừa (To Do List)",
                          st["section"])]],
                  colWidths=[sum(widths)], rowHeights=[42.75])
    title.setStyle(_grid())

    col_widths = [
        widths[0], widths[1], widths[2], _merge(widths, 3, 4),
        widths[5], widths[6], widths[7], widths[8], widths[9],
    ]
    rows = [
        [_para("Số thứ tự", st["col_head"]),
         _para("Công việc cụ thể", st["col_head"]),
         _para("Trách nhiệm\nthực hiện", st["col_head"]),
         _para("Ngày bắt đầu thực hiện", st["col_head"]),
         _para("Ngày hoàn thành", st["col_head"]),
         _para("Trách nhiệm \ngiám sát, \nbáo cáo", st["col_head"]),
         _para("Kết quả \nkiểm tra, giám sát", st["col_head"]), "",
         _para("Kết luận", st["col_head"])],
        ["", "", "", "", "", "",
         _para("Đạt", st["col_head"]), _para("Ko đạt", st["col_head"]), ""],
    ]
    count = _count_items(data, ("cong_viec", "trach_nhiem", "ket_luan"), MIN_TODO_ROWS)
    for index in range(1, count + 1):
        has_row = any(_numbered(data, prefix, index)
                      for prefix in ("cong_viec", "trach_nhiem", "giam_sat", "ket_luan"))
        rows.append([
            _para(str(index) if has_row else "", st["cell"]),
            _para(_numbered(data, "cong_viec", index), st["cell"]),
            _para(_numbered(data, "trach_nhiem", index), st["cell"]),
            _para(_numbered(data, "ngay_bat_dau", index), st["cell"]),
            _para(_numbered(data, "ngay_hoan_thanh", index), st["cell"]),
            _para(_numbered(data, "giam_sat", index), st["cell"]),
            _para(_numbered(data, "ket_qua_dat", index), st["cell"]),
            _para(_numbered(data, "ket_qua_khong_dat", index), st["cell"]),
            _para(_numbered(data, "ket_luan", index), st["cell"]),
        ])

    table = Table(rows, colWidths=col_widths, repeatRows=2)
    table.setStyle(_grid([
        ("BACKGROUND", (0, 0), (-1, 1), HEADER_FILL),
        ("SPAN", (0, 0), (0, 1)),
        ("SPAN", (1, 0), (1, 1)),
        ("SPAN", (2, 0), (2, 1)),
        ("SPAN", (3, 0), (3, 1)),
        ("SPAN", (4, 0), (4, 1)),
        ("SPAN", (5, 0), (5, 1)),
        ("SPAN", (6, 0), (7, 0)),
        ("SPAN", (8, 0), (8, 1)),
    ]))
    return [title, table]


def _signature_block(data: Dict, widths: List[float], st) -> Table:
    left_width = _merge(widths, 0, 4)
    rows = [
        [_para("Phê duyệt của Trưởng đơn vị", st["sign"]),
         _para(f"Đà Nẵng, ngày {data.get('created_at', '')}", st["sign"])],
        [_para("hoặc ĐDLĐ/ Ban TGĐ", st["sign"]),
         _para("Người lập biểu", st["sign"])],
        [_para("Võ Thị Tuyết An", st["sign"]),
         _para(data.get("ho_ten", ""), st["sign"])],
    ]
    table = Table(rows, colWidths=[left_width, sum(widths) - left_width],
                  rowHeights=[21, 21, 21])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def render_hdkp_pdf(data: Dict, output_path: str,
                    images_dir: Optional[str] = None,
                    logo_path: Optional[str] = None) -> str:
    """Dựng biểu mẫu HĐKP đã điền dữ liệu thành PDF, trả về đường dẫn file."""
    _register_fonts()
    page_size = landscape(A4)
    left, right = 0.3 * inch, 0.2 * inch
    top, bottom = 0.25 * inch, 0.25 * inch
    widths = _column_widths(page_size[0] - left - right)
    st = _styles()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=page_size,
        leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom,
        title="Báo cáo hành động khắc phục phòng ngừa",
    )
    # Phần II có thể dài tuỳ số nguyên nhân nên cứ để nó chảy sang trang sau,
    # header bảng được lặp lại. Phần III ngắn, giữ liền khối cho dễ đọc.
    story = [
        _header_block(data, widths, st, logo_path),
        *_describe_block(data, widths, st, images_dir),
        *_plan_block(data, widths, st),
        KeepTogether(_todo_block(data, widths, st)),
        Spacer(1, 10),
        _signature_block(data, widths, st),
    ]
    doc.build(story)
    return output_path
