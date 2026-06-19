from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
from datetime import datetime, date
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI(title="KingStar - Motor de Entregas SimpliRoute Firebase")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Inicializa o FirebaseAdmin (Certifique-se de ter o arquivo JSON da credencial do Firebase)
# No Render, você pode carregar isso via variável de ambiente. Para rodar local:
if not firebase_admin._apps:
    # Substitua "textkey.json" pelo nome do arquivo gerado pelo GCP/Firebase
    cred = credentials.Certificate("textkey.json") 
    firebase_admin.initialize_app(cred)

db = firestore.client()

def normalizar_payload(payload: dict) -> dict:
    campos_padrao = {
        "id": None, "title": "Sem título", "address": "Endereço não informado", 
        "route": "Rota não identificada", "status": "pending", "on_its_way": None, 
        "checkout_time": None, "checkout_observation": None, "checkout_comment": "", 
        "order": None, "_recebido_em": datetime.now().isoformat(),
    }
    return {**campos_padrao, **payload}

def derivar_status_visual(payload: dict) -> dict:
    status_raw = str(payload.get("status", "")).strip().lower()
    obs_raw = str(payload.get("checkout_observation", "") or "").strip().lower()
    on_its_way = payload.get("on_its_way")
    notificado = bool(on_its_way and str(on_its_way).strip() not in ("", "none", "null"))

    if status_raw in {"successful", "atendida", "success", "concluida"} or obs_raw in {"successful", "atendida", "success", "concluida"}:
        status_visual = "✅ Sucesso"
    elif status_raw in {"failed", "no_atendida", "not_delivered", "failure", "recusada", "devolvida"} or obs_raw in {"failed", "no_atendida", "not_delivered", "failure", "recusada", "devolvida"}:
        status_visual = "❌ Falhou"
    elif status_raw in ("in_transit", "in_progress", "iniciada"):
        status_visual = "🚚 Em rota"
    elif notificado:
        status_visual = "📱 Notificado"
    else:
        status_visual = "⏳ Pendente"

    payload["_notificado"] = notificado
    payload["_status_visual"] = status_visual
    return payload

def salvar_no_firebase(chave: str, payload: dict):
    data_entrega = payload.get("planned_date")
    if data_entrega: data_entrega = str(data_entrega)[:10]
    else: data_entrega = date.today().isoformat()
    
    # Grava na coleção 'entregas', usando como ID a combinação de Data + Chave para evitar duplicidade
    doc_id = f"{data_entrega}_{chave}"
    
    documento = {
        "id_chave": chave,
        "data_entrega": data_entrega,
        "payload": payload, # O Firestore guarda o JSON estruturado nativamente!
        "rota": payload.get("route", "Rota não identificada"),
        "recebido_em": payload.get("_recebido_em")
    }
    
    db.collection("entregas").document(doc_id).set(documento)

@app.post("/webhook")
async def receber_webhook(request: Request):
    try:
        try: payload = await request.json()
        except:
            form_data = await request.form()
            payload = json.loads(form_data.get("payload", form_data.get("data", "{}")))

        payload = normalizar_payload(payload)
        payload = derivar_status_visual(payload)
        chave = str(payload.get("id") or payload.get("tracking_id") or datetime.now().timestamp())
        
        salvar_no_firebase(chave, payload)
        return {"status": "sucesso", "id": chave}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

if __name__ == "__main__":
    uvicorn.run("motor_api:app", host="0.0.0.0", port=8000)
