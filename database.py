import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import hashlib
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))

def get_db():
    if "db" not in st.session_state:
        key_dict = json.loads(st.secrets["textkey"])
        creds    = service_account.Credentials.from_service_account_info(key_dict)
        st.session_state.db = firestore.Client(
            credentials=creds,
            project=creds.project_id,
            database="portal"
        )
    return st.session_state.db

def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()

# ─────────────────────────────────────────────
# AUTENTICAÇÃO
# ─────────────────────────────────────────────
def verificar_login(usuario: str, senha: str):
    if usuario == "admin" and senha == "admin123":
        return {"nome": "Administrador Master", "usuario": "admin", "role": "adm"}
    db  = get_db()
    doc = db.collection("usuarios").document(usuario).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("senha_hash") == hash_senha(senha):
            return data
    return None

def criar_usuario(nome, usuario, senha, role):
    get_db().collection("usuarios").document(usuario).set({
        "nome": nome, "usuario": usuario,
        "senha_hash": hash_senha(senha), "role": role
    })

def listar_usuarios():
    return [d.to_dict() for d in get_db().collection("usuarios").stream()]

def deletar_usuario(usuario):
    get_db().collection("usuarios").document(usuario).delete()

# ─────────────────────────────────────────────
# ENTREGAS
# ─────────────────────────────────────────────
def obter_tickets_db(data_alvo: str) -> list:
    """
    Busca entregas do Firestore para a data informada.
    Retorna a lista de payloads prontos para virar DataFrame.
    SEMPRE busca direto no Firestore — sem cache — para garantir
    que o painel reflita o estado atual em tempo real.
    """
    db   = get_db()
    docs = db.collection("entregas") \
             .where("data_entrega", "==", data_alvo) \
             .stream()

    resultado = []
    for doc in docs:
        d = doc.to_dict()
        # Prefere o sub-objeto "payload" (gravado pelo motor_api)
        # pois contém _notificado e _status_visual já calculados
        payload = d.get("payload", d)
        resultado.append(payload)

    return resultado

def obter_datas_disponiveis_db() -> list:
    """Retorna lista de datas com registros: [{"data": "2025-06-26", "total": 5}]"""
    db   = get_db()
    docs = db.collection("entregas").select(["data_entrega"]).stream()
    datas: dict = {}
    for doc in docs:
        d = doc.to_dict().get("data_entrega")
        if d:
            datas[d] = datas.get(d, 0) + 1
    return [{"data": k, "total": v} for k, v in sorted(datas.items(), reverse=True)]

# ─────────────────────────────────────────────
# DE-PARA MOTORISTAS
# ─────────────────────────────────────────────
def obter_vinculo_db(chave: str) -> str:
    doc = get_db().collection("de_para_motoristas").document(chave).get()
    return doc.to_dict().get("nome_motorista", chave) if doc.exists else chave

def salvar_vinculo_db(chave: str, nome: str):
    get_db().collection("de_para_motoristas").document(chave).set(
        {"nome_motorista": nome}
    )

def deletar_rota_db(rota_original: str, data_alvo: str):
    db    = get_db()
    docs  = db.collection("entregas") \
              .where("rota", "==", rota_original) \
              .where("data_entrega", "==", data_alvo) \
              .stream()
    batch = db.batch()
    for doc in docs:
        batch.delete(doc.reference)
    batch.commit()
