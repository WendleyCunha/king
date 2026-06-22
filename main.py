import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import os
import time
import base64

from database import (verificar_login, criar_usuario, listar_usuarios, 
                      deletar_usuario, obter_tickets_db, obter_datas_disponiveis_db)
from modulo.mod_rastreio import renderizar_rastreio

# Fallback gracioso caso o mod_tickets ainda não tenha sido criado por você
try:
    from modulo.mod_tickets import renderizar_tickets
except ImportError:
    def renderizar_tickets(papel):
        st.info("🚧 Módulo de Tickets em desenvolvimento...")

st.set_page_config(page_title="Monitoramento · KingStar", layout="wide", page_icon="🚚")

# --- FUNÇÕES GERAIS ---
def carregar_logo_base64(caminho_img):
    if os.path.exists(caminho_img):
        with open(caminho_img, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode()
    return None

# --- LOGIN E SESSÃO ---
if "user" not in st.session_state: st.session_state.user = None

if not st.session_state.user:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        logo_b64 = carregar_logo_base64("logo.png")
        if logo_b64:
            st.markdown(f'<div style="text-align: center;"><img src="data:image/png;base64,{logo_b64}" style="height: 80px; margin-bottom: 20px;"></div>', unsafe_allow_html=True)
        
        st.markdown("<h2 style='text-align: center; color: #2c3e50;'>🔐 Acesso Restrito</h2>", unsafe_allow_html=True)
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary", use_container_width=True):
            user = verificar_login(usuario, senha)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Credenciais inválidas. Verifique usuário e senha.")
    st.stop()

# --- ÁREA LOGADA ---
user = st.session_state.user
papel = user['role']

# CSS Global (KPIs e Headings)
st.markdown("""
<style>
    .header-container { background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%); border-left: 6px solid #C9A84C; border-radius: 12px; padding: 20px 24px; margin-bottom: 28px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); display: flex; align-items: center; }
    .kpi-card { background: #ffffff; border-radius: 12px; padding: 20px 16px; text-align: center; border-top: 4px solid #C9A84C; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05); height: 100%; }
    .kpi-label { color: #64778d; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; }
    .kpi-value { color: #2c3e50; font-size: 2.2rem; font-weight: 800; }
    .kpi-sub { color: #C9A84C; font-size: 0.85rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR (Controle Global) ---
with st.sidebar:
    st.success(f"👤 {user['nome']}\n\nNível: **{papel.upper()}**")
    if st.button("Sair"):
        st.session_state.user = None
        st.rerun()
    st.markdown("---")
    st.markdown("### 📅 Período de Consulta")
    
    datas_db = obter_datas_disponiveis_db()
    hoje, ontem = date.today().isoformat(), (date.today() - timedelta(days=1)).isoformat()
    datas_disp = [d["data"] for d in datas_db]
    opcoes_datas = []
    
    if hoje in datas_disp or not datas_disp: opcoes_datas.append(f"Hoje ({hoje})")
    if ontem in datas_disp: opcoes_datas.append(f"Ontem ({ontem})")
    for item in datas_db:
        if item["data"] not in (hoje, ontem): 
            opcoes_datas.append(f"{datetime.strptime(item['data'], '%Y-%m-%d').strftime('%d/%m/%Y')} — {item['total']} entregas")

    data_sel = st.selectbox("📆 Escolha o Dia:", opcoes_datas)
    data_consulta = hoje if "Hoje" in data_sel else ontem if "Ontem" in data_sel else datetime.strptime(data_sel.split("—")[0].strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    is_hoje = (data_consulta == hoje)
    auto_refresh = st.checkbox("🔄 Atualização em Tempo Real", value=is_hoje)

# --- HEADER (Comum a todas as abas) ---
logo_b64 = carregar_logo_base64("logo.png")
html_logo = f'<img src="data:image/png;base64,{logo_b64}" style="height: 55px; margin-right: 20px;">' if logo_b64 else ''
st.markdown(f"""
<div class="header-container">
    {html_logo}
    <div>
        <h1 style="color:#2c3e50; margin:0; font-size:1.8rem; font-weight:800;">Painel Integrado · KingStar</h1>
        <p style="color:#64778d; margin:4px 0 0; font-size:1rem; font-weight:500;">Eco 360º · Rastreio e Operações · <span style="color:#C9A84C;">{"🕐 Tempo Real" if is_hoje else data_consulta}</span></p>
    </div>
</div>
""", unsafe_allow_html=True)

# Coleta de Dados Base
df_principal = pd.DataFrame(obter_tickets_db(data_consulta))

# --- NAVEGAÇÃO PRINCIPAL ---
abas_principais = ["🚚 Rastreio", "🎫 Tickets"]
if papel == "adm": abas_principais.append("⚙️ Configurações (ADM)")

abas = st.tabs(abas_principais)

with abas[0]:
    renderizar_rastreio(df_principal, data_consulta, papel)

with abas[1]:
    renderizar_tickets(papel)

# --- ABA DE CONFIGURAÇÕES (Admin Global) ---
if "⚙️ Configurações (ADM)" in abas_principais:
    with abas[2]:
        st.subheader("👥 Gestão de Acessos")
        
        with st.expander("➕ Cadastrar Novo Usuário", expanded=True):
            with st.form("form_novo_user"):
                c1, c2 = st.columns(2)
                novo_nome = c1.text_input("Nome Completo")
                novo_user = c2.text_input("Usuário (Login)")
                nova_senha = c1.text_input("Senha", type="password")
                novo_nivel = c2.selectbox("Nível de Acesso", ["operacional", "supervisor", "adm"])
                if st.form_submit_button("Criar Acesso"):
                    if novo_nome and novo_user and nova_senha:
                        criar_usuario(novo_nome, novo_user, nova_senha, novo_nivel)
                        st.success(f"Usuário {novo_user} criado com sucesso!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("Por favor, preencha todos os campos.")

        st.markdown("---")
        st.write("**Usuários Ativos no Sistema**")
        lista_users = listar_usuarios()
        if lista_users:
            for i, u in enumerate(lista_users):
                username_limpo = u.get('usuario') if u.get('usuario') else f"usuario_{i}"
                col_u1, col_u2, col_u3, col_u4 = st.columns([2, 2, 2, 1])
                col_u1.write(f"**{u.get('nome', 'Sem Nome')}**")
                col_u2.write(f"Login: `{username_limpo}`")
                col_u3.write(f"Nível: {str(u.get('role', 'operacional')).upper()}")
                
                if col_u4.button("🗑️", key=f"del_{username_limpo}_{i}"):
                    if username_limpo != "admin":
                        deletar_usuario(username_limpo)
                        st.rerun()

# --- ATUALIZAÇÃO EM TEMPO REAL ---
if auto_refresh and is_hoje and not df_principal.empty:
    time.sleep(15)
    st.rerun()
