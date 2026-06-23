from pydantic import BaseModel


class PriceUpsertRequest(BaseModel):
    price: float
    price_min: float | None = None
    price_max: float | None = None
