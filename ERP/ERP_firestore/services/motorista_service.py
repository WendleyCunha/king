import streamlit as st
from db import get_db, hash_senha, agora_iso

COL_USUARIOS = "usuarios"
COL_CARGAS = "cargas"


def cadastrar_motorista(nome: str, placa: str, login: str, senha: str) -> str:
    """
    Motorista é um usuário do sistema (reaproveita a coleção 'usuarios',
    igual ao Painel KingStar) — só que sem permissão de EDITAR/VISUALIZAR
    em nenhuma ABA do ERP. O login e a senha aqui são o que ele usa no
    APP ENTREGAS pra ver só as próprias entregas.
    """
    login = (login or "").strip().lower()
    if not login:
        raise ValueError("Informe um login para o motorista.")
    ref = get_db().collection(COL_USUARIOS).document(login)
    if ref.get().exists:
        raise ValueError("Já existe um usuário com esse login.")
    ref.set({
        "nome": nome, "usuario": login, "senha_hash": hash_senha(senha),
        "placa": placa, "is_motorista": True, "ativo": True,
        "permissoes": {}, "criado_em": agora_iso(),
    })
    listar_motoristas.clear()
    return login


@st.cache_data(ttl=30, show_spinner=False)
def listar_motoristas(apenas_ativos=True) -> list:
    docs = get_db().collection(COL_USUARIOS).where("is_motorista", "==", True).stream()
    out = [d.to_dict() for d in docs]
    if apenas_ativos:
        out = [m for m in out if m.get("ativo", True)]
    return sorted(out, key=lambda m: m.get("nome", ""))


def entregas_por_motorista() -> list:
    """
    Quantidade de entregas por motorista — mesma consulta que alimenta o
    APP ENTREGAS (cada motorista só vê onde 'motorista_login' == o próprio login).
    """
    motoristas = listar_motoristas()
    cargas = list(get_db().collection(COL_CARGAS).stream())
    resultado = []
    for m in motoristas:
        total = sum(
            len(c.to_dict().get("pedidos", []))
            for c in cargas
            if c.to_dict().get("motorista_login") == m["usuario"]
            and c.to_dict().get("status") == "FINALIZADA"
        )
        resultado.append({"motorista": m, "total_entregas": total})
    return resultado


def entregas_do_motorista(motorista_login: str) -> list:
    """Usado pelo APP ENTREGAS: só as entregas daquele motorista específico."""
    db = get_db()
    cargas = db.collection(COL_CARGAS).where("motorista_login", "==", motorista_login).stream()
    numeros = []
    for c in cargas:
        numeros.extend(c.to_dict().get("pedidos", []))
    if not numeros:
        return []
    # Firestore 'in' aceita no máximo 30 itens por consulta — em volumes
    # maiores, quebrar 'numeros' em lotes de 30 antes deste where().
    docs = db.collection("pedidos").where("numero", "in", numeros[:30]).stream()
    return [d.to_dict() for d in docs]
