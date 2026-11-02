#!/usr/bin/env python3
"""Convert BAO_CAO.md to a formatted Word document (BAO_CAO.docx) with python-docx.

Handles the Markdown subset used in the report: headings, paragraphs, bullet / numbered lists, tables,
code blocks, block quotes, **bold**, *italic*, `code`, links. The two mermaid diagrams are replaced by
the PNGs made by tools/make_diagrams.py, and the result figures are inserted after sections 6.5/6.7.

Usage: python tools/md_to_docx.py [BAO_CAO.md] [-o BAO_CAO.docx]
"""
import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "figures"
BODY_FONT = "Calibri"
MONO_FONT = "Consolas"
ACCENT = RGBColor(0x1F, 0x3A, 0x5F)

# figures inserted *before* the heading that starts with the key; (file, caption)
INSERT_BEFORE = {
    "### 6.7": [("fig_operating_curves.png", "Tỉ lệ phát hiện ca ngã theo số báo nhầm mỗi giờ (leave-one-subject-out, 21 người)."),
                ("fig_probability_timelines.png", "Xác suất ngã của AI theo thời gian quanh va đập: hai ca ngã, vỗ tay, nằm giường, đi bộ.")],
    "### 6.9": [("fig_ablation.png", "Ablation: ảnh hưởng của từng thành phần lên tỉ lệ phát hiện và số báo nhầm."),
               ("fig_feature_importance.png", "Độ quan trọng đặc trưng của MLP (hoán vị đặc trưng, người 19–21).")],
}
MERMAID = [("fig_system.png", "Sơ đồ khối của hệ thống Bio-Band."),
           ("fig_states.png", "Máy trạng thái phát hiện té ngã và hai chế độ (luật / luật + AI).")]


# ----------------------------------------------------------------------------- low-level helpers
def set_cell_shading(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def set_cell_margins(table, top=40, bottom=40, left=70, right=70):
    tblPr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for name, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement(f"w:{name}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblPr.insert_element_before(mar, "w:tblLook", "w:tblCaption", "w:tblDescription")


def set_table_width_pct(table):
    tblPr = table._tbl.tblPr
    for el in tblPr.findall(qn("w:tblW")):
        tblPr.remove(el)
    w = OxmlElement("w:tblW")
    w.set(qn("w:w"), "5000")
    w.set(qn("w:type"), "pct")
    tblPr.insert_element_before(w, "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
                                "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription")


def repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def no_split(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def add_field(run, instr):
    for kind, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        elif text == instr:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = instr
        else:
            el = OxmlElement("w:t")
            el.text = text
        run._r.append(el)


def shade_paragraph(p, fill="F3F3F3"):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pPr.insert_element_before(shd, "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def left_border(p, color="1F3A5F"):
    pPr = p._p.get_or_add_pPr()
    b = OxmlElement("w:pBdr")
    el = OxmlElement("w:left")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), "18")
    el.set(qn("w:space"), "6")
    el.set(qn("w:color"), color)
    b.append(el)
    pPr.insert_element_before(b, "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


# ----------------------------------------------------------------------------- inline markdown
INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\*[^*\s][^*]*?\*|\[[^\]]+\]\([^)]+\))")


def add_inline(p, text, size=None, color=None, bold=None):
    text = text.replace("\\*", "\u0001").replace("\\|", "|")
    for part in INLINE.split(text):
        if not part:
            continue
        run = None
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = p.add_run(part[2:-2].replace("\u0001", "*"))
            run.bold = True
        elif part.startswith("`") and part.endswith("`"):
            run = p.add_run(part[1:-1].replace("\u0001", "*"))
            run.font.name = MONO_FONT
            run._r.rPr.rFonts.set(qn("w:eastAsia"), MONO_FONT)
            run.font.size = Pt((size or 11) - 1)
            run.font.color.rgb = RGBColor(0x9C, 0x2B, 0x2B)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2 and not part.startswith("**"):
            run = p.add_run(part[1:-1].replace("\u0001", "*"))
            run.italic = True
        elif part.startswith("[") and "](" in part:
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", part).groups()
            run = p.add_run(label.replace("\u0001", "*"))
            if url.startswith("http"):
                run.font.color.rgb = RGBColor(0x1F, 0x4E, 0xA8)
                run.underline = True
        else:
            run = p.add_run(part.replace("\u0001", "*"))
        if size and not (part.startswith("`") and part.endswith("`")):
            run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = color
        if bold:
            run.bold = True
    return p


