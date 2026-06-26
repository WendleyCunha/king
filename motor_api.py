from fastapi import FastAPI, Request, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
import os
from datetime import datetime, date, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI(title="KingStar - Motor de Entregas SimpliRoute Firebase")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if not firebase_admin._apps:
    cred = credentials.Certificate("textkey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client(database="portal")

# ─────────────────────────────────────────────
# FUSO HORÁRIO — Brasil (UTC-3)
# ─────────────────────────────────────────────
BRT = timezone(timedelta(hours=-3))

def agora_brt() -> str:
    return datetime.now(BRT).strftime("%Y-%m-%d %H:%M:%S")

def utc_para_brt(valor_str) -> str:
    """Converte string ISO UTC para horário de Brasília (UTC-3)."""
    if not valor_str or str(valor_str).strip().lower() in ("", "none", "null"):
        return valor_str
    try:
        s = str(valor_str).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if "+" in s[10:] or (s.count("-") > 2):
            dt_utc = datetime.fromisoformat(s)
        else:
            dt_utc = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return dt_utc.astimezone(BRT).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return valor_str

def converter_timestamps_para_brt(payload: dict) -> dict:
    """Converte todos os campos de timestamp UTC → BRT antes de salvar."""
    for campo in ["on_its_way", "checkout_time", "checkin_time",
                  "status_changed", "created", "modified"]:
        if payload.get(campo):
            payload[campo] = utc_para_brt(payload[campo])
    return payload

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def normalizar_payload(payload: dict) -> dict:
    campos_padrao = {
        "id": None, "title": "Sem título", "address": "Endereço não informado",
        "route": "Rota não identificada", "status": "pending", "on_its_way": None,
        "checkout_time": None, "checkout_observation": None, "checkout_comment": "",
        "checkin_time": None, "contact_name": "", "contact_phone": "",
        "contact_email": "", "tracking_id": "", "notes": "", "planned_date": None,
        "estimated_time_arrival": None, "order": None,
        "_recebido_em": agora_brt(),
    }
    return {**campos_padrao, **payload}

def derivar_status_visual(payload: dict) -> dict:
    status_raw = str(payload.get("status", "")).strip().lower()
    obs_raw    = str(payload.get("checkout_observation", "") or "").strip().lower()
    on_its_way = payload.get("on_its_way")

    notificado = bool(
        on_its_way and
        str(on_its_way).strip().lower() not in ("", "none", "null", "false")
    )

    sucesso_keys = {"successful", "atendida", "success", "concluida",
                    "done", "entregue", "completed", "partial"}
    falha_keys   = {"failed", "no_atendida", "not_delivered", "failure",
                    "recusada", "devolvida", "devolucao", "devolução",
                    "falhou", "canceled"}

    if status_raw in sucesso_keys or obs_raw in sucesso_keys:
        sv = "✅ Sucesso"
    elif status_raw in falha_keys or obs_raw in falha_keys:
        sv = "❌ Falhou"
    elif status_raw in ("in_transit", "in_progress", "in_route", "iniciada"):
        sv = "🚚 Em rota"
    elif notificado:
        sv = "📱 Notificado"
    else:
        sv = "⏳ Pendente"

    payload["_notificado"]    = notificado
    payload["_status_visual"] = sv
    return payload

def extrair_chave_permanente(nome_rota: str) -> str:
    if not nome_rota:
        return "SEM_ROTA"
    partes = nome_rota.split(" - ")
    return partes[1].strip() if len(partes) > 1 else nome_rota.strip()

# ─────────────────────────────────────────────
# WEBHOOK — recebe todos os eventos da SimpliRoute
# ─────────────────────────────────────────────
@app.post("/webhook")
async def receber_webhook(request: Request):
    try:
        try:
            raw = await request.json()
        except:
            form_data = await request.form()
            raw = json.loads(form_data.get("payload", form_data.get("data", "{}")))

        # Suporta envelope {"event": "...", "data": {...}} da SimpliRoute
        if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], dict):
            evento  = raw.get("event", "")
            payload = raw["data"]
            payload["_evento_simpli"] = evento
        else:
            payload = raw
            evento  = payload.get("_evento_simpli", "direto")

        payload = normalizar_payload(payload)
        payload = converter_timestamps_para_brt(payload)   # ← CORRIGE FUSO
        payload = derivar_status_visual(payload)

        id_chave = str(
            payload.get("id") or
            payload.get("tracking_id") or
            datetime.now(BRT).timestamp()
        )

        data_entrega = str(payload.get("planned_date", ""))[:10] or \
                       datetime.now(BRT).date().isoformat()

        doc_id = f"{data_entrega}_{id_chave}"

        documento = {
            "id_chave":    id_chave,
            "data_entrega": data_entrega,
            "route":       payload.get("route", "Rota não identificada"),
            "rota":        payload.get("route", "Rota não identificada"),
            "recebido_em": payload.get("_recebido_em"),
            "payload":     payload,   # ← usado por obter_tickets_db()
            **payload                 # ← campos planos para consultas Firestore
        }

        db.collection("entregas").document(doc_id).set(documento)

        print(
            f"[{agora_brt()}] evento={evento} | id={id_chave} | "
            f"rota={payload.get('route')} | "
            f"status={payload.get('_status_visual')} | "
            f"notificado={payload.get('_notificado')}"
        )

        return {
            "status":        "sucesso",
            "id":            id_chave,
            "evento":        evento,
            "status_visual": payload.get("_status_visual"),
            "notificado":    payload.get("_notificado"),
        }

    except Exception as e:
        print(f"[{agora_brt()}] ERRO webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "online", "hora_brt": agora_brt()}

if __name__ == "__main__":
    uvicorn.run("motor_api:app", host="0.0.0.0", port=8000, reload=True)
