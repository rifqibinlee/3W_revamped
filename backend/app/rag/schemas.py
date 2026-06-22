from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SearchResult(BaseModel):
    source: str
    page: int | None
    content: str

    model_config = {"from_attributes": True}
