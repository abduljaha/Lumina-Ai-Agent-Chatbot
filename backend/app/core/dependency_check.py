"""Startup dependency validation for the RAG file-ingestion pipeline.

Checked here (in the running app process itself), not just in the dev
launcher script (`scripts/run-dev.ps1`) - that script only protects the
`run-dev.ps1` entry point. A production deployment, a container, or anyone
running `uvicorn` by hand bypasses it entirely, and the previous failure mode
("No module named 'pypdf'") only ever surfaced per-upload, deep in a stack
trace, with no signal at boot that the interpreter running the app was
missing packages its own requirements.txt declares.
"""
from __future__ import annotations

import importlib
import logging

logger = logging.getLogger("app")

# name -> (import name, human label). Only the packages document_processor.py
# actually imports for parsing/OCR - not the whole requirements.txt, which
# would just be re-implementing `pip check`.
_RAG_DEPENDENCIES: dict[str, str] = {
    "pypdf": "PDF parsing",
    "docx": "DOCX parsing (python-docx)",
    "pptx": "PPTX parsing (python-pptx)",
    "openpyxl": "XLSX parsing",
    "pandas": "CSV/XLSX parsing",
    "bs4": "HTML parsing (beautifulsoup4)",
    "fitz": "PDF page rendering for OCR (PyMuPDF)",
    "PIL": "Image handling (Pillow)",
    "rapidocr_onnxruntime": "OCR (primary engine)",
}

# Not fatal if missing - pytesseract is only the secondary OCR fallback
# behind RapidOCR (see document_processor.ocr_image), and needs a system
# Tesseract binary this environment may not have installed.
_OPTIONAL_DEPENDENCIES: dict[str, str] = {
    "pytesseract": "OCR (secondary fallback engine, needs system Tesseract)",
}


def check_rag_dependencies() -> dict[str, bool]:
    """Import-check every RAG parsing/OCR dependency and log the result.

    Returns a {package: importable} map - used both for the startup log and
    surfaced on GET /health so a missing dependency is visible without
    digging through logs or waiting for a user's upload to fail.
    """
    status: dict[str, bool] = {}

    missing_required: list[str] = []
    for module_name, label in _RAG_DEPENDENCIES.items():
        try:
            importlib.import_module(module_name)
            status[module_name] = True
        except ImportError:
            status[module_name] = False
            missing_required.append(f"{module_name} ({label})")

    for module_name, label in _OPTIONAL_DEPENDENCIES.items():
        try:
            importlib.import_module(module_name)
            status[module_name] = True
        except ImportError:
            status[module_name] = False
            logger.info("Optional RAG dependency '%s' not available: %s - continuing without it.", module_name, label)

    if missing_required:
        logger.error(
            "RAG file-ingestion is DEGRADED - missing required dependencies: %s. "
            "Uploads of the affected file types will fail until this is fixed. "
            "Run: pip install -r requirements.txt (into the interpreter actually running this process).",
            ", ".join(missing_required),
        )
    else:
        logger.info("RAG dependency check passed - all %d required packages importable.", len(_RAG_DEPENDENCIES))

    return status
