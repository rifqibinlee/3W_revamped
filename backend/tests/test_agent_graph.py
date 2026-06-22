from app.agent.graph import build_agent


def test_agent_graph_builds_without_network_call(monkeypatch) -> None:
    """Building the graph just wires the model+tools together — no LLM
    call happens until .invoke(), so this needs no API key/network and
    should work with either provider."""
    from app.agent import llm

    monkeypatch.setattr(llm.settings, "anthropic_api_key", None)
    agent = build_agent()
    assert agent is not None
