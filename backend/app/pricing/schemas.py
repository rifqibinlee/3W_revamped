from pydantic import BaseModel


class PriceUpsertRequest(BaseModel):
    price: float
