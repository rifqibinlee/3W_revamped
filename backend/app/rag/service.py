"""Document ingestion and full-text search for the agent's knowledge base.

Supports PDFs and Excel workbooks. Retrieval uses PostgreSQL built-in
full-text search (to_tsvector / plainto_tsquery) — no pgvector extension
or Ollama embeddings required.
"""

import io
import tempfile
import os

import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.rag.models import KnowledgeChunk

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


# ── PDF ingestion ──────────────────────────────────────────────────────────────

def extract_pages(pdf_path: str) -> list[tuple[int, str]]:
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        t = page.extract_text() or ""
        if t.strip():
            pages.append((i, t))
    return pages


def ingest_pdf(db: Session, pdf_path: str, source_name: str) -> int:
    chunks_stored = 0
    for page_number, page_text in extract_pages(pdf_path):
        for chunk in _splitter.split_text(page_text):
            db.add(KnowledgeChunk(source=source_name, page=page_number, content=chunk))
            chunks_stored += 1
    db.commit()
    return chunks_stored


# ── Excel ingestion ────────────────────────────────────────────────────────────

def ingest_excel(db: Session, file_path: str, source_name: str) -> int:
    """Reads every sheet of an Excel file and stores each row as a chunk.

    Rows are serialised as "col: value | col: value …" strings so the
    agent can retrieve them with plain text search.
    """
    xls = pd.ExcelFile(file_path)
    chunks_stored = 0
    for sheet in xls.sheet_names:
        df = xls.parse(sheet).fillna("")
        for _, row in df.iterrows():
            line = " | ".join(f"{col}: {val}" for col, val in row.items() if str(val).strip())
            if not line.strip():
                continue
            for chunk in _splitter.split_text(line):
                db.add(KnowledgeChunk(source=f"{source_name}:{sheet}", page=None, content=chunk))
                chunks_stored += 1
    db.commit()
    return chunks_stored


# ── S3 training-data sync ──────────────────────────────────────────────────────

def sync_from_s3(db: Session) -> dict[str, int]:
    """Downloads all PDFs and Excels from the training-data S3 prefixes and
    ingests any that haven't been ingested yet (checked by source name).

    Returns {source_name: chunks_added} for newly ingested files.
    """
    from app.core.config import settings
    from app.ingestion.storage import get_s3_client, list_objects

    existing: set[str] = set(db.scalars(select(KnowledgeChunk.source).distinct()))
    client = get_s3_client()
    bucket = settings.s3_bucket
    results: dict[str, int] = {}

    pdf_keys = list_objects(bucket, settings.s3_train_pdf_prefix)
    excel_keys = list_objects(bucket, settings.s3_train_excel_prefix)

    for key in pdf_keys:
        source_name = key.split("/")[-1]
        if source_name in existing:
            continue
        suffix = os.path.splitext(key)[1] or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        try:
            client.download_file(bucket, key, tmp_path)
            n = ingest_pdf(db, tmp_path, source_name)
            results[source_name] = n
        finally:
            os.remove(tmp_path)

    for key in excel_keys:
        source_name = key.split("/")[-1]
        if source_name in existing:
            continue
        suffix = os.path.splitext(key)[1] or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        try:
            client.download_file(bucket, key, tmp_path)
            n = ingest_excel(db, tmp_path, source_name)
            results[source_name] = n
        finally:
            os.remove(tmp_path)

    return results


# ── Search ─────────────────────────────────────────────────────────────────────

def search(db: Session, query: str, top_k: int = 5) -> list[KnowledgeChunk]:
    """Full-text search over knowledge chunks using PostgreSQL tsvector.

    Falls back to a ILIKE substring match if FTS returns nothing, so short
    or single-term queries still get results.
    """
    fts_sql = text(
        "SELECT id FROM knowledge_chunks "
        "WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :q) "
        "ORDER BY ts_rank(to_tsvector('english', content), plainto_tsquery('english', :q)) DESC "
        "LIMIT :k"
    )
    rows = db.execute(fts_sql, {"q": query, "k": top_k}).fetchall()
    ids = [r[0] for r in rows]

    if not ids:
        like_sql = text(
            "SELECT id FROM knowledge_chunks WHERE content ILIKE :pat LIMIT :k"
        )
        rows = db.execute(like_sql, {"pat": f"%{query}%", "k": top_k}).fetchall()
        ids = [r[0] for r in rows]

    if not ids:
        return []
    return list(db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(ids))))
