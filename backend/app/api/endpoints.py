from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.endpoint import EndpointMetric
from app.schemas.metrics import MetricCreate, MetricRead
from typing import List

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_agent_token(x_agent_token: str = Header(None)):
    if x_agent_token != "infrasight-agent-secret":
        raise HTTPException(status_code=403, detail="Invalid agent token")

@router.post("/metrics", response_model=MetricRead, dependencies=[Depends(verify_agent_token)])
def ingest_metrics(metric_in: MetricCreate, db: Session = Depends(get_db)):
    """Recibe métricas crudas desde el Agente Ligero de Linux y las indexa."""
    db_metric = EndpointMetric(**metric_in.model_dump())
    db.add(db_metric)
    db.commit()
    db.refresh(db_metric)
    return db_metric

@router.get("/endpoints", response_model=List[dict])
def get_latest_endpoints(db: Session = Depends(get_db)):
    """Retorna la fotografía más reciente de salud para cada endpoint reportando."""
    # Obtener hostnames únicos
    hostnames = db.query(EndpointMetric.hostname).distinct().all()
    results = []
    
    for (h,) in hostnames:
        # Extraer el registro más fresco por host
        latest = db.query(EndpointMetric).filter(EndpointMetric.hostname == h).order_by(EndpointMetric.timestamp.desc()).first()
        if latest:
            results.append({
                "hostname": latest.hostname,
                "health_score": latest.health_score,
                "status": latest.status,
                "cpu_usage": latest.cpu_usage,
                "ram_usage": latest.ram_usage,
                "disk_usage": latest.disk_usage,
                "last_seen": latest.timestamp
            })
    return results

@router.get("/metrics/{hostname}", response_model=List[MetricRead])
def get_host_metrics(hostname: str, limit: int = 20, db: Session = Depends(get_db)):
    """Extrae la historia temporal (Time-Series emulado) de un host."""
    return db.query(EndpointMetric).filter(EndpointMetric.hostname == hostname).order_by(EndpointMetric.timestamp.desc()).limit(limit).all()
