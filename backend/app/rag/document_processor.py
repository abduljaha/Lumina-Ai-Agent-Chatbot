"""Document processing - loading, chunking, and metadata extraction."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("app")

# File extensions this processor can turn into indexable text. Shared with
# the upload endpoint's allow-list (see files.py) so the two can't drift
# apart - an extension accepted there but not handled here would silently
# index zero content, and one handled here but rejected there would just be
# dead code.
CODE_EXTENSIONS = {
    "py", "js", "jsx", "ts", "tsx", "java", "c", "cpp", "h", "hpp", "cs",
    "go", "rs", "rb", "php", "swift", "kt", "sql", "sh", "yaml", "yml",
    "toml", "ini", "css", "scss",
}
SUPPORTED_EXTENSIONS = (
    {"pdf", "docx", "pptx", "txt", "md", "csv", "xlsx", "xls", "json", "xml", "html", "htm"}
    | CODE_EXTENSIONS
    | {"jpg", "jpeg", "png", "webp"}
)


class DocumentProcessor:
    """Loads, chunks, and extracts metadata from uploaded documents.

    Supported types: PDF, DOCX, PPTX, TXT/Markdown, CSV, Excel (XLSX/XLS),
    JSON, XML, HTML, source code files (treated as plain text), and images
    (via OCR). Anything not explicitly handled below still falls through to
    a plain-text read, so it degrades rather than hard-fails.
    """

    CHUNK_SIZE = 800
    CHUNK_OVERLAP = 100

    def __init__(self, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> None:
        self._splitter = None
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            self._splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "langchain_text_splitters not available; using fallback splitter: %s",
                exc,
            )

    async def process(self, file_path: str, filename: str) -> list[dict[str, Any]]:
        """Process a file and return chunks with metadata."""
        file_ext = Path(filename).suffix.lower().lstrip(".")
        text = await self._extract_text(file_path, file_ext)

        if not text.strip():
            logger.warning("No text extracted from %s", filename)
            return []

        if self._splitter is not None:
            chunks = self._splitter.split_text(text)
        else:
            chunks = self._fallback_split_text(text)
        results = []
        for i, chunk in enumerate(chunks):
            results.append(
                {
                    "content": chunk,
                    "chunk_index": i,
                    "source": filename,
                    "metadata": self._extract_metadata(chunk, filename, i, file_ext),
                }
            )
        logger.info("Processed %s into %d chunks", filename, len(chunks))
        return results

    async def _extract_text(self, file_path: str, file_ext: str) -> str:
        """Extract text from a file based on its extension."""
        if file_ext == "pdf":
            return await self._extract_pdf(file_path)
        if file_ext == "docx":
            return await self._extract_docx(file_path)
        if file_ext == "pptx":
            return await self._extract_pptx(file_path)
        if file_ext in ("txt", "md", "csv", "json") or file_ext in CODE_EXTENSIONS:
            # JSON and source files are already human-readable plain text -
            # no structural parsing needed to make them embeddable/searchable.
            return await self._extract_text_simple(file_path)
        if file_ext in ("xlsx", "xls"):
            return await self._extract_excel(file_path)
        if file_ext == "xml":
            return await self._extract_xml(file_path)
        if file_ext in ("html", "htm"):
            return await self._extract_html(file_path)
        if file_ext in ("jpg", "jpeg", "png", "webp"):
            return await self._extract_ocr(file_path)
        if file_ext in ("zip", "mp3", "wav", "mp4"):
            return await self._extract_unsupported(file_path)
        return await self._extract_text_simple(file_path)

    async def _extract_pdf(self, file_path: str) -> str:
        """Extract text from a PDF."""
        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:  # noqa: BLE001
            logger.error("PDF extraction failed: %s", exc)
            return ""

    async def _extract_docx(self, file_path: str) -> str:
        """Extract text from a DOCX file."""
        try:
            from docx import Document

            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs if p.text)
        except Exception as exc:  # noqa: BLE001
            logger.error("DOCX extraction failed: %s", exc)
            return ""

    async def _extract_pptx(self, file_path: str) -> str:
        """Extract text from a PowerPoint file, slide by slide."""
        try:
            from pptx import Presentation

            prs = Presentation(file_path)
            slides = []
            for i, slide in enumerate(prs.slides):
                texts = [
                    shape.text_frame.text
                    for shape in slide.shapes
                    if shape.has_text_frame and shape.text_frame.text.strip()
                ]
                if texts:
                    slides.append(f"[Slide {i + 1}]\n" + "\n".join(texts))
            return "\n\n".join(slides)
        except Exception as exc:  # noqa: BLE001
            logger.error("PPTX extraction failed: %s", exc)
            return ""

    async def _extract_xml(self, file_path: str) -> str:
        """Extract visible text content from an XML file, tags stripped."""
        try:
            from xml.etree import ElementTree

            tree = ElementTree.parse(file_path)
            parts = [node.strip() for node in tree.getroot().itertext() if node and node.strip()]
            return "\n".join(parts)
        except Exception as exc:  # noqa: BLE001
            logger.error("XML extraction failed: %s", exc)
            return ""

    async def _extract_html(self, file_path: str) -> str:
        """Extract visible text content from an HTML file, tags/scripts/styles stripped."""
        try:
            from bs4 import BeautifulSoup

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)
        except Exception as exc:  # noqa: BLE001
            logger.error("HTML extraction failed: %s", exc)
            return ""

    async def _extract_text_simple(self, file_path: str) -> str:
        """Extract text from a simple text file."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as exc:  # noqa: BLE001
            logger.error("Text extraction failed: %s", exc)
            return ""

    async def _extract_excel(self, file_path: str) -> str:
        """Extract text from an Excel file."""
        try:
            import pandas as pd

            dfs = pd.read_excel(file_path, sheet_name=None)
            parts = []
            for sheet_name, df in dfs.items():
                parts.append(f"Sheet: {sheet_name}\n{df.to_string()}")
            return "\n\n".join(parts)
        except Exception as exc:  # noqa: BLE001
            logger.error("Excel extraction failed: %s", exc)
            return ""

    async def _extract_ocr(self, file_path: str) -> str:
        """Extract text from an image using OCR."""
        try:
            import pytesseract
            from PIL import Image

            image = Image.open(file_path)
            return pytesseract.image_to_string(image)
        except Exception as exc:  # noqa: BLE001
            logger.error("OCR extraction failed: %s", exc)
            return ""

    async def _extract_unsupported(self, file_path: str) -> str:
        """Handle unsupported file types gracefully."""
        return ""

    def _fallback_split_text(self, text: str) -> list[str]:
        """Fallback text splitter when langchain_text_splitters is unavailable."""
        if not text:
            return []
        sentences = text.split("\n\n")
        chunks: list[str] = []
        current = []
        current_len = 0
        for paragraph in sentences:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            paragraph_len = len(paragraph)
            if current_len + paragraph_len + 1 > self.CHUNK_SIZE and current:
                chunks.append("\n\n".join(current))
                current = [paragraph]
                current_len = paragraph_len
            else:
                current.append(paragraph)
                current_len += paragraph_len + 2
        if current:
            chunks.append("\n\n".join(current))
        return chunks

    def _extract_metadata(self, chunk: str, filename: str, index: int, file_type: str = "") -> dict[str, Any]:
        """Extract metadata from a chunk.

        `file_type` is stored so retrieval can filter by it (e.g. "only
        search my spreadsheets") - see Retriever.retrieve's `filters` param.
        """
        words = len(chunk.split())
        return {
            "chunk_index": index,
            "filename": filename,
            "file_type": file_type,
            "word_count": words,
            "char_count": len(chunk),
        }
