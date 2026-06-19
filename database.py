import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd
from datetime import datetime, date

def get_db():
    if "db" not in st.session_state:
        key_dict = json.loads(st.secrets["textkey"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        st.session_state.db = firestore.Client(credentials=creds, project="wendleydesenvolvimento")
    return st.session_state.db

def verificar_login(usuario, senha):
    # Regra inicial hardcoded solicitada
    if usuario == "admin" and senha == "admin123":
        return {"nome": "Administrador Master", "role": "adm"}
    return None

def obter_tickets_db(data_alvo):
    db = get_db()
    docs = db.collection("entregas").where("data_entrega", "==", data_alvo).stream()
    return [doc.to_dict()["payload"] for doc in docs]

def obter_datas_disponiveis_db():
    db = get_db()
    # Firestore não tem 'GROUP BY' nativo fácil como SQL, então puxamos as datas únicas
    docs = db.collection("entregas").select(["data_entrega"]).stream()
    datas = {}
    for doc in docs:
        d = doc.to_dict().get("data_entrega")
        if d:
            datas[d] = datas.get(d, 0) + 1
    return [{"data": k, "total": v} for k, v in sorted(datas.items(), reverse=True)]

def obter_vinculo_db(chave):
    db = get_db()
    doc = db.collection("de_para_motoristas").document(chave).get()
    if doc.exists:
        return doc.to_dict().get("nome_motorista", chave)
    return chave

def salvar_vinculo_db(chave, nome):
    db = get_db()
    db.collection("de_para_motoristas").document(chave).set({"nome_motorista": nome})

def deletar_rota_db(rota_original, data_alvo):
    db = get_db()
    docs = db.collection("entregas").where("rota", "==", rota_original).where("data_entrega", "==", data_alvo).stream()
    batch = db.batch()
    for doc in docs:
        batch.delete(doc.reference)
    batch.commit()
