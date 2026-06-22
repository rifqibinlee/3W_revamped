from app.rag import service
from app.rag.models import EMBEDDING_DIM, KnowledgeChunk


def _vec(*active_dims: int) -> list[float]:
    """A 768-dim vector (matching the real schema) that's 1.0 in the
    given dimensions and 0.0 elsewhere — keeps fake vectors trivially
    distinguishable for similarity ranking without a real embedding model."""
    v = [0.0] * EMBEDDING_DIM
    for d in active_dims:
        v[d] = 1.0
    return v


def _fake_embed_documents(texts: list[str]) -> list[list[float]]:
    return [_fake_vector(t) for t in texts]


def _fake_vector(text: str) -> list[float]:
    if "congestion" in text.lower():
        return _vec(0)
    if "antenna" in text.lower():
        return _vec(1)
    return _vec(2)


def test_chunk_text_splits_long_text() -> None:
    long_text = "word " * 500
    chunks = service.chunk_text(long_text)
    assert len(chunks) > 1
    assert all(len(c) <= service.CHUNK_SIZE + 50 for c in chunks)  # small tolerance for split boundaries


def test_chunk_text_short_text_stays_one_chunk() -> None:
    chunks = service.chunk_text("short text")
    assert chunks == ["short text"]


def test_ingest_pdf_stores_chunks_with_embeddings(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        service, "extract_pages", lambda path: [(1, "This describes congestion in the network.")]
    )
    count = service.ingest_pdf(db_session, "fake.pdf", "test-doc", embed_documents=_fake_embed_documents)
    assert count == 1

    stored = db_session.query(KnowledgeChunk).all()
    assert len(stored) == 1
    assert stored[0].source == "test-doc"
    assert stored[0].page == 1
    assert list(stored[0].embedding) == _vec(0)


def test_ingest_pdf_with_no_extractable_text_stores_nothing(db_session, monkeypatch) -> None:
    monkeypatch.setattr(service, "extract_pages", lambda path: [])
    count = service.ingest_pdf(db_session, "blank.pdf", "blank-doc", embed_documents=_fake_embed_documents)
    assert count == 0


def test_search_ranks_by_similarity(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "extract_pages",
        lambda path: [(1, "Congestion analysis report."), (2, "Antenna tilt configuration guide.")],
    )
    service.ingest_pdf(db_session, "doc.pdf", "doc", embed_documents=_fake_embed_documents)

    results = service.search(
        db_session, "tell me about congestion", top_k=1,
        embed_query=lambda q: _vec(0),
    )
    assert len(results) == 1
    assert "Congestion" in results[0].content


def test_search_with_empty_knowledge_base_returns_nothing(db_session) -> None:
    results = service.search(db_session, "anything", embed_query=lambda q: _vec(0))
    assert results == []
