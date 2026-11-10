from __future__ import annotations

import html
import io
import os
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf as fitz
import latex2mathml.converter
import mathml2omml
import resvg_py
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import parse_xml
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph
from PIL import Image, ImageDraw, ImageFont, ImageOps

from schemas import Diagram, Paper
import visuals

MAX_PAGES = 40
Image.MAX_IMAGE_PIXELS = 40_000_000


def office_binary():
    explicit = os.getenv("SOFFICE_PATH", "")
    for candidate in (explicit, shutil.which("soffice"),
                      r"C:\Program Files\LibreOffice\program\soffice.exe"):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def office_convert(source: Path, output: Path, extension: str):
    binary = office_binary()
    if not binary:
        raise RuntimeError("旧 DOC 文件需要服务端安装 LibreOffice，并设置 SOFFICE_PATH。请先另存为 DOCX 后上传。")
    profile = output / "office-profile"
    result = subprocess.run(
        [binary, f"-env:UserInstallation={profile.as_uri()}", "--headless",
         "--convert-to", extension, "--outdir", str(output), str(source)],
        capture_output=True, timeout=90,
    )
    target = output / (source.stem + "." + extension)
    if result.returncode or not target.exists():
        raise RuntimeError("Office 文档转换失败，请检查文件是否损坏或受密码保护。")
    return target


def prepare(folder: Path, files: list[dict]):
    """Normalize pages server-side. DOCX keeps native OMML rather than flattening math."""
    pages = []
    native = []
    media = folder / "media"
    media.mkdir(exist_ok=True)

    def add_image(image, name):
        if len(pages) >= MAX_PAGES:
            raise RuntimeError(f"单次最多 {MAX_PAGES} 页，请分批导入。")
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((2200, 3000))
        target = media / f"page-{len(pages) + 1}.jpg"
        image.save(target, quality=94)
        pages.append({"path": target.relative_to(folder).as_posix(), "source": name,
                      "width": image.width, "height": image.height})

    for file in files:
        source = folder / file["path"]
        suffix = source.suffix.lower()
        if suffix == ".doc":
            source = office_convert(source, media, "docx")
            suffix = ".docx"
        if suffix == ".pdf":
            with fitz.open(source) as pdf:
                if pdf.needs_pass:
                    raise RuntimeError("PDF 有密码，请解密后上传。")
                if len(pdf) + len(pages) > MAX_PAGES:
                    raise RuntimeError(f"单次最多 {MAX_PAGES} 页，请分批导入。")
                for page in pdf:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    add_image(Image.open(io.BytesIO(pix.tobytes("png"))), file["name"])
                    pages[-1]["text_hint"] = page.get_text()[:18000]
        elif suffix == ".docx":
            with zipfile.ZipFile(source) as archive:
                if sum(x.file_size for x in archive.infolist()) > 150_000_000:
                    raise RuntimeError("DOCX 解压后过大。")
                xml = archive.read("word/document.xml").decode("utf-8")
                if len(xml) > 800_000:
                    raise RuntimeError("DOCX 内容过长，请拆分后上传。")
                native.append({"source": file["name"], "document_xml": xml})
                for entry in archive.infolist():
                    if entry.filename.startswith("word/media/") and entry.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        add_image(Image.open(io.BytesIO(archive.read(entry))), entry.filename)
                        pages[-1]["embedded_media"] = True
                # Relationships preserve which illustration belongs to which paragraph.
                rel = "word/_rels/document.xml.rels"
                if rel in archive.namelist():
                    native[-1]["relationships"] = archive.read(rel).decode("utf-8")
        else:
            with Image.open(source) as image:
                add_image(image, file["name"])
    return pages, native


