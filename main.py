import streamlit as st
import pandas as pd
from database import verificar_login, obter_datas_disponiveis_db, obter_tickets_db
from modulo.mod_rastreio import renderizar_rastreio
from modulo.mod_tickets import renderizar_tickets # Você criará este arquivo
import os
import base64

st.set_page_config(page_title="Monitoramento · KingStar", layout="wide", page_icon="🚚")

# --- FUNÇÕES DE APOIO ---
def carregar_logo_base64(caminho_img):
    if os.path.exists(caminho_img):
        with open(caminho_img, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode()
    return None

# --- LOGIN ---
if "user" not in st.session_state: st.session_state.user = None

if not st.session_state.user:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        logo_b64 = carregar_logo_base64("logo.png")
        if logo_b64:
            st.markdown(f'<div style="text-align:center;"><img src="data:image/png;base64,{logo_b64}" style="height:80px;margin-bottom:20px;"></div>', unsafe_allow_html=True)
        st.markdown("<h2 style='text-align:center;'>🔐 Acesso Restrito</h2>", unsafe_allow_html=True)
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary", use_container_width=True):
            user = verificar_login(usuario, senha)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Credenciais inválidas.")
    st.stop()

# --- ÁREA LOGADA ---
user = st.session_state.user
papel = user['role']

with st.sidebar:
    st.success(f"👤 {user['nome']}\n\nNível: **{papel.upper()}**")
    if st.button("Sair"):
        st.session_state.user = None
        st.rerun()
    st.markdown("---")

# --- NAVEGAÇÃO PRINCIPAL ---
aba_rastreio, aba_tickets = st.tabs(["🚚 Rastreio", "🎫 Tickets"])

with aba_rastreio:
    # A lógica que estava no seu código original agora vive nesta função importada
    renderizar_rastreio(papel)

with aba_tickets:
    # A lógica de tickets será implementada aqui
    renderizar_tickets(papel)
