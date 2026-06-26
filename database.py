import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json, hashlib
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))

def get_db():
    if "db" not in st.session_state:
        key_dict = json.loads(st.secrets["textkey"])
        creds    = service_account.Credentials.from_service_account_info(key_dict)
        st.session_state.db = firestore.Client(
            credentials=creds, project=creds.project_id, database="portal"
        )
    return st.session_state.db

def hash_senha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

MODULOS_PADRAO = {
    "adm":         ["rastreio","tickets","exportar"],
    "supervisor":  ["rastreio","tickets","exportar"],
    "operacional": ["rastreio"],
}

def modulos_do_usuario(user: dict) -> list:
    return user.get("modulos") or MODULOS_PADRAO.get(user.get("role","operacional"), ["rastreio"])

def tem_permissao(user: dict, modulo: str) -> bool:
    return modulo in modulos_do_usuario(user)

def pode_editar(user: dict) -> bool:
    return user.get("role") in ("supervisor","adm")

def pode_exportar(user: dict) -> bool:
    return "exportar" in modulos_do_usuario(user)

def pode_deletar(user: dict) -> bool:
    return user.get("role") == "adm"

# ── Auth ──────────────────────────────────────────────────────────
def verificar_login(usuario: str, senha: str):
    if usuario == "admin" and senha == "admin123":
        return {"nome":"Administrador Master","usuario":"admin",
                "role":"adm","modulos":["rastreio","tickets","exportar"]}
    doc = get_db().collection("usuarios").document(usuario).get()
    if doc.exists:
        d = doc.to_dict()
        if d.get("senha_hash") == hash_senha(senha):
            return d
    return None

def criar_usuario(nome, usuario, senha, role, modulos=None):
    if modulos is None:
        modulos = MODULOS_PADRAO.get(role, ["rastreio"])
    get_db().collection("usuarios").document(usuario).set({
        "nome": nome, "usuario": usuario,
        "senha_hash": hash_senha(senha),
        "role": role, "modulos": modulos,
    })

def alterar_senha_usuario(usuario: str, senha_atual: str, nova_senha: str):
    """Retorna (True, msg_sucesso) ou (False, msg_erro)."""
    if usuario == "admin":
        return False, "A senha do admin master não pode ser alterada aqui."
    doc = get_db().collection("usuarios").document(usuario).get()
    if not doc.exists:
        return False, "Usuário não encontrado."
    d = doc.to_dict()
    if d.get("senha_hash") != hash_senha(senha_atual):
        return False, "Senha atual incorreta."
    get_db().collection("usuarios").document(usuario).update(
        {"senha_hash": hash_senha(nova_senha)}
    )
    return True, "Senha alterada com sucesso! Faça login novamente."

def atualizar_modulos_usuario(usuario: str, modulos: list):
    get_db().collection("usuarios").document(usuario).update({"modulos": modulos})

def listar_usuarios():
    return [d.to_dict() for d in get_db().collection("usuarios").stream()]

def deletar_usuario(usuario):
    get_db().collection("usuarios").document(usuario).delete()

# ── Entregas ──────────────────────────────────────────────────────
def obter_tickets_db(data_alvo: str) -> list:
    docs = get_db().collection("entregas") \
                   .where("data_entrega","==",data_alvo).stream()
    return [d.to_dict().get("payload", d.to_dict()) for d in docs]

def obter_datas_disponiveis_db() -> list:
    docs  = get_db().collection("entregas").select(["data_entrega"]).stream()
    datas: dict = {}
    for d in docs:
        v = d.to_dict().get("data_entrega")
        if v: datas[v] = datas.get(v, 0) + 1
    return [{"data":k,"total":v} for k,v in sorted(datas.items(), reverse=True)]

# ── De-Para motoristas ────────────────────────────────────────────
def obter_vinculo_db(chave: str) -> str:
    doc = get_db().collection("de_para_motoristas").document(chave).get()
    return doc.to_dict().get("nome_motorista", chave) if doc.exists else chave

def salvar_vinculo_db(chave: str, nome: str):
    get_db().collection("de_para_motoristas").document(chave).set({"nome_motorista": nome})

def deletar_rota_db(rota: str, data: str):
    db    = get_db()
    docs  = db.collection("entregas").where("rota","==",rota).where("data_entrega","==",data).stream()
    batch = db.batch()
    for d in docs: batch.delete(d.reference)
    batch.commit()
