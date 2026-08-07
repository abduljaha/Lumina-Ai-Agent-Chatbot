"""File upload and management endpoints."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from app.api.deps import CurrentUser, DbDep
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.db.models import Document, DocumentStatus, File as FileModel
from app.repositories import DocumentRepository, FileRepository
from app.schemas.models import DocumentList, DocumentRead, FileUploadResponse

settings = get_settings()
router = APIRouter()
logger = logging.getLogger("app")


def _get_ext(filename: str) -> str:
    """Get the file extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower().lstrip(".")


@router.post("/upload", response_model=FileUploadResponse, summary="Upload a file")
async def upload_file(
    file: UploadFile = File(...),
    user: CurrentUser = None,
    db: DbDep = None,
) -> FileUploadResponse:
    """Upload a file (document, image, audio, video)."""
    ext = _get_ext(file.filename or "unknown")
    if ext not in settings.allowed_extensions:
        raise ValidationError(f"File type '.{ext}' is not allowed")

    # Determine category
    imgs = {"jpg", "jpeg", "png", "webp", "gif", "svg"}
    audios = {"mp3", "wav", "ogg", "m4a", "flac"}
    videos = {"mp4", "avi", "mov", "mkv", "webm"}
    if ext in imgs:
        category = "image"
    elif ext in audios:
        category = "audio"
    elif ext in videos:
        category = "video"
    else:
        category = "document"

    # Save file
    upload_dir = settings.upload_path
    stored_name = f"{uuid.uuid4()}.{ext}"
    stored_path = upload_dir / stored_name

    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise ValidationError(f"File size exceeds {settings.max_upload_size_mb}MB limit")

    stored_path.write_bytes(content)

    # Persist file record
    file_repo = FileRepository(db)
    file_record = FileModel(
        user_id=user.id,
        filename=file.filename or stored_name,
        stored_path=str(stored_path),
        content_type=file.content_type or "application/octet-stream",
        size=len(content),
        category=category,
    )
    await file_repo.create(file_record)
    await file_repo.commit()

    return FileUploadResponse(
        file_id=str(file_record.id),
        filename=file_record.filename,
        content_type=file_record.content_type,
        size=file_record.size,
        url=f"/uploads/{stored_name}",
        category=category,
    )


