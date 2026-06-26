import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, timezone
import os
import time
import base64

from database import (
    verificar_login, criar_usuario, listar_usuarios,
    deletar_usuario, obter_tickets_db, obter_datas_disponiveis_db
)
from modulo.mod_rastreio import renderizar_rastreio

try:
    from modulo.mod_tickets import renderizar_tickets
except ImportError:
    def renderizar_tickets(papel):
        st.info("🚧 Módulo de Tickets em desenvolvimento...")

st.set_page_config(
    page_title="Monitoramento · KingStar",
    layout="wide",
    page_icon="🚚"
)

BRT = timezone(timedelta(hours=-3))

def agora_brt() -> str:
    return datetime.now(BRT).strftime("%H:%M:%S")

def hoje_brt() -> str:
    return datetime.now(BRT).date().isoformat()

def ontem_brt() -> str:
    return (datetime.now(BRT).date() - timedelta(days=1)).isoformat()

def carregar_logo_base64(caminho):
    if os.path.exists(caminho):
        with open(caminho, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    _, col2, _ = st.columns([1, 1, 1])
    with col2:
        logo_b64 = carregar_logo_base64("logo.png")
        if logo_b64:
            st.markdown(
                f'<div style="text-align:center;">'
                f'<img src="data:image/png;base64,{logo_b64}" '
                f'style="height:80px;margin-bottom:20px;"></div>',
                unsafe_allow_html=True,
            )
        st.markdown("<h2 style='text-align:center;color:#2c3e50;'>🔐 Acesso Restrito</h2>",
                    unsafe_allow_html=True)
        usuario = st.text_input("Usuário")
        senha   = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary", use_container_width=True):
            user = verificar_login(usuario, senha)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Credenciais inválidas.")
    st.stop()

# ─────────────────────────────────────────────
# ÁREA LOGADA
# ─────────────────────────────────────────────
user  = st.session_state.user
papel = user["role"]

st.markdown("""
<style>
    .header-container {
        background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
        border-left: 6px solid #C9A84C; border-radius: 12px;
        padding: 20px 24px; margin-bottom: 28px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        display: flex; align-items: center;
    }
    .kpi-card {
        background: #ffffff; border-radius: 12px; padding: 20px 16px;
        text-align: center; border-top: 4px solid #C9A84C;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05); height: 100%;
    }
    .kpi-label { color: #64778d; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; }
    .kpi-value { color: #2c3e50; font-size: 2.2rem; font-weight: 800; }
    .kpi-sub   { color: #C9A84C; font-size: 0.85rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.success(f"👤 {user['nome']}\n\nNível: **{papel.upper()}**")
    if st.button("Sair"):
        st.session_state.user = None
        st.rerun()

    st.markdown("---")
    st.markdown("### 📅 Período de Consulta")

    datas_db    = obter_datas_disponiveis_db()
    hoje        = hoje_brt()
    ontem       = ontem_brt()
    datas_disp  = [d["data"] for d in datas_db]

    opcoes_datas = []
    if hoje in datas_disp or not datas_disp:
        opcoes_datas.append(f"Hoje ({hoje})")
    if ontem in datas_disp:
        opcoes_datas.append(f"Ontem ({ontem})")
    for item in datas_db:
        if item["data"] not in (hoje, ontem):
            try:
                label = f"{datetime.strptime(item['data'], '%Y-%m-%d').strftime('%d/%m/%Y')} — {item['total']} entregas"
            except:
                label = item["data"]
            opcoes_datas.append(label)

    if not opcoes_datas:
        opcoes_datas = [f"Hoje ({hoje})"]

    data_sel = st.selectbox("📆 Escolha o Dia:", opcoes_datas)

    if "Hoje" in data_sel:
        data_consulta = hoje
    elif "Ontem" in data_sel:
        data_consulta = ontem
    else:
        try:
            data_consulta = datetime.strptime(
                data_sel.split("—")[0].strip(), "%d/%m/%Y"
            ).strftime("%Y-%m-%d")
        except:
            data_consulta = hoje

    is_hoje      = (data_consulta == hoje)
    auto_refresh = st.checkbox("🔄 Atualização em Tempo Real", value=is_hoje)

# ─────────────────────────────────────────────
# CABEÇALHO
# ─────────────────────────────────────────────
logo_b64 = carregar_logo_base64("logo.png")
html_logo = (
    f'<img src="data:image/png;base64,{logo_b64}" style="height:55px;margin-right:20px;">'
    if logo_b64 else ""
)
st.markdown(f"""
<div class="header-container">
    {html_logo}
    <div>
        <h1 style="color:#2c3e50;margin:0;font-size:1.8rem;font-weight:800;">
            Painel Integrado · KingStar
        </h1>
        <p style="color:#64778d;margin:4px 0 0;font-size:1rem;font-weight:500;">
            Eco 360º &nbsp;·&nbsp; Rastreio e Operações &nbsp;·&nbsp;
            <span style="color:#C9A84C;">{"🕐 Tempo Real" if is_hoje else data_consulta}</span>
            &nbsp;·&nbsp;
            <span style="color:#aaa;font-size:0.85rem;">{agora_brt()}</span>
        </p>
    </div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# BUSCA DE DADOS
# CORREÇÃO CRÍTICA: sem cache — busca direto no Firestore toda vez.
# st.cache_data(ttl=15) causava retorno de dados antigos exatamente
# quando o rerun() era chamado após 15s de sleep.
# ─────────────────────────────────────────────
tickets_raw  = obter_tickets_db(data_consulta)
df_principal = pd.DataFrame(tickets_raw) if tickets_raw else pd.DataFrame()

# ─────────────────────────────────────────────
# NAVEGAÇÃO PRINCIPAL
# ─────────────────────────────────────────────
abas_nomes = ["🚚 Rastreio", "🎫 Tickets"]
if papel == "adm":
    abas_nomes.append("⚙️ Configurações (ADM)")

abas = st.tabs(abas_nomes)

with abas[0]:
    renderizar_rastreio(df_principal, data_consulta, papel)

with abas[1]:
    renderizar_tickets(papel)

if "⚙️ Configurações (ADM)" in abas_nomes:
    with abas[2]:
        st.subheader("👥 Gestão de Acessos")

        with st.expander("➕ Cadastrar Novo Usuário", expanded=True):
            with st.form("form_novo_user"):
                c1, c2    = st.columns(2)
                novo_nome = c1.text_input("Nome Completo")
                novo_user = c2.text_input("Usuário (Login)")
                nova_senha= c1.text_input("Senha", type="password")
                novo_nivel= c2.selectbox("Nível de Acesso",
                                         ["operacional", "supervisor", "adm"])
                if st.form_submit_button("Criar Acesso"):
                    if novo_nome and novo_user and nova_senha:
                        criar_usuario(novo_nome, novo_user, nova_senha, novo_nivel)
                        st.success(f"Usuário {novo_user} criado!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("Preencha todos os campos.")

        st.markdown("---")
        st.write("**Usuários Ativos**")
        for i, u in enumerate(listar_usuarios()):
            uname = u.get("usuario", f"user_{i}")
            c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
            c1.write(f"**{u.get('nome', '—')}**")
            c2.write(f"Login: `{uname}`")
            c3.write(f"Nível: {str(u.get('role', '—')).upper()}")
            if c4.button("🗑️", key=f"del_{uname}_{i}"):
                if uname != "admin":
                    deletar_usuario(uname)
                    st.rerun()

# ─────────────────────────────────────────────
# AUTO-REFRESH com contador regressivo
# CORREÇÃO: sem time.sleep() bloqueante — usa loop com sleep(1)
# para mostrar contador e permitir que o Streamlit respire.
# ─────────────────────────────────────────────
if auto_refresh and is_hoje:
    placeholder = st.empty()
    for i in range(15, 0, -1):
        placeholder.caption(f"🔄 Próxima atualização em {i}s…")
        time.sleep(1)
    placeholder.empty()
    st.rerun()
