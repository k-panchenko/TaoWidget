from datetime import datetime
from pydantic import BaseModel


class HistoricalData(BaseModel):
    block_number: int
    timestamp: datetime
    value: float 