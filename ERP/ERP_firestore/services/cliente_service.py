import streamlit as st
from db import get_db, agora_iso

COL = "clientes"


def cadastrar_cliente(**dados) -> str:
    if not dados.get("nome") or not dados.get("cpf_cnpj"):
        raise ValueError("Nome e CPF/CNPJ são obrigatórios.")
    db = get_db()
    existentes = list(db.collection(COL).where("cpf_cnpj", "==", dados["cpf_cnpj"]).stream())
    if existentes:
        raise ValueError("Já existe cliente cadastrado com esse CPF/CNPJ.")
    dados["ativo"] = True
    dados["criado_em"] = agora_iso()
    ref = db.collection(COL).document()
    dados["id"] = ref.id
    ref.set(dados)
    listar_clientes.clear()
    return ref.id


def atualizar_cliente(cliente_id: str, **dados):
    get_db().collection(COL).document(cliente_id).update(dados)
    listar_clientes.clear()


@st.cache_data(ttl=30, show_spinner=False)
def listar_clientes(apenas_ativos=True) -> list:
    docs = get_db().collection(COL).stream()
    out = [d.to_dict() for d in docs]
    if apenas_ativos:
        out = [c for c in out if c.get("ativo", True)]
    return sorted(out, key=lambda c: c.get("nome", ""))


def buscar_cliente(termo: str) -> list:
    """Busca local (em memória) por nome ou CPF/CNPJ — usado na ABA VENDA.
    Firestore não faz busca por substring nativamente; como a base de
    clientes tende a ser pequena/média, filtrar em memória sobre a lista
    já cacheada é mais simples do que manter um índice de busca à parte."""
    termo = (termo or "").strip().lower()
    if not termo:
        return listar_clientes()
    return [
        c for c in listar_clientes()
        if termo in c.get("nome", "").lower() or termo in c.get("cpf_cnpj", "").lower()
    ]