def crop_figures(folder: Path, paper: Paper, pages: list[dict]):
    for q in paper.questions:
        q.original_images = []
        cropped = {}
        for i, region in enumerate(q.figures):
            if region.page >= len(pages):
                q.warnings.append("模型给出的配图页码无效，需要核对。")
                continue
            with Image.open(folder / pages[region.page]["path"]) as image:
                x1, y1, x2, y2 = region.box
                box = (int(x1 * image.width), int(y1 * image.height),
                       int(x2 * image.width), int(y2 * image.height))
                target = folder / "media" / f"{q.id}-original-{i}.png"
                image.crop(box).save(target)
                q.original_images.append(target.relative_to(folder).as_posix())
                cropped[i] = target.relative_to(folder).as_posix()
        if q.visuals:
            # Missing references can only be recovered when the match is unique.
            assigned_regions = {v.source_region for v in q.visuals if v.source_region is not None}
            for asset in q.visuals:
                if asset.source_region is None:
                    candidates = [i for i in cropped if i not in assigned_regions
                                  and asset.caption and q.figures[i].caption == asset.caption]
                    if len(candidates) == 1:
                        asset.source_region = candidates[0]
                    elif len(q.visuals) == 1 and len(cropped) == 1:
                        asset.source_region = next(iter(cropped))
                    if asset.source_region is not None:
                        assigned_regions.add(asset.source_region)
                if asset.source_region not in cropped:
                    raise RuntimeError(f"配图 {asset.id} 缺少有效原图区域，已停止以避免错配。")
                asset.original_image = cropped[asset.source_region]
                asset.redrawn_image = asset.svg_file = ""
            # Retain unreferenced crop regions too; no figure silently disappears.
            from schemas import VisualAsset
            assigned = {v.source_region for v in q.visuals}
            used_ids = {v.id for v in q.visuals}
            for index, path in cropped.items():
                if index not in assigned:
                    key = f"region_{index}"
                    while key in used_ids:
                        key += "_extra"
                    used_ids.add(key)
                    q.visuals.append(VisualAsset(id=key, source_region=index,
                        caption=q.figures[index].caption, original_image=path))
            visuals.sync_paths(q)


def render_diagram(diagram: Diagram, folder: Path, prefix: str):
    """Small declarative renderer: no model-supplied executable code or SVG markup."""
    target = folder / "media" / prefix
    target.parent.mkdir(exist_ok=True)
    canvas = Image.new("RGB", (1200, 900), "white")
    draw = ImageDraw.Draw(canvas)
    font_path = r"C:\Windows\Fonts\times.ttf"
    if not Path(font_path).exists():
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
    try:
        font = ImageFont.truetype(font_path, 36)
    except OSError:
        font = ImageFont.load_default(size=36)
    body = []
    scale = 2
    for p in diagram.primitives:
        attrs = 'fill="none" stroke="#202020" stroke-width="1.5"'
        if p.dashed:
            attrs += ' stroke-dasharray="5 4"'
        if p.type in ("line", "polyline"):
            pts = p.points
            body.append(f'<polyline points="{" ".join(f"{x},{y}" for x, y in pts)}" {attrs}/>')
            for a, b in zip(pts, pts[1:]):
                if p.dashed:
                    length = ((b[0]-a[0])**2+(b[1]-a[1])**2)**0.5
                    for n in range(0, max(1, int(length)), 9):
                        t1, t2 = n/max(length, 1), min((n+5)/max(length, 1), 1)
                        draw.line([(scale*(a[0]+(b[0]-a[0])*t), scale*(a[1]+(b[1]-a[1])*t)) for t in (t1, t2)], fill="#202020", width=3)
                else:
                    draw.line([(x*scale, y*scale) for x, y in (a, b)], fill="#202020", width=3)
        elif p.type in ("circle", "ellipse"):
            rx, ry = (p.r, p.r) if p.type == "circle" else (p.rx, p.ry)
            body.append(f'<ellipse cx="{p.x}" cy="{p.y}" rx="{rx}" ry="{ry}" {attrs}/>')
            draw.ellipse(((p.x-rx)*scale, (p.y-ry)*scale, (p.x+rx)*scale, (p.y+ry)*scale), outline="#202020", width=3)
        elif p.type == "text":
            body.append(f'<text x="{p.x}" y="{p.y}" font-family="serif" font-size="18" fill="#202020">{html.escape(p.text)}</text>')
            draw.text((p.x*scale, p.y*scale-32), p.text, font=font, fill="#202020")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="450" viewBox="0 0 600 450"><rect width="600" height="450" fill="white"/>' + "".join(body) + "</svg>"
    target.with_suffix(".svg").write_text(svg, "utf-8")
    canvas.save(target.with_suffix(".png"))
    return (target.with_suffix(".svg").relative_to(folder).as_posix(),
            target.with_suffix(".png").relative_to(folder).as_posix())


