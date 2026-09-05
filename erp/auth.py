"""
Permissões do ERP, por ABA.

O login/senha continuam sendo os do Painel principal (main.py já cuidou
disso antes de chamar o ERP) — aqui só guardamos, por login, o que cada
usuário pode fazer dentro de cada ABA do ERP. Fica na mesma base "erp"
(coleção 'permissoes_erp', doc id = login do painel), separado da
coleção 'usuarios' do painel principal pra não misturar responsabilidade:
quem pode logar é problema do painel; o que pode fazer dentro do ERP é
problema daqui.

Exceção: papel == "adm" no painel principal tem EDITAR em tudo
automaticamente (mesmo espírito do admin master do painel) — quem tem
esse nível já é confiável pra tudo, não precisa configurar aba por aba.
"""
import streamlit as st
from erp.db import get_db, agora_iso

ABAS = [
    "CADASTRO", "PRODUTO", "VENDA", "AGENDAR", "ENCOMENDAR", "LOGISTICA",
    "EMPRESA", "FINANCEIRO", "FISCAL", "RH", "DIRETORIA",
]
NIVEIS = ["NENHUM", "VISUALIZAR", "EDITAR"]

COL = "permissoes_erp"  # doc id = login do painel principal


def permissoes_padrao_vazias() -> dict:
    return {aba: "NENHUM" for aba in ABAS}


@st.cache_data(ttl=20, show_spinner=False)
def permissoes_do_usuario(login: str) -> dict:
    doc = get_db().collection(COL).document(login).get()
    if doc.exists:
        return doc.to_dict().get("permissoes", permissoes_padrao_vazias())
    return permissoes_padrao_vazias()


def pode_visualizar(papel: str, login: str, aba: str) -> bool:
    if papel == "adm":
        return True
    return permissoes_do_usuario(login).get(aba, "NENHUM") in ("VISUALIZAR", "EDITAR")


def pode_editar(papel: str, login: str, aba: str) -> bool:
    if papel == "adm":
        return True
    return permissoes_do_usuario(login).get(aba, "NENHUM") == "EDITAR"


def tem_algum_acesso(papel: str, login: str) -> bool:
    """Usado pelo main.py pra decidir se mostra o botão 'ERP' na sidebar."""
    if papel == "adm":
        return True
    return any(v != "NENHUM" for v in permissoes_do_usuario(login).values())


def definir_permissao(login: str, aba: str, nivel: str):
    if aba not in ABAS:
        raise ValueError(f"Aba inválida: {aba}")
    if nivel not in NIVEIS:
        raise ValueError(f"Nível inválido: {nivel}")
    ref = get_db().collection(COL).document(login)
    doc = ref.get()
    permissoes = doc.to_dict().get("permissoes", permissoes_padrao_vazias()) if doc.exists else permissoes_padrao_vazias()
    permissoes[aba] = nivel
    ref.set({"login": login, "permissoes": permissoes, "atualizado_em": agora_iso()})
    permissoes_do_usuario.clear()
