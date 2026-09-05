"""
Módulo ERP (vendas, estoque, logística, RH, financeiro, fiscal) para o
Painel KingStar.

Diferente do mod_checklist.py (que fala com uma API própria em outro
servidor), o ERP mora dentro do mesmo repositório, no pacote `erp/`, e usa
Firestore direto — só que num banco separado ("erp", ver erp/db.py) pra
não misturar coleções com o painel ("portal"). O login é o mesmo do
Painel: quem já autenticou em main.py não loga de novo aqui, e as
permissões por ABA do ERP (ver erp/auth.py) são uma camada adicional em
cima do que a pessoa já é no Painel (nível ADM do Painel = acesso total
automático ao ERP).
"""
import streamlit as st
from erp.auth import ABAS, pode_visualizar, pode_editar

from erp.views import (
    cadastro_view, produto_view, venda_view, agendar_view, encomendar_view,
    logistica_view, empresa_view, financeiro_view, fiscal_view, rh_view,
    diretoria_view,
)

DEFINICAO_ABAS = [
    ("CADASTRO", "📇 Cadastro"),
    ("PRODUTO", "📦 Produto"),
    ("VENDA", "🛒 Venda"),
    ("AGENDAR", "📅 Agendar"),
    ("ENCOMENDAR", "🧾 Encomendar"),
    ("LOGISTICA", "🚚 Logística"),
    ("EMPRESA", "🏢 Empresa"),
    ("FINANCEIRO", "💰 Financeiro"),
    ("FISCAL", "🧾 Fiscal"),
    ("RH", "👥 RH"),
    ("DIRETORIA", "🏛️ Diretoria"),
]


def _renderizar_aba(codigo: str, login: str, editar: bool):
    if codigo == "CADASTRO":
        cadastro_view.render(editar)
    elif codigo == "PRODUTO":
        produto_view.render(editar, login)
    elif codigo == "VENDA":
        venda_view.render(editar, login)
    elif codigo == "AGENDAR":
        agendar_view.render(editar)
    elif codigo == "ENCOMENDAR":
        encomendar_view.render()
    elif codigo == "LOGISTICA":
        logistica_view.render(editar)
    elif codigo == "EMPRESA":
        empresa_view.render(editar)
    elif codigo == "FINANCEIRO":
        financeiro_view.render()
    elif codigo == "FISCAL":
        fiscal_view.render()
    elif codigo == "RH":
        rh_view.render(editar)
    elif codigo == "DIRETORIA":
        diretoria_view.render(editar, login)


def renderizar_erp(papel: str, user: dict = None):
    login = (user or {}).get("usuario", "")

    abas_visiveis = [(c, r) for c, r in DEFINICAO_ABAS if pode_visualizar(papel, login, c)]
    if not abas_visiveis:
        st.info(
            "Você ainda não tem acesso a nenhuma aba do ERP. Peça pra alguém com "
            "acesso à ABA DIRETORIA do ERP liberar o que você precisa."
        )
        return

    tabs = st.tabs([rotulo for _, rotulo in abas_visiveis])
    for tab, (codigo, _rotulo) in zip(tabs, abas_visiveis):
        with tab:
            _renderizar_aba(codigo, login, pode_editar(papel, login, codigo))
