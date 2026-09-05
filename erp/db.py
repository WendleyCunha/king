import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json, hashlib
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))

# ══════════════════════════════════════════════════════════════════
# Conexão — igual ao padrão do Painel KingStar. Se quiser, o ERP pode
# usar um banco "portal" separado (ex: database="erp") pra não misturar
# coleções com o painel; só trocar o parâmetro `database` abaixo.
# ══════════════════════════════════════════════════════════════════
def get_db():
    if "db_erp" not in st.session_state:
        key_dict = json.loads(st.secrets["textkey"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        st.session_state.db_erp = firestore.Client(
            credentials=creds, project=creds.project_id, database="erp"
        )
    return st.session_state.db_erp


def hash_senha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def agora_str() -> str:
    return datetime.now(BRT).strftime("%d/%m/%Y %H:%M:%S")


def agora_iso() -> str:
    return datetime.now(BRT).isoformat()


# ══════════════════════════════════════════════════════════════════
# Numeração sequencial (PED-000001, NF-000001, VEND-0001...).
# Firestore não tem auto-incremento nativo, então usamos um documento
# contador e uma TRANSACTION pra garantir que dois usuários clicando ao
# mesmo tempo nunca recebam o mesmo número (a transaction do Firestore
# faz retry automático em caso de conflito de escrita concorrente).
# ══════════════════════════════════════════════════════════════════
def proximo_numero(nome_contador: str, prefixo: str, largura: int = 6) -> str:
    db = get_db()
    ref = db.collection("contadores").document(nome_contador)

    @firestore.transactional
    def _incrementar(transaction):
        snap = ref.get(transaction=transaction)
        atual = snap.to_dict().get("valor", 0) if snap.exists else 0
        novo = atual + 1
        transaction.set(ref, {"valor": novo})
        return novo

    transaction = db.transaction()
    novo_valor = _incrementar(transaction)
    return f"{prefixo}-{novo_valor:0{largura}d}"
