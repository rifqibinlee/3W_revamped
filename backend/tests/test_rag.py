from app.rag import service
from app.rag.models import KnowledgeChunk


def test_chunk_text_splits_long_text() -> None:
    long_text = "word " * 500
    chunks = service._splitter.split_text(long_text)
    assert len(chunks) > 1
    assert all(len(c) <= service.CHUNK_SIZE + 50 for c in chunks)


def test_chunk_text_short_text_stays_one_chunk() -> None:
    chunks = service._splitter.split_text("short text")
    assert chunks == ["short text"]


def test_ingest_pdf_stores_chunks(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        service, "extract_pages", lambda path: [(1, "This describes congestion in the network.")]
    )
    count = service.ingest_pdf(db_session, "fake.pdf", "test-doc")
    assert count == 1

    stored = db_session.query(KnowledgeChunk).all()
    assert len(stored) == 1
    assert stored[0].source == "test-doc"
    assert stored[0].page == 1


def test_ingest_pdf_with_no_extractable_text_stores_nothing(db_session, monkeypatch) -> None:
    monkeypatch.setattr(service, "extract_pages", lambda path: [])
    count = service.ingest_pdf(db_session, "blank.pdf", "blank-doc")
    assert count == 0


def test_search_with_empty_knowledge_base_returns_nothing(db_session) -> None:
    results = service.search(db_session, "anything")
    assert results == []
