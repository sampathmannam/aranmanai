"""RAG (retrieval-augmented generation) over BNS/BNSS/BSA + similar cases.

Uses ChromaDB for vector storage. v1 indexes:
- BNS sections (Bharatiya Nyaya Sanhita 2023)
- BNSS sections (Bharatiya Nagarik Suraksha Sanhita 2023)
- BSA sections (Bharatiya Sakshya Adhiniyam 2023)
- A small corpus of prior HC/SC judgments (will be added in Phase 2)

v1 status: scaffolding. The retriever is wired; the corpus ingestion
script is at scripts/ingest_corpus.py (to be added in Phase 2 day 3-4).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.aranmanai.config import settings
from src.aranmanai.logging_config import get_logger

log = get_logger(__name__)

# Lazy import to avoid hard chromadb dependency on import
_chromadb = None
_chroma_client = None
_chroma_collection = None


def _ensure_chromadb() -> bool:
    """Initialize ChromaDB client + collection. Idempotent. Returns True on success."""
    global _chromadb, _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return True
    try:
        import chromadb
        _chromadb = chromadb
    except ImportError:
        log.warning("chromadb not installed; RAG unavailable")
        return False
    try:
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        _chroma_client = _chromadb.PersistentClient(path=str(settings.chroma_dir))
        _chroma_collection = _chroma_client.get_or_create_collection(
            name="aranmanai_corpus",
            metadata={"hnsw:space": "cosine"},
        )
        log.info("rag.ready chroma_dir=%s count=%s", settings.chroma_dir, _chroma_collection.count())
        return True
    except Exception as e:
        log.error("rag.init failed: %s", e)
        return False


def retrieve(query: str, n_results: int = 5, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Retrieve top-k documents for the query. Returns list of {text, metadata, distance}.

    Returns empty list if RAG is unavailable or no hits.
    """
    if not _ensure_chromadb() or _chroma_collection is None:
        return []
    try:
        res = _chroma_collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        return [
            {"text": d, "metadata": m or {}, "distance": dist}
            for d, m, dist in zip(docs, metas, dists)
        ]
    except Exception as e:
        log.error("rag.retrieve failed: %s", e)
        return []


def add_documents(
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    ids: list[str] | None = None,
) -> bool:
    """Add documents to the corpus. Idempotent (upsert by id)."""
    if not _ensure_chromadb() or _chroma_collection is None:
        return False
    try:
        kwargs: dict[str, Any] = {"documents": texts}
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        if ids is not None:
            kwargs["ids"] = ids
        _chroma_collection.upsert(**kwargs)
        log.info("rag.added n=%s", len(texts))
        return True
    except Exception as e:
        log.error("rag.add failed: %s", e)
        return False


def corpus_size() -> int:
    """Current number of documents in the corpus."""
    if not _ensure_chromadb() or _chroma_collection is None:
        return 0
    return _chroma_collection.count()
