from fastapi import APIRouter, Depends

from app.agent.graph import run_agent
from app.agent.schemas import AgentChatRequest, AgentChatResponse
from app.auth.dependencies import get_current_user
from app.auth.models import User

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
def chat(payload: AgentChatRequest, user: User = Depends(get_current_user)) -> AgentChatResponse:
    return AgentChatResponse(reply=run_agent(payload.message))
