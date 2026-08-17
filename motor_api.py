"""
KingStar — Motor de Entregas SimpliRoute
Deploy: Render.com

Credenciais Firebase via variável de ambiente TEXTKEY.
No Render: Dashboard → seu serviço → Environment → Add Environment Variable
  Key:   TEXTKEY
  Value: cole o conteúdo inteiro do textkey.json (o mesmo JSON do Streamlit Secrets)

NOVO — Rastreio ao vivo (GPS do motorista + alerta de proximidade):
Variáveis de ambiente OPCIONAIS (se não configuradas, o envio de WhatsApp
é simplesmente pulado — o resto do rastreio continua funcionando normal):
  TWILIO_ACCOUNT_SID   = seu Account SID do Twilio
  TWILIO_AUTH_TOKEN    = seu Auth Token do Twilio
  TWILIO_WHATSAPP_FROM = número WhatsApp do Twilio, formato: whatsapp:+14155238886
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
import os
import math
import requests
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


# ═══════════════════════════════════════════════════════════════════
# RASTREIO AO VIVO — recebe o ping de GPS do celular do motorista
# (enviado pela página motorista_gps_tracker.html) e alimenta as
# coleções que o Streamlit (mod_rastreio.py / mod_rastreio_live.py) lê.
# ═══════════════════════════════════════════════════════════════════

LIMITE_ALERTA_KM   = 5.0
FATOR_ROTA         = 1.35   # aproxima distância real de estrada a partir da linha reta
VELOCIDADE_PADRAO  = 30.0   # km/h, usado no ETA quando o GPS não informa velocidade

TWILIO_ACCOUNT_SID   = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "")  # ex: "whatsapp:+14155238886"


def distancia_haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distância em linha reta entre dois pontos GPS, em km."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimar_distancia_rota_km(lat1, lon1, lat2, lon2) -> float:
    """Aproximação de distância de estrada (linha reta × fator de sinuosidade),
    sem depender de uma API paga de roteamento (Google Directions/OSRM)."""
    return distancia_haversine_km(lat1, lon1, lat2, lon2) * FATOR_ROTA


def calcular_eta_minutos(distancia_km: float, velocidade_kmh) -> int:
    v = velocidade_kmh if (velocidade_kmh and velocidade_kmh > 3) else VELOCIDADE_PADRAO
    return max(1, round((distancia_km / v) * 60))


def enviar_whatsapp_twilio(telefone: str, mensagem: str) -> bool:
    """
    Envia uma mensagem de WhatsApp via API REST do Twilio.

    Se as variáveis de ambiente do Twilio não estiverem configuradas, ou
    se o envio falhar por qualquer motivo, retorna False e apenas loga no
    console — nunca derruba o endpoint de GPS por causa disso (o rastreio
    e o cálculo de distância/ETA continuam funcionando mesmo sem WhatsApp).

    Se o seu projeto já tem uma função própria de envio (usada pelo
    mod_chat.py), o ideal é substituir o corpo desta função por uma
    chamada HTTP a ela, ou por um import direto, para não manter duas
    integrações de WhatsApp separadas.
    """
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
        print(f"[{agora_brt()}] Twilio não configurado — pulando envio de WhatsApp "
              f"(defina TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM no Render).")
        return False

    telefone = (telefone or "").strip()
    if not telefone:
        print(f"[{agora_brt()}] Sem telefone do cliente cadastrado — não é possível avisar.")
        return False

    destino = telefone if telefone.startswith("whatsapp:") else f"whatsapp:{telefone}"

    try:
        resp = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={"From": TWILIO_WHATSAPP_FROM, "To": destino, "Body": mensagem},
            timeout=8,
        )
        if resp.status_code >= 300:
            print(f"[{agora_brt()}] Twilio retornou erro {resp.status_code}: {resp.text[:300]}")
            return False
        return True
    except Exception as e:
        print(f"[{agora_brt()}] Falha ao chamar a API do Twilio: {e}")
        return False


@app.post("/gps/{ticket_id}")
async def receber_gps(ticket_id: str, request: Request):
    """
    Recebe um ping de GPS do celular do motorista (motorista_gps_tracker.html)
    para uma entrega específica (ticket_id = _doc_id da entrega no Firestore).

    Body esperado (JSON):
      { "lat": -23.55, "lng": -46.63, "velocidade_kmh": 32, "precisao_m": 12,
        "atualizado_em": "2026-08-17T15:30:00.000Z" }

    Passos:
      1. Grava a posição em /posicoes_motoristas/{ticket_id}
      2. Lê a config de rastreio ao vivo da entrega em /entregas_rastreio_live/{ticket_id}
      3. Se a config existir e o alerta ainda não tiver sido enviado,
         calcula a distância até o destino e, se estiver dentro do limite,
         dispara o WhatsApp e marca o alerta como enviado (não repete).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corpo da requisição precisa ser JSON.")

    lat = body.get("lat")
    lng = body.get("lng")
    if lat is None or lng is None:
        raise HTTPException(status_code=400, detail="Campos 'lat' e 'lng' são obrigatórios.")

    velocidade_kmh = body.get("velocidade_kmh")
    precisao_m     = body.get("precisao_m")
    atualizado_em  = body.get("atualizado_em") or agora_brt()

    # 1) Grava a posição — é isso que o Streamlit lê para desenhar o mapa.
    db.collection("posicoes_motoristas").document(ticket_id).set({
        "lat": lat,
        "lng": lng,
        "velocidade_kmh": velocidade_kmh,
        "precisao_m": precisao_m,
        "atualizado_em": atualizado_em,
    })

    resultado = {
        "status": "posicao_registrada",
        "ticket_id": ticket_id,
        "distancia_km": None,
        "eta_min": None,
        "alerta_disparado": False,
    }

    # 2) Lê a config da entrega (destino + telefone do cliente + flag de alerta)
    config_ref = db.collection("entregas_rastreio_live").document(ticket_id)
    config_doc = config_ref.get()

    if not config_doc.exists:
        # Posição gravada normalmente, mas essa entrega ainda não teve o
        # rastreio ao vivo "ativado" no Streamlit (sem destino cadastrado,
        # não dá pra calcular distância nem disparar alerta).
        print(f"[{agora_brt()}] Ping recebido para {ticket_id}, mas sem config de rastreio ao vivo ainda.")
        return resultado

    config = config_doc.to_dict()
    dist_km = estimar_distancia_rota_km(lat, lng, config["destino_lat"], config["destino_lng"])
    eta_min = calcular_eta_minutos(dist_km, velocidade_kmh)

    resultado["distancia_km"] = round(dist_km, 2)
    resultado["eta_min"] = eta_min

    # 3) Gatilho do alerta — dispara UMA ÚNICA VEZ por entrega.
    if not config.get("alerta_5km_enviado") and dist_km <= LIMITE_ALERTA_KM:
        mensagem = (
            f"🚚 Seu pedido está chegando! Faltam aproximadamente "
            f"{dist_km:.1f} km — previsão de chegada em {eta_min} min."
        )
        enviado = enviar_whatsapp_twilio(config.get("cliente_telefone", ""), mensagem)

        # Marca como enviado MESMO se o Twilio falhar (ex: número inválido),
        # para não ficar tentando reenviar a cada ping novo (a cada poucos
        # segundos) caso o problema seja persistente. Se quiser tentar de
        # novo manualmente, dá pra resetar o campo direto no Firestore.
        config_ref.update({"alerta_5km_enviado": True})
        resultado["alerta_disparado"] = enviado

        print(f"[{agora_brt()}] Alerta de proximidade para {ticket_id}: "
              f"{dist_km:.1f}km, WhatsApp {'enviado' if enviado else 'NÃO enviado (ver log acima)'}.")

    return resultado


@app.get("/gps/{ticket_id}")
def consultar_gps(ticket_id: str):
    """Endpoint auxiliar de leitura — útil para testar rapidamente pelo
    navegador/Postman se um ticket_id já tem posição e config gravadas,
    sem precisar abrir o Streamlit."""
    pos_doc = db.collection("posicoes_motoristas").document(ticket_id).get()
    cfg_doc = db.collection("entregas_rastreio_live").document(ticket_id).get()
    return {
        "posicao": pos_doc.to_dict() if pos_doc.exists else None,
        "config": cfg_doc.to_dict() if cfg_doc.exists else None,
    }


@app.get("/health")
def health():
    return {"status": "online", "hora_brt": agora_brt()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("motor_api:app", host="0.0.0.0", port=port)
