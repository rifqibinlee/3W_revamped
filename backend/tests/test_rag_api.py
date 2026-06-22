def test_search_endpoint_with_empty_knowledge_base(client, monkeypatch) -> None:
    monkeypatch.setattr("app.rag.router.service.search", lambda db, query, top_k: [])
    resp = client.post("/rag/search", json={"query": "anything"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_ingest_endpoint_requires_auth(client) -> None:
    resp = client.post("/rag/ingest", files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert resp.status_code == 401
