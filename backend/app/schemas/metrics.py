# pyrefly: ignore [missing-import]
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime

class MetricCreate(BaseModel):
    hostname: str
    cpu_usage: float
    ram_usage: float
    disk_usage: float
    health_score: int
    status: str
    services: Dict[str, str]

class MetricRead(MetricCreate):
    id: int
    timestamp: datetime
    
    class Config:
        from_attributes = True
