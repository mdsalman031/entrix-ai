"""Document ingestion pipeline.

Handles text extraction, deterministic chunking, embedding generation, and
indexing into both Qdrant (dense vectors) and BM25 (keyword search).

Chunking is deterministic for reproducibility: given the same input, chunk
size, and overlap, the output chunks are identical.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Document, DocumentChunk

if TYPE_CHECKING:
    from app.retrieval import RetrievalEngine

logger = structlog.get_logger(__name__)
_settings = get_settings()


# ── Text chunking ────────────────────────────────────────────────────────


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[str]:
    """Split text into chunks by character count with overlap.

    Deterministic: same input always produces the same output.
    Splits on whitespace boundaries to avoid cutting words.
    """
    size = chunk_size or _settings.chunk_size
    overlap = chunk_overlap or _settings.chunk_overlap

    if not text.strip():
        return []

    words = text.split()
    chunks: list[str] = []
    current_words: list[str] = []
    current_len = 0

    for word in words:
        word_len = len(word) + (1 if current_words else 0)
        if current_len + word_len > size and current_words:
            chunks.append(" ".join(current_words))
            # Keep overlap worth of characters from the end
            overlap_words: list[str] = []
            overlap_len = 0
            for w in reversed(current_words):
                if overlap_len + len(w) + 1 > overlap:
                    break
                overlap_words.insert(0, w)
                overlap_len += len(w) + 1
            current_words = overlap_words
            current_len = sum(len(w) for w in current_words) + max(0, len(current_words) - 1)
        current_words.append(word)
        current_len += word_len

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


def compute_content_hash(content: str) -> str:
    """SHA-256 hash of document content for deduplication."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ── Ingestion pipeline ───────────────────────────────────────────────────


async def ingest_document(
    db: AsyncSession,
    retrieval_engine: RetrievalEngine,
    *,
    organization_id: str,
    title: str,
    content: str,
    source_id: str | None = None,
    allowed_roles: list[str] | None = None,
) -> Document:
    """Ingest a document: chunk, embed, index, persist metadata.

    If a document with the same source_id exists for this org, it is replaced
    (version incremented, old chunks deleted, re-indexed).
    """
    if allowed_roles is None:
        allowed_roles = ["viewer", "editor", "admin"]

    content_hash = compute_content_hash(content)

    # Check for existing document by source_id
    existing_doc = None
    if source_id:
        result = await db.execute(
            select(Document).where(
                Document.organization_id == organization_id,
                Document.source_id == source_id,
            )
        )
        existing_doc = result.scalar_one_or_none()

    if existing_doc is not None:
        # Version-aware replacement
        logger.info("replacing_document", doc_id=existing_doc.id, source_id=source_id)
        # Delete old chunks from vector store
        await retrieval_engine.delete_document_vectors(existing_doc.id)
        retrieval_engine.bm25_index.remove_document(organization_id, existing_doc.id)
        # Delete old chunks from DB
        for chunk in existing_doc.chunks:
            await db.delete(chunk)

        existing_doc.title = title
        existing_doc.content_hash = content_hash
        existing_doc.allowed_roles = allowed_roles
        existing_doc.version += 1
        doc = existing_doc
    else:
        doc = Document(
            organization_id=organization_id,
            title=title,
            source_id=source_id,
            content_hash=content_hash,
            allowed_roles=allowed_roles,
        )
        db.add(doc)

    await db.flush()  # Get doc.id

    # Chunk the content
    chunks_text = chunk_text(content)
    doc.chunk_count = len(chunks_text)

    # Create chunk records and collect for embedding
    chunk_records: list[DocumentChunk] = []
    for idx, text in enumerate(chunks_text):
        chunk = DocumentChunk(
            document_id=doc.id,
            chunk_index=idx,
            text=text,
            embedding_id=str(uuid.uuid4()),
        )
        db.add(chunk)
        chunk_records.append(chunk)

    await db.flush()

    # Index in vector store and BM25
    await retrieval_engine.index_chunks(
        chunks=chunk_records,
        document=doc,
        organization_id=organization_id,
        allowed_roles=allowed_roles,
    )

    logger.info(
        "document_ingested",
        doc_id=doc.id,
        title=title,
        chunks=len(chunks_text),
        org_id=organization_id,
    )

    return doc


async def delete_document(
    db: AsyncSession,
    retrieval_engine: RetrievalEngine,
    document: Document,
) -> None:
    """Delete a document and all its chunks from the database and vector store."""
    await retrieval_engine.delete_document_vectors(document.id)
    await db.delete(document)
    logger.info("document_deleted", doc_id=document.id)
