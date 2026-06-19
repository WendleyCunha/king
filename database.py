import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd

def get_db():
    if "db" not in st.session_state:
        key_dict = json.loads(st.secrets["textkey"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        st.session_state.db = firestore.Client(credentials=creds, project="wendleydesenvolvimento")
    return st.session_state.db

# Funções de Acesso
def verificar_login(email, senha):
    db = get_db()
    user_ref = db.collection("usuarios").where("email", "==", email).get()
    for doc in user_ref:
        data = doc.to_dict()
        import bcrypt
        if bcrypt.checkpw(senha.encode('utf-8'), data['senha_hash'].encode('utf-8')):
            return data
    return None

def listar_entregas(data_filtro=None):
    db = get_db()
    query = db.collection("entregas")
    if data_filtro:
        query = query.where("data_entrega", "==", data_filtro)
    return pd.DataFrame([doc.to_dict() for doc in query.stream()])

def deletar_entrega(doc_id):
    get_db().collection("entregas").document(doc_id).delete()
