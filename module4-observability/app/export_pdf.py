from datetime import datetime
from zoneinfo import ZoneInfo

from fpdf import FPDF
from fpdf.enums import TableCellFillMode

SGT = ZoneInfo("Asia/Singapore")


def _text(value) -> str:
    return str("" if value is None else value).encode("latin-1", "replace").decode("latin-1")


def _when(value) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return str(value)
        return parsed.astimezone(SGT).strftime("%d %b %Y %H:%M")
    except ValueError:
        return str(value)


def _risk(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def attendance_pdf(title: str, rows: list, summary: dict | None = None, generated_by: str = "") -> bytes:
    pdf = FPDF(orientation="L", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    stamp = datetime.now(SGT).strftime("%d %b %Y %H:%M SGT")
    pdf.cell(0, 6, _text(f"Generated {stamp}" + (f" by {generated_by}" if generated_by else "")),
             new_x="LMARGIN", new_y="NEXT")
    if summary:
        line = ", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in summary.items()
                         if isinstance(value, (int, float, str)))
        if line:
            pdf.multi_cell(0, 6, _text(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    with pdf.table(
        col_widths=(48, 62, 56, 38, 24, 18),
        text_align=("LEFT", "LEFT", "LEFT", "LEFT", "LEFT", "RIGHT"),
        cell_fill_mode=TableCellFillMode.ROWS,
        cell_fill_color=(245, 245, 245),
        line_height=5.5,
    ) as table:
        header = table.row()
        for name in ("Student", "Email", "Session", "Checked in (SGT)", "Status", "Risk"):
            header.cell(name, style=None)
        for record in rows:
            row = table.row()
            row.cell(_text(record.get("student_name")))
            row.cell(_text(record.get("student_email")))
            row.cell(_text(record.get("session_name")))
            row.cell(_text(_when(record.get("checked_in_at"))))
            row.cell(_text(record.get("status")))
            row.cell(_text(_risk(record.get("risk_score"))))
    return bytes(pdf.output())
