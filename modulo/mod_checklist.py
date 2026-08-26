"""
mod_checklist.py
Ponto de entrada do módulo de Checklist no Painel — chamado pelo roteamento
do main.py (dentro de _executar_modulo_protegido, já blindado contra erro).

Toda a lógica de verdade vive no pacote checklist/ (mesmo padrão já usado
pelo pacote tickets/): cada aba é uma tela própria, falando com a API de
Checklist (FastAPI + Postgres, hospedada separadamente no Render).
"""
import streamlit as st

from checklist import api_client as api
from checklist.estrutura import renderizar_estrutura
from checklist.colaboradores import renderizar_colaboradores
from checklist.editor import renderizar_editor
from checklist.aplicacao import renderizar_aplicacao
from checklist.planos_acao import renderizar_planos_acao
from checklist.dashboard import renderizar_dashboard


def renderizar_checklist(papel, user=None):
    if not api.garantir_token():
        return

    aba_estrutura, aba_colab, aba_editor, aba_aplicacao, aba_planos, aba_dash = st.tabs(
        ["🏬 Estrutura", "👤 Colaboradores", "📋 Editor de Checklist",
         "▶️ Aplicação", "🛠️ Planos de Ação", "📊 Dashboard"]
    )
    with aba_estrutura:
        renderizar_estrutura()
    with aba_colab:
        renderizar_colaboradores()
    with aba_editor:
        renderizar_editor()
    with aba_aplicacao:
        renderizar_aplicacao()
    with aba_planos:
        renderizar_planos_acao()
    with aba_dash:
        renderizar_dashboard()
