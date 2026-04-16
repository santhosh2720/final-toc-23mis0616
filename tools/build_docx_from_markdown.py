from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape
import re
import sys
import zipfile


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@dataclass(slots=True)
class Block:
    kind: str
    text: str


def parse_markdown(source: str) -> list[Block]:
    lines = source.splitlines()
    blocks: list[Block] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines).strip()
            if text:
                blocks.append(Block("paragraph", text))
            paragraph_lines = []

    for line in lines:
        stripped = line.rstrip()
        if not stripped.strip():
            flush_paragraph()
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            blocks.append(Block("title", stripped[2:].strip()))
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            blocks.append(Block("heading1", stripped[3:].strip()))
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            blocks.append(Block("heading2", stripped[4:].strip()))
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            blocks.append(Block("bullet", stripped[2:].strip()))
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            continue
        paragraph_lines.append(stripped)

    flush_paragraph()
    return blocks


def run_properties(*, bold: bool = False, italic: bool = False, color: str | None = None, size: int | None = None) -> str:
    parts: list[str] = []
    if bold:
        parts.append("<w:b/>")
    if italic:
        parts.append("<w:i/>")
    if color:
        parts.append(f'<w:color w:val="{color}"/>')
    if size:
        parts.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    return f"<w:rPr>{''.join(parts)}</w:rPr>" if parts else ""


def paragraph_properties(*, align: str | None = None, spacing_before: int = 0, spacing_after: int = 160, left: int = 0, first_line: int = 0) -> str:
    parts = [f'<w:spacing w:before="{spacing_before}" w:after="{spacing_after}" w:line="360" w:lineRule="auto"/>']
    if align:
        parts.append(f'<w:jc w:val="{align}"/>')
    if left or first_line:
        parts.append(f'<w:ind w:left="{left}" w:firstLine="{first_line}"/>')
    return f"<w:pPr>{''.join(parts)}</w:pPr>"


def make_paragraph(text: str, *, align: str | None = None, bold: bool = False, italic: bool = False, color: str | None = None, size: int | None = None, spacing_before: int = 0, spacing_after: int = 160, left: int = 0, first_line: int = 0) -> str:
    safe = escape(text)
    ppr = paragraph_properties(
        align=align,
        spacing_before=spacing_before,
        spacing_after=spacing_after,
        left=left,
        first_line=first_line,
    )
    rpr = run_properties(bold=bold, italic=italic, color=color, size=size)
    return f"<w:p>{ppr}<w:r>{rpr}<w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"


def make_page_break() -> str:
    return "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"


def build_document_xml(template_xml: str, markdown_text: str) -> str:
    blocks = parse_markdown(markdown_text)
    prefix, _, body_and_rest = template_xml.partition("<w:body>")
    if not body_and_rest:
        raise RuntimeError("Template document.xml does not contain <w:body>.")
    body_content, _, _ = body_and_rest.partition("</w:body>")
    sect_matches = re.findall(r"(<w:sectPr[\s\S]*?</w:sectPr>)", body_content)
    sect_pr = sect_matches[-1] if sect_matches else (
        '<w:sectPr>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>'
        '</w:sectPr>'
    )

    xml_parts: list[str] = []
    first_heading = True

    for block in blocks:
        if block.kind == "title":
            xml_parts.append(make_paragraph(block.text, align="center", bold=True, color="8A1C1C", size=34, spacing_before=220, spacing_after=220))
            continue
        if block.kind == "heading1":
            if first_heading:
                xml_parts.append(make_page_break())
                first_heading = False
            else:
                xml_parts.append(make_page_break())
            xml_parts.append(make_paragraph(block.text, bold=True, color="1F4E79", size=30, spacing_before=120, spacing_after=120))
            continue
        if block.kind == "heading2":
            xml_parts.append(make_paragraph(block.text, bold=True, color="C55A11", size=24, spacing_before=90, spacing_after=70))
            continue
        if block.kind == "bullet":
            xml_parts.append(make_paragraph(f"- {block.text}", color="1F1F1F", size=22, left=360, first_line=0, spacing_after=90))
            continue
        xml_parts.append(make_paragraph(block.text, color="1F1F1F", size=22, first_line=360, spacing_after=140))

    return f"{prefix}<w:body>{''.join(xml_parts)}{sect_pr}</w:body></w:document>"


def build_from_template(template_path: Path, markdown_path: Path, output_path: Path) -> None:
    template_xml = ""
    with zipfile.ZipFile(template_path, "r") as src_zip:
        template_xml = src_zip.read("word/document.xml").decode("utf-8")
        markdown_text = markdown_path.read_text(encoding="utf-8")
        new_document_xml = build_document_xml(template_xml, markdown_text)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as dst_zip:
            for item in src_zip.infolist():
                data = src_zip.read(item.filename)
                if item.filename == "word/document.xml":
                    data = new_document_xml.encode("utf-8")
                dst_zip.writestr(item, data)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: build_docx_from_markdown.py <template.docx> <source.md> <output.docx>")
    template_path = Path(sys.argv[1])
    markdown_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])
    build_from_template(template_path, markdown_path, output_path)
    print(output_path)


if __name__ == "__main__":
    main()
