"""
KingStar — Motor de Entregas SimpliRoute
Deploy: Render.com

Credenciais Firebase via variável de ambiente TEXTKEY.
No Render: Dashboard → seu serviço → Environment → Add Environment Variable
  Key:   TEXTKEY
  Value: cole o conteúdo inteiro do textkey.json (o mesmo JSON do Streamlit Secrets)
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
import os
from datetime import datetime, date, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI(title="KingStar - Motor de Entregas SimpliRoute")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# FIREBASE — lê credenciais da env var TEXTKEY
# Mesmo JSON que está no Streamlit Secrets
# ─────────────────────────────────────────────
if not firebase_admin._apps:
    raw = os.environ.get("TEXTKEY", "")
    if not raw:
        raise RuntimeError(
            "Variável de ambiente TEXTKEY não encontrada. "
            "Configure em Render → Environment → TEXTKEY = {conteúdo do textkey.json}"
        )
    cred_dict = json.loads(raw)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client(database="portal")

# ─────────────────────────────────────────────
# FUSO HORÁRIO — Brasil (UTC-3)
# ─────────────────────────────────────────────
BRT = timezone(timedelta(hours=-3))

def agora_brt() -> str:
    return datetime.now(BRT).strftime("%Y-%m-%d %H:%M:%S")

def utc_para_brt(valor) -> str:
    if not valor or str(valor).strip().lower() in ("", "none", "null"):
        return valor
    try:
        s = str(valor).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if "+" in s[10:] or s.count("-") > 2:
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return dt.astimezone(BRT).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return valor

def converter_timestamps(payload: dict) -> dict:
    for campo in ["on_its_way", "checkout_time", "checkin_time",
                  "status_changed", "created", "modified"]:
        if payload.get(campo):
            payload[campo] = utc_para_brt(payload[campo])
    return payload

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def normalizar_payload(payload: dict) -> dict:
    defaults = {
        "id": None, "title": "Sem título", "address": "Endereço não informado",
        "route": "Rota não identificada", "status": "pending", "on_its_way": None,
        "checkout_time": None, "checkout_observation": None, "checkout_comment": "",
        "checkin_time": None, "contact_name": "", "contact_phone": "",
        "contact_email": "", "tracking_id": "", "notes": "", "planned_date": None,
        "estimated_time_arrival": None, "order": None,
        "_recebido_em": agora_brt(),
    }
    return {**defaults, **payload}

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

# ─────────────────────────────────────────────
# WEBHOOK — recebe todos os eventos da SimpliRoute
# ─────────────────────────────────────────────
@app.post("/webhook")
async def receber_webhook(request: Request):
    try:
        try:
            raw = await request.json()
        except Exception:
            form = await request.form()
            raw  = json.loads(form.get("payload", form.get("data", "{}")))

        # Suporta envelope {"event": "...", "data": {...}}
        if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], dict):
            payload = raw["data"]
            payload["_evento_simpli"] = raw.get("event", "")
        else:
            payload = raw

        payload = normalizar_payload(payload)
        payload = converter_timestamps(payload)
        payload = derivar_status_visual(payload)

        id_chave = str(
            payload.get("id") or
            payload.get("tracking_id") or
            datetime.now(BRT).timestamp()
        )
        data_entrega = (
            str(payload.get("planned_date", ""))[:10] or
            datetime.now(BRT).date().isoformat()
        )

        doc_id    = f"{data_entrega}_{id_chave}"
        documento = {
            "id_chave":     id_chave,
            "data_entrega": data_entrega,
            "route":        payload.get("route", "Rota não identificada"),
            "rota":         payload.get("route", "Rota não identificada"),
            "recebido_em":  payload.get("_recebido_em"),
            "payload":      payload,
            **payload,
        }

        db.collection("entregas").document(doc_id).set(documento)

        print(f"[{agora_brt()}] id={id_chave} | "
              f"rota={payload.get('route')} | "
              f"status={payload.get('_status_visual')} | "
              f"notificado={payload.get('_notificado')}")

        return {
            "status":        "sucesso",
            "id":            id_chave,
            "status_visual": payload.get("_status_visual"),
            "notificado":    payload.get("_notificado"),
        }

    except Exception as e:
        print(f"[{agora_brt()}] ERRO: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "online", "hora_brt": agora_brt()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("motor_api:app", host="0.0.0.0", port=port)
