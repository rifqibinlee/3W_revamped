"""PDF ingestion and similarity search for the agent's knowledge base.

Ports `s3_ingest.py`'s chunk/embed/store flow, minus the S3-specific
download step (this takes a local file path; whatever serves the file —
S3, MinIO, an upload endpoint — is the router's concern, not this
service's).

`embeddings_provider` is injectable (same pattern as genset.py's
`graph_provider`) so tests don't need a running Ollama server.
"""

from collections.abc import Callable

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm import get_embeddings
from app.rag.models import KnowledgeChunk

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

EmbeddingsProvider = Callable[[list[str]], list[list[float]]]


def _default_embed_documents(texts: list[str]) -> list[list[float]]:
    return get_embeddings().embed_documents(texts)


def _default_embed_query(text: str) -> list[float]:
    return get_embeddings().embed_query(text)


def extract_pages(pdf_path: str) -> list[tuple[int, str]]:
    """Returns [(page_number, text), ...], 1-indexed pages, skipping blank ones."""
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((i, text))
    return pages


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    return splitter.split_text(text)


def ingest_pdf(
    db: Session,
    pdf_path: str,
    source_name: str,
    embed_documents: EmbeddingsProvider = _default_embed_documents,
) -> int:
    """Extracts, chunks, embeds, and stores every page of a PDF. Returns
    the number of chunks stored."""
    chunks_with_pages: list[tuple[int, str]] = []
    for page_number, page_text in extract_pages(pdf_path):
        for chunk in chunk_text(page_text):
            chunks_with_pages.append((page_number, chunk))

    if not chunks_with_pages:
        return 0

    embeddings = embed_documents([c for _, c in chunks_with_pages])

    for (page_number, chunk_text_), embedding in zip(chunks_with_pages, embeddings):
        db.add(KnowledgeChunk(source=source_name, page=page_number, content=chunk_text_, embedding=embedding))
    db.commit()
    return len(chunks_with_pages)


def search(
    db: Session,
    query: str,
    top_k: int = 5,
    embed_query: Callable[[str], list[float]] = _default_embed_query,
) -> list[KnowledgeChunk]:
    """Ranks every stored chunk by cosine similarity to the query
    embedding, in Python — see the module/model docstring for why this
    isn't a pgvector <=> query."""
    chunks = list(db.scalars(select(KnowledgeChunk)))
    if not chunks:
        return []

    query_vec = np.array(embed_query(query))
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return []

    def similarity(chunk: KnowledgeChunk) -> float:
        chunk_vec = np.array(chunk.embedding)
        chunk_norm = np.linalg.norm(chunk_vec)
        if chunk_norm == 0:
            return -1.0
        return float(np.dot(query_vec, chunk_vec) / (query_norm * chunk_norm))

    ranked = sorted(chunks, key=similarity, reverse=True)
    return ranked[:top_k]
