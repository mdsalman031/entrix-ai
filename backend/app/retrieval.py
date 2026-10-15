"""Hybrid retrieval engine: dense (Qdrant) + sparse (BM25) with tenant isolation.

Architecture:
  1. Dense retrieval via Qdrant with mandatory org_id metadata filter.
  2. Sparse retrieval via BM25 with same authorization constraints.
  3. Reciprocal Rank Fusion (RRF) to combine ranked lists.
  4. Post-retrieval server-side authorization check (metadata filtering
     is an optimization, not the sole security boundary).
  5. Deduplication by chunk ID.
  6. Return typed EvidenceItem objects with full provenance.

Security invariant: unauthorized document content NEVER reaches downstream
components. If a candidate fails authorization, it is discarded before its
text is read.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np
import structlog
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Document, DocumentChunk, User
from app.schemas import EvidenceItem
from app.security import check_document_access

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)
_settings = get_settings()


# ── Embedding adapter ────────────────────────────────────────────────────


class EmbeddingModel:
    """Wrapper around sentence-transformers for embedding generation.

    Loads model lazily to avoid slow startup when not needed (e.g., tests).
    """

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or _settings.embedding_model
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        if _settings.embedding_backend == "hash":
            return [self._hash_embed(text) for text in texts]
        self._load()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def encode_query(self, query: str) -> list[float]:
        return self.encode([query])[0]

    @staticmethod
    def _hash_embed(text: str) -> list[float]:
        """Deterministic offline embedding used by the demo and test suite."""
        vector = np.zeros(_settings.embedding_dimension, dtype=np.float32)
        for token in text.lower().split():
            index = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % len(vector)
            vector[index] += 1.0
        norm = np.linalg.norm(vector)
        return (vector / norm if norm else vector).tolist()


# ── BM25 index ───────────────────────────────────────────────────────────


class BM25Index:
    """In-memory BM25 index, partitioned by organization_id for tenant isolation."""

    def __init__(self):
        # org_id -> list of (chunk_id, document_id, tokenized_text)
        self._org_docs: dict[str, list[tuple[str, str, list[str]]]] = defaultdict(list)
        self._org_index: dict[str, BM25Okapi | None] = {}

    def add_chunks(
        self,
        org_id: str,
        chunks: list[tuple[str, str, str]],  # (chunk_id, document_id, text)
    ) -> None:
        for chunk_id, doc_id, text in chunks:
            tokens = text.lower().split()
            self._org_docs[org_id].append((chunk_id, doc_id, tokens))
        self._rebuild_index(org_id)

    def remove_document(self, org_id: str, document_id: str) -> None:
        self._org_docs[org_id] = [
            (cid, did, tokens) for cid, did, tokens in self._org_docs[org_id] if did != document_id
        ]
        self._rebuild_index(org_id)

    def search(
        self,
        org_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[str, str, float]]:
        """Search BM25 index for an organization. Returns (chunk_id, doc_id, score)."""
        index = self._org_index.get(org_id)
        docs = self._org_docs.get(org_id, [])
        if index is None or not docs:
            return []

        tokens = query.lower().split()
        scores = index.get_scores(tokens)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                chunk_id, doc_id, _ = docs[idx]
                results.append((chunk_id, doc_id, float(scores[idx])))
        return results

    def _rebuild_index(self, org_id: str) -> None:
        docs = self._org_docs.get(org_id, [])
        if docs:
            corpus = [tokens for _, _, tokens in docs]
            self._org_index[org_id] = BM25Okapi(corpus)
        else:
            self._org_index[org_id] = None


# ── Retrieval Engine ─────────────────────────────────────────────────────


class RetrievalEngine:
    """Hybrid retrieval with tenant-isolated dense + sparse search.

    Combines Qdrant vector search with BM25 keyword search via Reciprocal
    Rank Fusion (RRF).
    """

    def __init__(
        self,
        qdrant_client: QdrantClient | None = None,
        embedding_model: EmbeddingModel | None = None,
        bm25_index: BM25Index | None = None,
    ):
        self.embedding_model = embedding_model or EmbeddingModel()
        self.bm25_index = bm25_index or BM25Index()

        if qdrant_client is not None:
            self.qdrant = qdrant_client
        elif _settings.qdrant_in_memory:
            self.qdrant = QdrantClient(location=":memory:")
        else:
            self.qdrant = QdrantClient(host=_settings.qdrant_host, port=_settings.qdrant_port)

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it doesn't exist."""
        collections = [c.name for c in self.qdrant.get_collections().collections]
        if _settings.qdrant_collection not in collections:
            self.qdrant.create_collection(
                collection_name=_settings.qdrant_collection,
                vectors_config=models.VectorParams(
                    size=_settings.embedding_dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("qdrant_collection_created", name=_settings.qdrant_collection)

    async def index_chunks(
        self,
        chunks: list[DocumentChunk],
        document: Document,
        organization_id: str,
        allowed_roles: list[str],
    ) -> None:
        """Index document chunks in both Qdrant and BM25."""
        if not chunks:
            return

        texts = [c.text for c in chunks]
        embeddings = self.embedding_model.encode(texts)

        # Index in Qdrant
        points = []
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            points.append(
                models.PointStruct(
                    id=chunk.embedding_id,
                    vector=embedding,
                    payload={
                        "chunk_id": chunk.id,
                        "document_id": document.id,
                        "organization_id": organization_id,
                        "allowed_roles": allowed_roles,
                        "chunk_index": chunk.chunk_index,
                        "document_title": document.title,
                        "source_id": document.source_id or "",
                    },
                )
            )
        self.qdrant.upsert(collection_name=_settings.qdrant_collection, points=points)

        # Index in BM25
        bm25_entries = [(c.id, document.id, c.text) for c in chunks]
        self.bm25_index.add_chunks(organization_id, bm25_entries)

        logger.info(
            "chunks_indexed",
            doc_id=document.id,
            count=len(chunks),
            org_id=organization_id,
        )

    async def delete_document_vectors(self, document_id: str) -> None:
        """Remove all vectors for a document from Qdrant."""
        self.qdrant.delete(
            collection_name=_settings.qdrant_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        ),
                    ]
                )
            ),
        )

    async def hydrate(self, db: AsyncSession) -> None:
        """Rebuild in-memory indexes from trusted relational document records.

        This is required when the local Qdrant instance is in-memory: metadata
        survives in SQLite but its vector and BM25 indexes do not.
        """
        self.bm25_index = BM25Index()
        result = await db.execute(select(Document))
        for document in result.scalars().all():
            await self.index_chunks(
                list(document.chunks),
                document,
                document.organization_id,
                list(document.allowed_roles) if isinstance(document.allowed_roles, list) else [],
            )

    async def search(
        self,
        query: str,
        user: User,
        db: AsyncSession,
        top_k: int | None = None,
    ) -> list[EvidenceItem]:
        """Execute hybrid retrieval with full authorization enforcement.

        Steps:
        1. Dense search in Qdrant with org_id metadata filter.
        2. BM25 keyword search with org_id partition.
        3. Reciprocal Rank Fusion to combine rankings.
        4. Server-side authorization check on each candidate.
        5. Return authorized EvidenceItem objects only.
        """
        k = top_k or _settings.retrieval_top_k
        org_id = user.organization_id

        # ── Dense retrieval (Qdrant) ──────────────────────────────────
        query_vector = self.embedding_model.encode_query(query)

        try:
            qdrant_results = self.qdrant.query_points(
                collection_name=_settings.qdrant_collection,
                query=query_vector,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="organization_id",
                            match=models.MatchValue(value=org_id),
                        ),
                    ]
                ),
                limit=k * 2,  # Over-fetch for fusion
            ).points
        except Exception as e:
            logger.error("qdrant_search_failed", error=str(e))
            qdrant_results = []

        # ── Sparse retrieval (BM25) ───────────────────────────────────
        bm25_results = self.bm25_index.search(org_id, query, top_k=k * 2)

        # ── Reciprocal Rank Fusion ────────────────────────────────────
        rrf_scores: dict[str, float] = defaultdict(float)
        chunk_meta: dict[str, dict] = {}
        rrf_k = 60  # Standard RRF constant

        for rank, hit in enumerate(qdrant_results):
            chunk_id = hit.payload.get("chunk_id", "")
            rrf_scores[chunk_id] += 1.0 / (rrf_k + rank + 1)
            chunk_meta[chunk_id] = {
                "document_id": hit.payload.get("document_id", ""),
                "document_title": hit.payload.get("document_title", ""),
                "chunk_index": hit.payload.get("chunk_index", 0),
                "source_id": hit.payload.get("source_id"),
                "score": hit.score if hit.score else 0.0,
            }

        for rank, (chunk_id, doc_id, bm25_score) in enumerate(bm25_results):
            rrf_scores[chunk_id] += 1.0 / (rrf_k + rank + 1)
            if chunk_id not in chunk_meta:
                chunk_meta[chunk_id] = {
                    "document_id": doc_id,
                    "document_title": "",
                    "chunk_index": 0,
                    "source_id": None,
                    "score": bm25_score,
                }

        # Sort by fused score
        sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        # ── Server-side authorization ─────────────────────────────────
        # Load documents for authorization check
        doc_ids = list({meta["document_id"] for meta in chunk_meta.values()})
        result = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        documents = {doc.id: doc for doc in result.scalars().all()}

        # Do not load a chunk record (which contains text) until the trusted
        # document authorization check has passed. Vector payload is metadata-only.
        chunk_ids = [
            chunk_id
            for chunk_id, _ in sorted_chunks
            if (document := documents.get(chunk_meta.get(chunk_id, {}).get("document_id", "")))
            and check_document_access(user, document)
        ][: k * 2]
        chunk_result = await db.execute(
            select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
        )
        chunk_texts = {c.id: c for c in chunk_result.scalars().all()}

        authorized_evidence: list[EvidenceItem] = []
        unauthorized_count = 0

        for chunk_id, fused_score in sorted_chunks:
            if len(authorized_evidence) >= k:
                break

            meta = chunk_meta.get(chunk_id, {})
            doc_id = meta.get("document_id", "")
            doc = documents.get(doc_id)

            # SECURITY: Server-side authorization check
            if doc is None or not check_document_access(user, doc):
                unauthorized_count += 1
                logger.warning(
                    "unauthorized_candidate_filtered",
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    user_id=user.id,
                    # Never log the restricted content
                )
                continue

            chunk_record = chunk_texts.get(chunk_id)
            if chunk_record is None:
                continue

            authorized_evidence.append(
                EvidenceItem(
                    evidence_id=chunk_id,
                    document_id=doc_id,
                    document_title=doc.title,
                    chunk_index=chunk_record.chunk_index,
                    text=chunk_record.text,
                    score=round(fused_score, 4),
                    source_id=doc.source_id,
                )
            )

        if unauthorized_count > 0:
            logger.info(
                "retrieval_unauthorized_filtered",
                filtered_count=unauthorized_count,
                user_id=user.id,
                org_id=org_id,
            )

        return authorized_evidence