# ----------------------------------------------------------------------------- document assembly
def build(md_path: Path, out_path: Path):
    lines = md_path.read_text(encoding="utf-8").split("\n")
    doc = Document()

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(2.0)

    st = doc.styles["Normal"]
    st.font.name = BODY_FONT
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    st.paragraph_format.space_after = Pt(6)
    st.paragraph_format.line_spacing = 1.18
    for name, size, before, after in (("Heading 1", 20, 18, 8), ("Heading 2", 16, 16, 6), ("Heading 3", 13, 12, 4), ("Heading 4", 11.5, 8, 3)):
        h = doc.styles[name]
        h.font.name = BODY_FONT
        h.font.size = Pt(size)
        h.font.bold = True
        h.font.color.rgb = ACCENT
        h.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
        h.element.rPr.rFonts.set(qn("w:ascii"), BODY_FONT)
        h.element.rPr.rFonts.set(qn("w:hAnsi"), BODY_FONT)
        h.paragraph_format.space_before = Pt(before)
        h.paragraph_format.space_after = Pt(after)
        h.paragraph_format.keep_with_next = True

    # footer: title + page number
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("Bio-Band — báo cáo dự án  ·  Trang ")
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    r2 = fp.add_run()
    r2.font.size = Pt(9)
    add_field(r2, "PAGE")

    fig_no = [0]

    def add_figure(file, caption):
        path = FIG / file
        if not path.is_file():
            return
        fig_no[0] += 1
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = Pt(6)
        p.add_run().add_picture(str(path), width=Cm(16.2))
        c = doc.add_paragraph()
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = c.add_run(f"Hình {fig_no[0]}. {caption}")
        run.italic = True
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    mermaid_idx = 0
    i = 0
    title_done = False
    in_toc = False
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        # ---- code fences
        if s.startswith("```"):
            lang = s[3:].strip()
            j = i + 1
            block = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                block.append(lines[j])
                j += 1
            i = j + 1
            if lang == "mermaid":
                if mermaid_idx < len(MERMAID):
                    add_figure(*MERMAID[mermaid_idx])
                mermaid_idx += 1
                continue
            for k, code_line in enumerate(block):
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.left_indent = Cm(0.3)
                shade_paragraph(p)
                run = p.add_run(code_line if code_line else " ")
                run.font.name = MONO_FONT
                run._r.rPr.rFonts.set(qn("w:eastAsia"), MONO_FONT)
                run.font.size = Pt(8.5)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
            continue

        # ---- figures injected before given headings
        for key, figs in INSERT_BEFORE.items():
            if s.startswith(key + " ") or s.startswith(key + "."):
                for f in figs:
                    add_figure(*f)
                INSERT_BEFORE[key] = []
                break

        # ---- headings
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            if level == 1 and not title_done:
                title_done = True
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.space_before = Pt(70)
                p.paragraph_format.space_after = Pt(10)
                run = p.add_run(text)
                run.bold = True
                run.font.size = Pt(26)
                run.font.color.rgb = ACCENT
                i += 1
                continue
            in_toc = text.lower().startswith("mục lục")
            h = doc.add_heading(level=min(level, 4))
            add_inline(h, text)
            if level == 2 and not in_toc and text[:2].strip().rstrip(".").isdigit() and text.split(".")[0] != "1":
                h.paragraph_format.page_break_before = False
            i += 1
            continue

        # ---- horizontal rule
        if re.match(r"^-{3,}$", s):
            i += 1
            continue

        # ---- block quote
        if s.startswith(">"):
            while i < len(lines) and lines[i].strip().startswith(">"):
                q = lines[i].strip().lstrip(">").strip()
                if q:
                    p = doc.add_paragraph()
                    p.paragraph_format.left_indent = Cm(0.4)
                    p.paragraph_format.space_after = Pt(3)
                    left_border(p)
                    add_inline(p, q, size=10.5, color=RGBColor(0x33, 0x33, 0x33))
                i += 1
            continue

        # ---- tables
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            rows = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                if not re.match(r"^\|[\s:|-]+\|$", lines[j].strip()):
                    cells = re.split(r"(?<!\\)\|", lines[j].strip())[1:-1]
                    rows.append([c.strip() for c in cells])
                j += 1
            i = j
            ncol = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=ncol)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            set_table_width_pct(table)
            set_cell_margins(table)
            fs = 9.5 if ncol <= 4 else 8.8
            for ri, row in enumerate(rows):
                tr = table.rows[ri]
                no_split(tr)
                for ci in range(ncol):
                    cell = tr.cells[ci]
                    txt = row[ci] if ci < len(row) else ""
                    p = cell.paragraphs[0]
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.05
                    add_inline(p, txt, size=fs, bold=(ri == 0))
                    if ri == 0:
                        set_cell_shading(cell, "D9E2F3")
                    elif ri % 2 == 0:
                        set_cell_shading(cell, "F6F8FC")
                if ri == 0:
                    repeat_header(tr)
            sp = doc.add_paragraph()
            sp.paragraph_format.space_after = Pt(4)
            continue

        # ---- lists
        mb = re.match(r"^(\s*)[-*]\s+(.*)$", ln)
        mn = re.match(r"^(\s*)(\d+)\.\s+(.*)$", ln)
        if mb or mn:
            indent = len((mb or mn).group(1))
            level = 1 if indent >= 2 else 0
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.left_indent = Cm(0.75 + 0.7 * level)
            p.paragraph_format.first_line_indent = Cm(-0.5)
            if mb:
                p.add_run("•  " if level == 0 else "–  ")
                add_inline(p, mb.group(2))
            else:
                p.add_run(f"{mn.group(2)}. ")
                add_inline(p, mn.group(3))
            i += 1
            continue

        # ---- blank
        if not s:
            i += 1
            continue

        # ---- paragraph (merge consecutive lines)
        buf = [s]
        j = i + 1
        while j < len(lines) and lines[j].strip() and not re.match(r"^(#|\||>|```|\s*[-*]\s|\s*\d+\.\s|-{3,}$)", lines[j]):
            buf.append(lines[j].strip())
            j += 1
        i = j
        p = doc.add_paragraph()
        add_inline(p, " ".join(buf))

    # remaining figures whose anchor heading was never reached
    for key, figs in INSERT_BEFORE.items():
        for f in figs:
            add_figure(*f)

    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")
    doc.core_properties.title = "Bio-Band — Vòng đeo tay phát hiện té ngã và theo dõi sinh hiệu (TinyML trên ESP32-S3)"
    doc.core_properties.author = "Bio-Band"
    doc.core_properties.language = "vi-VN"
    doc.save(out_path)
    return fig_no[0]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("md", nargs="?", default=str(ROOT / "BAO_CAO.md"))
    ap.add_argument("-o", "--out", default=str(ROOT / "BAO_CAO.docx"))
    a = ap.parse_args()
    n = build(Path(a.md), Path(a.out))
    print(f"wrote {a.out} ({n} figures)")
