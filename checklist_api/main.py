from fastapi import FastAPI

from modules import api_router

app = FastAPI(
    title="King Star — Motor de Checklists",
    version="0.1.0",
    description="API do sistema próprio de gestão de checklists (Fase 2 — MVP, módulo: auth + estrutura organizacional)",
)

app.include_router(api_router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
