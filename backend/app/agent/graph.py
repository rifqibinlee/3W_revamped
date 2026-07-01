"""The agent itself: a standard LangGraph ReAct loop (model + tools),
built fresh per request rather than as a long-lived module-level object —
`get_chat_model()` already checks settings at call time (Claude vs Ollama
fallback), so building the graph per-request keeps that check live
instead of baking in whichever provider was active at import time.
"""

from langgraph.prebuilt import create_react_agent

from app.agent.llm import get_chat_model
from app.agent.tools import ALL_TOOLS

SYSTEM_PROMPT = (
    "You are the 3W+ network operations assistant for a Malaysian telco. "
    "You have access to the live analytics warehouse (DuckDB Parquet) and "
    "an internal knowledge base of training documents. "
    "Your capabilities:\n"
    "• Congestion status and forecasts by sector (zoom_sector_id)\n"
    "• List all congested sectors, optionally filtered by region\n"
    "• Site coordinates, sector count, and congestion summary by site_id\n"
    "• Coverage hole clusters from DBSCAN anomaly detection\n"
    "• CAPEX equipment and services pricing\n"
    "• Direct SQL queries against the analytics warehouse (read-only)\n"
    "• Knowledge base search over internal PDFs and Excel reference data\n\n"
    "Always cite the data source (sector ID, site ID, region, or document "
    "name) in your answers. If a tool returns an error, say so plainly "
    "rather than guessing. Respond in the same language the user writes in."
)


def build_agent():
    return create_react_agent(get_chat_model(), ALL_TOOLS, prompt=SYSTEM_PROMPT)


def run_agent(message: str) -> str:
    agent = build_agent()
    result = agent.invoke({"messages": [{"role": "user", "content": message}]})
    return result["messages"][-1].content