@router.post("/documents", response_model=DocumentRead, summary="Upload and index a document")
async def upload_document(
    file: UploadFile = File(...),
    # Optional: ties this document to the conversation it was uploaded from,
    # so RAGRetrievalNode can deterministically surface it for vague
    # in-thread questions ("describe this file") instead of relying on
    # semantic search to guess which of the user's many documents is meant -
    # see the node for the retrieval side of this. Not required, since a
    # document can also be uploaded with no conversation context.
    thread_id: str | None = Form(None),
    user: CurrentUser = None,
    db: DbDep = None,
) -> DocumentRead:
    """Upload a document and index it for RAG."""
    from app.rag.document_processor import SUPPORTED_EXTENSIONS

    ext = _get_ext(file.filename or "unknown")
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValidationError(f"Unsupported document type: .{ext}")

    if thread_id:
        from app.repositories import ThreadRepository

        thread = await ThreadRepository(db).get(thread_id)
        if not thread or thread.user_id != user.id:
            # Don't let a stale/foreign thread_id silently misfile the
            # upload as belonging to someone else's (or no) conversation -
            # but a bad thread reference shouldn't block the upload either,
            # so it just falls back to unscoped rather than raising.
            logger.warning("Upload's thread_id %s not found or not owned by user %s", thread_id, user.id)
            thread_id = None

    # Save the file
    upload_dir = settings.upload_path
    stored_name = f"{uuid.uuid4()}.{ext}"
    stored_path = upload_dir / stored_name
    content = await file.read()
    if not content:
        raise ValidationError("The uploaded file is empty")
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise ValidationError(f"File size exceeds {settings.max_upload_size_mb}MB limit")
    stored_path.write_bytes(content)

    # Create document record (processing state)
    doc_repo = DocumentRepository(db)
    document = Document(
        user_id=user.id,
        thread_id=thread_id,
        filename=file.filename or stored_name,
        file_path=str(stored_path),
        file_type=ext,
        file_size=len(content),
        status=DocumentStatus.PROCESSING,
    )
    await doc_repo.create(document)
    logger.info(
        "Document upload started: id=%s filename=%s type=%s size=%d thread_id=%s user_id=%s",
        document.id, document.filename, ext, len(content), thread_id, user.id,
    )

    # Process and embed (in production, this runs as a background task)
    try:
        from app.rag.document_processor import DocumentProcessor
        from app.core.container import app_container

        processor = DocumentProcessor()
        chunks = await processor.process(str(stored_path), document.filename)
        logger.info("Document %s: extracted %d chunk(s)", document.id, len(chunks))

        if not chunks:
            # Extraction ran without raising but produced nothing usable
            # (empty/corrupt file, unsupported content inside a supported
            # extension, OCR unavailable, ...) - this must NOT be reported
            # as READY: a "successful" document with zero retrievable
            # content is exactly what produces "I don't see any file" once
            # a question about it reaches the LLM with empty RAG context.
            document.status = DocumentStatus.FAILED
            document.metadata_ = {
                **document.metadata_,
                "error": "No text could be extracted from this file. It may be empty, "
                "corrupted, image-based without OCR support, or in an unexpected format.",
            }
            await doc_repo.update(document)
            await doc_repo.commit()
            logger.warning("Document %s marked FAILED: no extractable text", document.id)
            return DocumentRead.model_validate(document)

        embedder = app_container.get_embedder()
        texts = [chunk["content"] for chunk in chunks]
        embeddings = await embedder.embed(texts)
        logger.info(
            "Document %s: embedded %d chunk(s) via backend=%s",
            document.id, len(embeddings), getattr(embedder, "_backend", "unknown"),
        )

        for chunk in chunks:
            # The processor only numbers chunks *within* one document
            # (0, 1, 2, ...) - without the document id prefixed in, a
            # second upload's chunk 0 collides with the first upload's
            # chunk 0 in the vector store and silently overwrites it.
            chunk["id"] = f"{document.id}_{chunk['chunk_index']}"
            chunk["document_id"] = str(document.id)
            # Vector search has no inherent per-user boundary - without
            # this tag, retrieval can't scope results to the owner and
            # every user's documents become searchable by every other
            # user (see Retriever.retrieve).
            metadata = chunk.setdefault("metadata", {})
            metadata["user_id"] = user.id
            if thread_id:
                metadata["thread_id"] = thread_id

        vector_store = app_container.get_vector_store()
        await vector_store.add_documents(chunks, embeddings)

        document.chunk_count = len(chunks)
        document.status = DocumentStatus.READY
        logger.info(
            "Document %s ready: %d chunk(s) indexed (thread_id=%s)",
            document.id, document.chunk_count, thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Document %s processing failed", document.id)
        document.status = DocumentStatus.FAILED
        # Reassigned (not mutated in place) - SQLAlchemy's plain JSON column
        # type doesn't track in-place dict mutation as a pending change, so
        # `document.metadata_["error"] = ...` was silently never persisted.
        document.metadata_ = {**document.metadata_, "error": str(exc)}

    await doc_repo.update(document)
    await doc_repo.commit()
    return DocumentRead.model_validate(document)


@router.get("/documents", response_model=DocumentList, summary="List uploaded documents")
async def list_documents(
    user: CurrentUser,
    db: DbDep,
) -> DocumentList:
    """List all documents uploaded by the current user."""
    doc_repo = DocumentRepository(db)
    from sqlalchemy import select

    stmt = select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
    result = await db.execute(stmt)
    docs = list(result.scalars().all())
    return DocumentList(
        items=[DocumentRead.model_validate(d) for d in docs],
        total=len(docs),
    )


# response_model=None required alongside status_code=204 - see threads.py's
# delete_thread for why "-> None" alone isn't enough under this file's
# `from __future__ import annotations`.
@router.delete("/documents/{document_id}", status_code=204, response_model=None, summary="Delete a document")
async def delete_document(
    document_id: str,
    user: CurrentUser,
    db: DbDep,
) -> None:
    """Delete a document and its embeddings."""
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.get(document_id)
    if doc and doc.user_id == user.id:
        # Clean up file
        if doc.file_path and Path(doc.file_path).exists():
            Path(doc.file_path).unlink()
        # Without this, a "deleted" document's chunks stay searchable in the
        # vector store forever - the DB record disappears but RAG answers
        # can still surface (and cite) content the user just removed.
        if doc.chunk_count:
            from app.core.container import app_container

            vector_store = app_container.get_vector_store()
            ids = [f"{doc.id}_{i}" for i in range(doc.chunk_count)]
            await vector_store.delete_ids(ids)
        await doc_repo.delete(doc)
        await doc_repo.commit()
