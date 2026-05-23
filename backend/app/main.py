import os
from fastapi import FastAPI
from app.database import Base, engine
from app.api.endpoints import router as metrics_router
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Crear tablas locales SQLite (MVP)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="InfraSight API", 
    version="1.0.0",
    description="Remote Monitoring & Endpoint Intelligence Backend"
)

# CORS para Dashboards Desacoplados
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montar Rutas API
app.include_router(metrics_router, prefix="/api/v1")

# Montar Dashboard Estático
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", tags=["frontend"])
def read_dashboard():
    return FileResponse("app/static/index.html")
