from fastapi import FastAPI, Request, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
import os
from datetime import datetime, date
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI(title="KingStar - Motor de Entregas SimpliRoute Firebase")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializa o FirebaseAdmin utilizando o arquivo de credenciais
if not firebase_admin._apps:
    cred = credentials.Certificate("textkey.json") 
    firebase_admin.initialize_app(cred)

db = firestore.client(database="portal")

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

def extrair_chave_permanente(nome_rota: str) -> str:
    if not nome_rota:
        return "SEM_ROTA"  # Ajustado para bater com o padrão do Streamlit
    partes = nome_rota.split(" - ")
    return partes[1].strip() if len(partes) > 1 else nome_rota.strip()

# --- ENDPOINT 1: RECEBER WEBHOOK DO SIMPLIROUTE ---
@app.post("/webhook")
async def receber_webhook(request: Request):
    try:
        try: 
            payload = await request.json()
        except:
            form_data = await request.form()
            payload = json.loads(form_data.get("payload", form_data.get("data", "{}")))

        payload = normalizar_payload(payload)
        payload = derivar_status_visual(payload)
        
        id_chave = str(payload.get("id") or payload.get("tracking_id") or datetime.now().timestamp())
        data_entrega = payload.get("planned_date")
        if data_entrega: 
            data_entrega = str(data_entrega)[:10]
        else: 
            data_entrega = date.today().isoformat()
            
        doc_id = f"{data_entrega}_{id_chave}"
        
        # CORREÇÃO CRUCIAL: Monta o documento com mapeamentos para a API E para o Streamlit
        documento = {
            "id_chave": id_chave,
            "data_entrega": data_entrega,
            "route": payload.get("route", "Rota não identificada"), # Usado pela API
            "rota": payload.get("route", "Rota não identificada"),  # Usado pelo deletar_rota_db do Streamlit
            "recebido_em": payload.get("_recebido_em"),
            "payload": payload,                                     # Usado pelo obter_tickets_db do Streamlit
            **payload                                               # Mantém campos planos para os endpoints da API
        }
        
        db.collection("entregas").document(doc_id).set(documento)
        return {"status": "sucesso", "id": id_chave}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

# --- ENDPOINT 2: DATAS DISPONÍVEIS ---
@app.get("/datas_disponiveis")
def datas_disponiveis():
    try:
        docs = db.collection("entregas").select(["data_entrega"]).stream()
        datas = {}
        for doc in docs:
            d_val = doc.to_dict().get("data_entrega")
            if d_val:
                datas[d_val] = datas.get(d_val, 0) + 1
        
        resultado = [{"data_entrega": k, "total": v} for k, v in sorted(datas.items(), reverse=True)]
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 3: BUSCAR ENTREGAS DA DATA ---
@app.get("/entregas")
def listar_entregas(data_selecionada: str = Query(...)):
    try:
        docs = db.collection("entregas").where("data_entrega", "==", data_selecionada).stream()
        entregas = [doc.to_dict() for doc in docs]
        return {"entregas": entregas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 4: CONSOLIDADO DE MOTORISTAS/ROTAS ---
@app.get("/motoristas")
def resumo_motoristas(data_selecionada: str = Query(...)):
    try:
        docs = db.collection("entregas").where("data_entrega", "==", data_selecionada).stream()
        
        rotas = {}
        for doc in docs:
            t = doc.to_dict()
            r = t.get("route", "Rota não identificada")
            if r not in rotas:
                rotas[r] = {"total": 0, "notificados": 0, "sucesso": 0, "falha": 0, "pendente": 0}
            
            rotas[r]["total"] += 1
            if t.get("_notificado"): 
                rotas[r]["notificados"] += 1
                
            status_vis = t.get("_status_visual")
            if status_vis == "✅ Sucesso": 
                rotas[r]["sucesso"] += 1
            elif status_vis == "❌ Falhou": 
                rotas[r]["falha"] += 1
            else: 
                rotas[r]["pendente"] += 1

        dp_docs = db.collection("de_para_motoristas").stream()
        de_para = {doc.id: doc.to_dict().get("nome_motorista") for doc in dp_docs}

        resultado = []
        for rota, stats in rotas.items():
            chave_permanente = extrair_chave_permanente(rota)
            nome_final = de_para.get(chave_permanente, chave_permanente)
            
            resultado.append({
                "motorista_id_original": rota,
                "motorista": nome_final,
                "total_entregas": stats["total"],
                "notificados": stats["notificados"],
                "pct_notificacao": round(stats["notificados"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0,
                "sucesso": stats["sucesso"],
                "falhou": stats["falha"],
                "pendentes": stats["pendente"],
            })
        return {"motoristas": sorted(resultado, key=lambda x: x["motorista"])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 5: SALVAR DE-PARA DE MOTORISTA ---
@app.post("/salvar_motorista")
async def salvar_motorista(request: Request):
    try:
        dados = await request.json()
        chave_rota = dados.get("chave_rota")
        nome_motorista = dados.get("nome_motorista")
        if not chave_rota or not nome_motorista:
            raise HTTPException(status_code=400, detail="Campos ausentes.")
            
        db.collection("de_para_motoristas").document(chave_rota).set({"nome_motorista": nome_motorista})
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("motor_api:app", host="0.0.0.0", port=8000)
