"""File text extraction — PDF / DOCX / XLSX / PPTX / text / images.

Never raises: every extractor returns {"text": ..., "pages": n?, "truncated": bool}
and degrades to {"text": "", "error": ...} on corrupt input or missing libs.
"""
from __future__ import annotations

import io

MAX_CHARS = 20000
MAX_PAGES = 100
MAX_ROWS = 1000  # per sheet


def _cut(s: str) -> tuple[str, bool]:
    return (s[:MAX_CHARS], len(s) > MAX_CHARS)


def _pdf(data: bytes) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for i, page in enumerate(reader.pages[:MAX_PAGES]):
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    text, trunc = _cut("\n".join(p for p in parts if p.strip()))
    return {"text": text, "pages": min(len(reader.pages), MAX_PAGES),
            "truncated": trunc or len(reader.pages) > MAX_PAGES}


def _docx(data: bytes) -> dict:
    from docx import Document
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    text, trunc = _cut("\n".join(parts))
    return {"text": text, "truncated": trunc}


def _xlsx(data: bytes) -> dict:
    from itertools import islice
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"[Sheet: {ws.title}]")
        for row in islice(ws.iter_rows(values_only=True), MAX_ROWS):
            line = " | ".join("" if v is None else str(v) for v in row).rstrip(" |")
            if line.strip(" |"):
                parts.append(line)
    wb.close()
    text, trunc = _cut("\n".join(parts))
    return {"text": text, "truncated": trunc}


def _pptx(data: bytes) -> dict:
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    parts = []
    for i, slide in enumerate(prs.slides):
        if i >= MAX_PAGES:
            break
        bits = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                bits.append(shape.text)
            elif shape.has_table:
                for row in shape.table.rows:
                    bits.append(" | ".join(c.text for c in row.cells))
        if bits:
            parts.append(f"[Slide {i + 1}]\n" + "\n".join(bits))
    text, trunc = _cut("\n".join(parts))
    return {"text": text, "slides": min(len(prs.slides), MAX_PAGES),
            "truncated": trunc or len(prs.slides) > MAX_PAGES}


def _image(data: bytes, suffix: str) -> dict:
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img.load()
    return {"text": f"[image: {img.format or suffix} {img.width}x{img.height}]",
            "truncated": False}


_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".jsonl", ".log", ".yaml", ".yml"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def extract_text(data: bytes, filename: str, content_type: str = "") -> dict:
    """Extract searchable text from an upload. Never raises."""
    suffix = "." + (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    try:
        if (content_type or "").startswith("text/") or suffix in _TEXT_SUFFIXES:
            text, trunc = _cut(data.decode("utf-8", "ignore"))
            return {"text": text, "truncated": trunc}
        if suffix == ".pdf":
            return _pdf(data)
        if suffix == ".docx":
            return _docx(data)
        if suffix == ".xlsx":
            return _xlsx(data)
        if suffix == ".pptx":
            return _pptx(data)
        if suffix in _IMAGE_SUFFIXES:
            return _image(data, suffix)
    except ImportError as e:
        return {"text": "", "error": f"extractor missing: {e.name if hasattr(e, 'name') else e}"}
    except Exception as e:
        return {"text": "", "error": f"{suffix or 'file'} parse failed: {str(e)[:120]}"}
    return {"text": "", "error": f"unsupported type: {suffix or content_type or 'unknown'}"}
