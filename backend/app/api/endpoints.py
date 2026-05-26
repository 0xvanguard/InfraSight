# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.endpoint import EndpointMetric
from app.schemas.metrics import MetricCreate, MetricRead
from typing import List
# pyrefly: ignore [missing-import]
import httpx
import os

router = APIRouter()

VANGUARDOPS_URL = os.getenv("VANGUARDOPS_URL", "http://localhost:8000/api/v1/tickets/")
VANGUARDOPS_TOKEN = "super-secret-admin-token"  

def send_alert_to_vanguardops(hostname: str, score: int, cpu: float, ram: float, disk: float):
    """Dispara el webhook hacia VanguardOps para orquestar la respuesta a incidentes."""
    payload = {
        "title": f"Degradación Crítica: {hostname}",
        "description": f"Alerta Automática de InfraSight.\nScore de Salud: {score}/100\nCPU: {cpu}%\nRAM: {ram}%\nDisco: {disk}%",
        "category": "endpoint_health",
        "severity": "CRITICAL"
    }
    headers = {
        "X-Admin-Token": VANGUARDOPS_TOKEN,
        "Content-Type": "application/json"
    }
    try:
        with httpx.Client() as client:
            res = client.post(VANGUARDOPS_URL, json=payload, headers=headers, timeout=5.0)
            print(f"[Webhook] Alerta enviada a VanguardOps: HTTP {res.status_code}")
    except Exception as e:
        print(f"[Webhook] Error de conexión con VanguardOps: {e}")

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
    
    # 1. Verificar estado anterior para no saturar de webhooks (Spam Control)
    previous = db.query(EndpointMetric).filter(EndpointMetric.hostname == metric_in.hostname).order_by(EndpointMetric.timestamp.desc()).first()
    
    # 2. Guardar métrica nueva
    db_metric = EndpointMetric(**metric_in.model_dump())
    db.add(db_metric)
    db.commit()
    db.refresh(db_metric)
    
    # 3. Disparar Integración hacia VanguardOps si cruza el umbral
    if metric_in.status == "CRITICAL":
        if not previous or previous.status != "CRITICAL":
            # El endpoint acaba de colapsar, disparar webhook en segundo plano
            background_tasks = None
            background_tasks.add_task(
                send_alert_to_vanguardops, 
                metric_in.hostname, 
                metric_in.health_score, 
                metric_in.cpu_usage, 
                metric_in.ram_usage, 
                metric_in.disk_usage
            )
            
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