def render_svg(svg: str, folder: Path, prefix: str):
    """Model authors SVG; only passive geometry/text is admitted before rendering."""
    if "<!DOCTYPE" in svg.upper() or "<!ENTITY" in svg.upper():
        raise ValueError("SVG 不允许文档实体")
    root = ET.fromstring(svg)
    allowed = {"svg", "g", "defs", "path", "line", "polyline", "polygon", "circle",
               "ellipse", "rect", "text", "tspan", "title", "desc", "marker", "clipPath"}
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in allowed:
            raise ValueError(f"SVG 包含不支持的元素：{tag}")
        for key, value in node.attrib.items():
            name = key.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or name in ("href", "src"):
                raise ValueError("SVG 不允许脚本或外部资源")
            if "url(" in value.lower() and not re.fullmatch(r"url\(#[\w-]+\)", value):
                raise ValueError("SVG 不允许外部样式资源")
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("不是 SVG 文件")
    # Fixed viewport and output dimensions bound raster resource usage.
    root.set("width", "600")
    root.set("height", "450")
    svg = ET.tostring(root, encoding="unicode")
    png = resvg_py.svg_to_bytes(svg_string=svg, width=1200, height=900, background="white")
    target = folder / "media" / prefix
    target.parent.mkdir(exist_ok=True)
    target.with_suffix(".svg").write_text(svg, "utf-8")
    target.with_suffix(".png").write_bytes(png)
    return (target.with_suffix(".svg").relative_to(folder).as_posix(),
            target.with_suffix(".png").relative_to(folder).as_posix())


MATH_PATTERN = re.compile(r"(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\])")


def add_rich(paragraph, text):
    for part in MATH_PATTERN.split(text):
        if not part:
            continue
        if MATH_PATTERN.fullmatch(part):
            latex = part[2:-2] if part.startswith(("$$", "\\(", "\\[")) else part[1:-1]
            try:
                mathml = latex2mathml.converter.convert(latex)
                omml = mathml2omml.convert(mathml)
                wrapper = parse_xml(
                    '<root xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
                    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    + omml + '</root>')
                for element in list(wrapper):
                    paragraph._p.append(element)
            except Exception as exc:
                raise RuntimeError(f"公式无法转换为可编辑 Word 公式：{latex[:100]}。请重试或调整该公式。") from exc
        else:
            paragraph.add_run(part)


def keep_illustration_with_text(container):
    paragraphs = container.paragraphs
    # Do not chain a sequence of independent figures through their captions.
    if paragraphs and not any(p._p.xpath(".//w:drawing") for p in paragraphs[-2:]):
        paragraphs[-1].paragraph_format.keep_with_next = True


def add_panel(container, panel, question, folder, options, width):
    if panel.title:
        title = container.add_paragraph()
        title.paragraph_format.keep_with_next = bool(panel.figure_id or panel.text)
        add_rich(title, panel.title)
    if panel.figure_id:
        asset = next(v for v in question.visuals if v.id == panel.figure_id)
        path = visuals.safe_path(folder, visuals.choose_path(asset, options.get("figure_modes", {}).get(question.id, options.get("figures")) == "redraw"))
        keep_illustration_with_text(container)
        p = container.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        with Image.open(path) as im:
            image_width = min(width, 6 * im.width / im.height)
        p.add_run().add_picture(str(path), width=Cm(image_width))
        if panel.text:
            p.paragraph_format.keep_with_next = True
        if asset.caption and asset.caption not in (panel.title, panel.text):
            p.paragraph_format.keep_with_next = True
            p = container.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_rich(p, asset.caption)
    if panel.text:
        add_rich(container.add_paragraph(), panel.text)


