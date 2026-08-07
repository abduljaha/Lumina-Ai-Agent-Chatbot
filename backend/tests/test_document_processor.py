"""Tests for DocumentProcessor - text extraction across every supported file type.

Each test builds a small real file of its format in a temp directory (not a
mock) and asserts the extracted text actually contains the content that was
put into it - this is what catches an extractor silently returning "" (which
`upload_document` now treats as a hard failure, see test_files_endpoint.py).
"""
from __future__ import annotations

import json

import pytest

from app.rag.document_processor import DocumentProcessor, SUPPORTED_EXTENSIONS


@pytest.fixture
def processor() -> DocumentProcessor:
    return DocumentProcessor()


async def _process(processor: DocumentProcessor, tmp_path, filename: str, write) -> list[dict]:
    """Write a fixture file via `write(path)` and run it through the processor."""
    path = tmp_path / filename
    write(path)
    return await processor.process(str(path), filename)


@pytest.mark.asyncio
async def test_txt(processor: DocumentProcessor, tmp_path) -> None:
    chunks = await _process(
        processor, tmp_path, "notes.txt",
        lambda p: p.write_text("The quarterly revenue was $1.2 million.", encoding="utf-8"),
    )
    assert chunks
    assert "1.2 million" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_markdown(processor: DocumentProcessor, tmp_path) -> None:
    chunks = await _process(
        processor, tmp_path, "readme.md",
        lambda p: p.write_text("# Title\n\nProject Zephyr ships in Q4.", encoding="utf-8"),
    )
    assert chunks
    assert "Zephyr" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_csv(processor: DocumentProcessor, tmp_path) -> None:
    chunks = await _process(
        processor, tmp_path, "data.csv",
        lambda p: p.write_text("name,revenue\nNorthwind,184230\n", encoding="utf-8"),
    )
    assert chunks
    assert "Northwind" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_json(processor: DocumentProcessor, tmp_path) -> None:
    payload = {"project": "Aurora", "owner": "Priya Desai"}
    chunks = await _process(
        processor, tmp_path, "notes.json",
        lambda p: p.write_text(json.dumps(payload), encoding="utf-8"),
    )
    assert chunks
    assert "Priya Desai" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_xml(processor: DocumentProcessor, tmp_path) -> None:
    xml = "<config><owner>Platform Team</owner><timeout>30</timeout></config>"
    chunks = await _process(processor, tmp_path, "config.xml", lambda p: p.write_text(xml, encoding="utf-8"))
    assert chunks
    assert "Platform Team" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_html(processor: DocumentProcessor, tmp_path) -> None:
    html = "<html><head><style>.x{}</style></head><body><h1>Return Policy</h1><p>45 days</p></body></html>"
    chunks = await _process(processor, tmp_path, "policy.html", lambda p: p.write_text(html, encoding="utf-8"))
    assert chunks
    assert "45 days" in chunks[0]["content"]
    assert ".x{}" not in chunks[0]["content"]  # <style> content must be stripped


@pytest.mark.asyncio
async def test_source_code(processor: DocumentProcessor, tmp_path) -> None:
    code = "def calculate_total(items):\n    return sum(i.price for i in items)\n"
    chunks = await _process(processor, tmp_path, "billing.py", lambda p: p.write_text(code, encoding="utf-8"))
    assert chunks
    assert "calculate_total" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_docx(processor: DocumentProcessor, tmp_path) -> None:
    from docx import Document as DocxDocument

    def write(path):
        doc = DocxDocument()
        doc.add_paragraph("Employee handbook: remote work is approved company-wide.")
        doc.save(str(path))

    chunks = await _process(processor, tmp_path, "handbook.docx", write)
    assert chunks
    assert "remote work" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_pptx(processor: DocumentProcessor, tmp_path) -> None:
    from pptx import Presentation

    def write(path):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Q3 Roadmap"
        slide.placeholders[1].text = "Ship onboarding flow by September 15th."
        prs.save(str(path))

    chunks = await _process(processor, tmp_path, "roadmap.pptx", write)
    assert chunks
    assert "onboarding flow" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_xlsx(processor: DocumentProcessor, tmp_path) -> None:
    from openpyxl import Workbook

    def write(path):
        wb = Workbook()
        ws = wb.active
        ws.append(["Region", "Revenue"])
        ws.append(["Pacific Northwest", 240000])
        wb.save(str(path))

    chunks = await _process(processor, tmp_path, "sales.xlsx", write)
    assert chunks
    assert "Pacific Northwest" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_pdf(processor: DocumentProcessor, tmp_path) -> None:
    from pypdf import PdfWriter

    def write(path):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(path, "wb") as f:
            writer.write(f)

    # A blank-page PDF has no extractable text - this asserts the processor
    # degrades gracefully (empty chunk list, no exception) rather than
    # crashing, which is the behavior upload_document depends on to mark
    # the document FAILED with a clear reason instead of a 500.
    chunks = await _process(processor, tmp_path, "blank.pdf", write)
    assert chunks == []


@pytest.mark.asyncio
async def test_image_ocr_degrades_gracefully(processor: DocumentProcessor, tmp_path) -> None:
    """Without the tesseract binary installed, OCR must fail soft, not raise."""
    from PIL import Image

    def write(path):
        Image.new("RGB", (50, 50), color=(255, 255, 255)).save(str(path))

    chunks = await _process(processor, tmp_path, "photo.png", write)
    assert isinstance(chunks, list)  # empty (no OCR) or populated (OCR available) - never raises


@pytest.mark.asyncio
async def test_corrupt_file_does_not_raise(processor: DocumentProcessor, tmp_path) -> None:
    """A file whose extension claims one format but whose bytes are garbage must degrade, not crash."""
    chunks = await _process(
        processor, tmp_path, "corrupt.docx", lambda p: p.write_bytes(b"not a real docx file")
    )
    assert chunks == []


def test_supported_extensions_cover_the_documented_formats() -> None:
    """Every format the RAG feature claims to support has a real extension entry."""
    expected = {
        "pdf", "docx", "pptx", "txt", "md", "csv", "xlsx", "xls",
        "json", "xml", "html", "py", "jpg", "png",
    }
    assert expected.issubset(SUPPORTED_EXTENSIONS)
