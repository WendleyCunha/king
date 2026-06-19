import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import hashlib

def get_db():
    if "db" not in st.session_state:
        key_dict = json.loads(st.secrets["textkey"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        st.session_state.db = firestore.Client(credentials=creds, project="wendleydesenvolvimento")
    return st.session_state.db

def hash_senha(senha):
    """Gera um hash nativo usando SHA-256 (não requer pip install bcrypt)"""
    return hashlib.sha256(senha.encode()).hexdigest()

def verificar_login(usuario, senha):
    # Regra master inicial solicitada (bypass seguro temporário)
    if usuario == "admin" and senha == "admin123":
        return {"nome": "Administrador Master", "usuario": "admin", "role": "adm"}
    
    db = get_db()
    doc = db.collection("usuarios").document(usuario).get()
    if doc.exists:
        user_data = doc.to_dict()
        if user_data.get("senha_hash") == hash_senha(senha):
            return user_data
    return None

def criar_usuario(nome, usuario, senha, role):
    db = get_db()
    db.collection("usuarios").document(usuario).set({
        "nome": nome,
        "usuario": usuario,
        "senha_hash": hash_senha(senha),
        "role": role
    })

def listar_usuarios():
    db = get_db()
    return [doc.to_dict() for doc in db.collection("usuarios").stream()]

def deletar_usuario(usuario):
    get_db().collection("usuarios").document(usuario).delete()

def obter_tickets_db(data_alvo):
    docs = get_db().collection("entregas").where("data_entrega", "==", data_alvo).stream()
    return [doc.to_dict().get("payload", {}) for doc in docs]

def obter_datas_disponiveis_db():
    docs = get_db().collection("entregas").select(["data_entrega"]).stream()
    datas = {}
    for doc in docs:
        d = doc.to_dict().get("data_entrega")
        if d: datas[d] = datas.get(d, 0) + 1
    return [{"data": k, "total": v} for k, v in sorted(datas.items(), reverse=True)]

def obter_vinculo_db(chave):
    doc = get_db().collection("de_para_motoristas").document(chave).get()
    return doc.to_dict().get("nome_motorista", chave) if doc.exists else chave

def salvar_vinculo_db(chave, nome):
    get_db().collection("de_para_motoristas").document(chave).set({"nome_motorista": nome})

def deletar_rota_db(rota_original, data_alvo):
    db = get_db()
    docs = db.collection("entregas").where("rota", "==", rota_original).where("data_entrega", "==", data_alvo).stream()
    batch = db.batch()
    for doc in docs: batch.delete(doc.reference)
    batch.commit()