def add_visual_group(doc, group, question, folder, options):
    single_asset = (next((v for v in question.visuals if v.id == group.panels[0].figure_id), None)
                    if len(group.panels) == 1 else None)
    repeated_caption = single_asset and group.caption.strip() == single_asset.caption.strip()
    if group.caption and not repeated_caption:
        caption = doc.add_paragraph()
        caption.paragraph_format.keep_with_next = True
        add_rich(caption, group.caption)
    count = min(group.columns, len(group.panels))
    table = doc.add_table(rows=(len(group.panels) + count - 1) // count, cols=count)
    table.autofit = False
    borders = parse_xml('<w:tblBorders xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
        ''.join(f'<w:{side} w:val="nil"/>' for side in ("top", "left", "bottom", "right", "insideH", "insideV")) +
        '</w:tblBorders>')
    table._tbl.tblPr.append(borders)
    for column in table.columns:
        column.width = Cm(16.6 / count)
    for i, panel in enumerate(group.panels):
        cell = table.cell(i // count, i % count)
        cell.width = Cm(16.6 / count)
        cell.paragraphs[0].paragraph_format.space_after = Pt(0)
        add_panel(cell, panel, question, folder, options, 16.6 / count - .5)
    for row in table.rows:
        row._tr.get_or_add_trPr().append(parse_xml(
            '<w:cantSplit xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'))
    doc.add_paragraph()


def add_question_tables(doc, question, after, index=0, folder=None, options=None):
    options = options or {}
    items = sorted([*question.tables, *question.visual_groups], key=lambda item: item.order)
    from schemas import VisualGroup
    for source in items:
        if source.after != after or source.after_index != index:
            continue
        if doc.paragraphs:
            doc.paragraphs[-1].paragraph_format.keep_with_next = True
        if isinstance(source, VisualGroup):
            add_visual_group(doc, source, question, folder, options)
            continue
        if source.caption and source.caption.strip() != question.stem.strip():
            add_rich(doc.add_paragraph(), source.caption)
        table = doc.add_table(rows=source.rows, cols=source.columns)
        table.style = "Table Grid"
        if source.column_widths:
            table.autofit = False
            total = sum(source.column_widths)
            for column_index, ratio in enumerate(source.column_widths):
                width = Cm(16.6 * ratio / total)
                table.columns[column_index].width = width
                for row in table.rows:
                    row.cells[column_index].width = width
        for cell in source.cells:
            target = table.cell(cell.row, cell.column)
            if cell.row_span > 1 or cell.column_span > 1:
                target = target.merge(table.cell(cell.row + cell.row_span - 1,
                                                cell.column + cell.column_span - 1))
            target.text = ""
            target.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            add_rich(target.paragraphs[0], cell.text)
            ratios = source.column_widths or [1] * source.columns
            cell_width = 16.6 * sum(ratios[cell.column:cell.column + cell.column_span]) / sum(ratios)
            for panel in cell.panels:
                add_panel(target, panel, question, folder, options, max(.5, cell_width - .5))
        compact = (source.rows <= 8 and not any(c.panels for c in source.cells)
                   and sum(len(c.text) for c in source.cells) < 1000)
        for row_index, row in enumerate(table.rows):
            row._tr.get_or_add_trPr().append(parse_xml(
                '<w:cantSplit xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'))
            if compact and row_index < source.rows - 1:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        paragraph.paragraph_format.keep_with_next = True
        doc.add_paragraph()


def export_docx(folder: Path, paper: Paper, options: dict, teacher=False, filename=None):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2.2)
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "宋体")
    normal.paragraph_format.line_spacing = 1.35
    normal.paragraph_format.space_after = Pt(8)
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    shown_title = paper.title
    if (shown_title == "数学试卷" and paper.questions
            and all(q.content_role == "reference_answer" for q in paper.questions)):
        shown_title = "参考答案与评分标准"
    run = title.add_run(shown_title + (" · 答案与解析" if teacher else ""))
    run.bold, run.font.size = True, Pt(18)
    if not teacher and any(q.content_role == "problem" for q in paper.questions):
        p = doc.add_paragraph("姓名：________________    班级：________________")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    section_pattern = r"^\s*[一二三四五六七八九十\d]+[、.．]\s*(选择题|填空题|解答题|判断题)(?:\s*[（(][^）)]{0,80}[）)])?\s*$"
    kinds = {q.kind for q in paper.questions}
    matches = [re.fullmatch(section_pattern, text) for text in paper.instructions]
    section_headers = {}
    for instruction, match in zip(paper.instructions, matches):
        if (match and match[1] in kinds
                and sum(bool(m and m[1] == match[1]) for m in matches) == 1):
            section_headers[match[1]] = instruction
        else:
            add_rich(doc.add_paragraph(), instruction)
    previous_page = None
    for i, q in enumerate(paper.questions):
        if options.get("layout") == "original" and previous_page is not None and q.source_page != previous_page:
            doc.add_page_break()
        previous_page = q.source_page
        if q.kind in section_headers:
            heading = doc.add_paragraph()
            heading.paragraph_format.keep_with_next = True
            add_rich(heading, section_headers.pop(q.kind))
        question_start = len(doc.element.body) - 1  # Exclude trailing sectPr.
        p = doc.add_paragraph()
        p.paragraph_format.keep_with_next = True
        first_part_is_stem = (not q.stem.strip() and bool(q.parts) and not q.options
                              and not any(item.after == "stem"
                                          for item in [*q.tables, *q.visual_groups]))
        shown_stem = q.parts[0] if first_part_is_stem else q.stem
        section_heading = (q.content_role == "reference_answer" and q.number
                           and not q.number.isdigit() and shown_stem.startswith(q.number))
        prefix = "" if section_heading else f"{q.number or i+1}. "
        add_rich(p, prefix + (f"（{q.points:g} 分）" if q.points is not None else "") + shown_stem)
        add_question_tables(doc, q, "stem", folder=folder, options=options)
        for index, option in enumerate(q.options):
            label = chr(65 + index)
            shown_option = option if re.match(r"^\s*[A-Z](?:[.．、)）:：]|$)", option) else f"{label}. {option}"
            label_pattern = rf"^\s*{label}\s*[.．、)）:：]?\s*$"
            label_in_figure = (re.fullmatch(label_pattern, shown_option) and any(
                panel.figure_id and any(re.fullmatch(label_pattern, value)
                                        for value in (panel.title, panel.text))
                for group in q.visual_groups for panel in group.panels))
            if not label_in_figure:
                option_paragraph = doc.add_paragraph()
                option_paragraph.paragraph_format.keep_with_next = index < len(q.options) - 1
                add_rich(option_paragraph, shown_option)
            add_question_tables(doc, q, "option", index, folder, options)
        for index, part in enumerate(q.parts):
            if not (first_part_is_stem and index == 0):
                add_rich(doc.add_paragraph(), part)
            add_question_tables(doc, q, "part", index, folder, options)
        mode = options.get("figure_modes", {}).get(q.id, options.get("figures", "both"))
        # Student paper uses one representation; resource ZIP includes both.
        images = q.redrawn_images if mode == "redraw" and q.redrawn_images else q.original_images or q.redrawn_images
        if q.visuals:
            from schemas import VisualPanel
            for asset in q.visuals:
                if asset.id not in visuals.referenced_ids(q):
                    add_panel(doc, VisualPanel(figure_id=asset.id), q, folder, options, 9)
            images = []
        for image in images:
            path = (folder / image).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file():
                raise RuntimeError("配图资源缺失，未导出不完整试卷。")
            keep_illustration_with_text(doc)
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(str(path), width=Cm(9))
        # Short multiple-choice items should travel with their diagrams/options.
        # Keep relationships between blocks, not a fixed-height container: Word
        # can still split an item that exceeds a page. Do not chain long problems.
        if q.options and not q.parts and len(q.stem) + sum(map(len, q.options)) <= 1200:
            blocks = list(doc.element.body)[question_start:-1]
            for block in blocks[:-1]:
                for element in block.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                    Paragraph(element, doc).paragraph_format.keep_with_next = True
            if blocks:
                # End the chain before the next question, including a final table.
                for element in blocks[-1].iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                    Paragraph(element, doc).paragraph_format.keep_with_next = False
        if teacher:
            for label, value in (("答案", q.answer), ("详细解答", q.solution), ("知识点介绍", q.knowledge)):
                if value:
                    p = doc.add_paragraph()
                    p.add_run(label + "：").bold = True
                    add_rich(p, value)
            if q.provenance:
                doc.add_paragraph("来源说明：" + q.provenance)
            if q.review and not q.review.get('passed'):
                doc.add_paragraph('审核建议（供教师参考）：' + '；'.join(q.review.get('issues', [])))
        else:
            # Use spacing on existing content; an extra empty paragraph can
            # spill onto an otherwise blank final page after a tall table.
            if doc.paragraphs:
                doc.paragraphs[-1].paragraph_format.space_after = Pt(22 if q.kind == "解答题" else 8)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("第 ")
    footer._p.append(parse_xml('<w:fldSimple xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:instr="PAGE"/>'))
    footer.add_run(" 页")
    export_dir = folder / "exports"
    export_dir.mkdir(exist_ok=True)
    name = filename or ("teacher.docx" if teacher else "paper.docx")
    doc.save(export_dir / name)
    return f"exports/{name}"


def export_resources(folder: Path, paper: Paper):
    target = folder / "exports" / "figures.zip"
    added = set()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for q in paper.questions:
            for file in q.original_images + q.redrawn_images + q.svg_files:
                path = (folder / file).resolve()
                if path.is_relative_to(folder.resolve()) and path.is_file() and file not in added:
                    z.write(path, file)
                    added.add(file)
    return "exports/figures.zip"
