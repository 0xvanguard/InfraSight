# pyrefly: ignore [missing-import]
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from datetime import datetime
from app.database import Base

class EndpointMetric(Base):
    __tablename__ = "endpoint_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String, index=True)
    cpu_usage = Column(Float)
    ram_usage = Column(Float)
    disk_usage = Column(Float)
    health_score = Column(Integer)
    status = Column(String)
    services = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
