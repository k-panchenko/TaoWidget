from datetime import datetime
from pydantic import BaseModel


class HistoricalData(BaseModel):
    block_number: int
    timestamp: datetime
    value: float 


class DailyData(BaseModel):
    date: datetime
    balance: float
    stake: float
