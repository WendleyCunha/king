import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import os, time, base64

from database import (
    verificar_login, criar_usuario, listar_usuarios, deletar_usuario,
    atualizar_modulos_usuario, obter_tickets_db, obter_datas_disponiveis_db,
    modulos_do_usuario, tem_permissao, pode_editar, pode_exportar, pode_deletar,
    MODULOS_PADRAO,
)
from modulo.mod_rastreio import renderizar_rastreio

try:
    from modulo.mod_tickets import renderizar_tickets
except ImportError:
    def renderizar_tickets(papel): st.info("🚧 Módulo de Tickets em desenvolvimento...")

st.set_page_config(page_title="KingStar · Painel Integrado",
                   layout="wide", page_icon="🚚",
                   initial_sidebar_state="expanded")

BRT = timezone(timedelta(hours=-3))
def agora_brt(): return datetime.now(BRT).strftime("%H:%M:%S")
def hoje_brt():  return datetime.now(BRT).date().isoformat()
def ontem_brt(): return (datetime.now(BRT).date() - timedelta(days=1)).isoformat()

def get_logo():
    if os.path.exists("logo.png"):
        with open("logo.png","rb") as f: return base64.b64encode(f.read()).decode()
    return None

st.markdown("""
<style>
.stApp { background-color: #f4f6f9; }
.block-container { padding-top: 4rem !important; }

/* Sidebar clara */
section[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    border-right: 1px solid #dbe2e9 !important;
}
section[data-testid="stSidebar"] .stButton > button {
    border: 1px solid #e2e8f0 !important;
    background: #f8f9fa !important;
    color: #2c3e50 !important;
    font-size: 0.88rem !important;
    border-radius: 8px !important;
    margin-bottom: 4px !important;
    padding: 9px 14px !important;
    width: 100% !important;
    text-align: left !important;
    font-weight: 500 !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: #f0f2f5 !important; border-color: #C9A84C !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: rgba(201,168,76,0.1) !important;
    border-color: #C9A84C !important;
    color: #7a5f1a !important; font-weight: 700 !important;
}
.nav-section { font-size:0.68rem; font-weight:700; text-transform:uppercase;
    letter-spacing:1.5px; color:#9aabb8; padding:14px 4px 6px; display:block; }
.nav-soon { padding:8px 14px; font-size:0.85rem; color:#b0bec5;
    display:flex; justify-content:space-between; align-items:center; margin-bottom:2px; }
.soon-tag { font-size:0.6rem; background:#f0f2f5; color:#9aabb8;
    padding:2px 7px; border-radius:8px; font-weight:600; }

/* Cabeçalho */
.ks-header {
    background:#ffffff; border-left:5px solid #C9A84C;
    border-radius:12px; padding:16px 24px; margin-bottom:20px;
    box-shadow:0 2px 8px rgba(0,0,0,0.05);
    display:flex; align-items:center; gap:18px;
}
.ks-title { font-size:1.4rem; font-weight:800; color:#2c3e50; margin:0; }
.ks-sub { font-size:0.8rem; color:#64778d; margin-top:3px; }
.ks-pill { display:inline-block; padding:3px 10px; border-radius:10px;
    font-size:0.72rem; font-weight:700; margin-right:3px;
    background:rgba(52,152,219,.1); color:#2471a3; }
.ks-nivel { display:inline-block; padding:3px 10px; border-radius:10px;
    font-size:0.72rem; font-weight:700;
    background:rgba(201,168,76,.15); color:#7a5f1a; }

/* KPI */
.kpi-card { background:#fff; border-radius:12px; padding:18px 12px;
    text-align:center; box-shadow:0 2px 8px rgba(0,0,0,0.05); }
.kpi-card.gold  { border-top:4px solid #C9A84C; }
.kpi-card.green { border-top:4px solid #27ae60; }
.kpi-card.blue  { border-top:4px solid #2980b9; }
.kpi-card.red   { border-top:4px solid #e74c3c; }
.kpi-card.gray  { border-top:4px solid #95a5a6; }
.kpi-label { color:#64778d; font-size:0.72rem; font-weight:700;
    text-transform:uppercase; letter-spacing:1px; }
.kpi-value { font-size:2rem; font-weight:800; color:#2c3e50; line-height:1.2; margin:4px 0 2px; }
.kpi-sub { font-size:0.78rem; font-weight:600; color:#C9A84C; }
.kpi-card.green .kpi-value { color:#27ae60; }
.kpi-card.blue  .kpi-value { color:#2980b9; }
.kpi-card.red   .kpi-value { color:#e74c3c; }

/* Cards motorista */
.driver-card { background:#fff; border:1px solid #e2e8f0; border-radius:12px;
    padding:14px; margin-bottom:6px; border-top:4px solid #C9A84C; }
.tag { display:inline-block; padding:3px 9px; border-radius:10px;
    font-size:0.73rem; font-weight:700; margin:2px; }
.tg { background:rgba(201,168,76,.12); color:#7a5f1a; }
.tn { background:rgba(46,204,113,.1);  color:#1e8449; }
.tb { background:rgba(52,152,219,.1);  color:#2471a3; }
.tr { background:rgba(231,76,60,.1);   color:#a93226; }
</style>
""", unsafe_allow_html=True)

# ── LOGIN ─────────────────────────────────────────────────────────
if "user"         not in st.session_state: st.session_state.user = None
if "modulo_ativo" not in st.session_state: st.session_state.modulo_ativo = "rastreio"

if st.session_state.user is None:
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col, _ = st.columns([1,1,1])
    with col:
        lb = get_logo()
        if lb:
            st.markdown(f'<div style="text-align:center;margin-bottom:20px;">'
                        f'<img src="data:image/png;base64,{lb}" style="height:80px;"></div>',
                        unsafe_allow_html=True)
        st.markdown("<h2 style='text-align:center;color:#2c3e50;margin-bottom:20px;'>🔐 Acesso Restrito</h2>",
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

user  = st.session_state.user
papel = user["role"]
mods  = modulos_do_usuario(user)

# ── SIDEBAR ───────────────────────────────────────────────────────
with st.sidebar:
    lb = get_logo()
    if lb:
        st.markdown(f'<div style="text-align:center;padding:18px 0 14px;">'
                    f'<img src="data:image/png;base64,{lb}" style="height:50px;"></div>',
                    unsafe_allow_html=True)
    st.markdown('<div style="border-top:1px solid #e2e8f0;margin:0 8px 10px;"></div>',
                unsafe_allow_html=True)
    st.markdown('<span class="nav-section">Operacional</span>', unsafe_allow_html=True)

    for key, label in [("rastreio","Rastreio"),("tickets","Tickets")]:
        if key not in mods: continue
        ativo = st.session_state.modulo_ativo == key
        if st.button(label, key=f"nav_{key}", use_container_width=True,
                     type="primary" if ativo else "secondary"):
            st.session_state.modulo_ativo = key
            st.rerun()

    if papel == "adm":
        ativo = st.session_state.modulo_ativo == "config"
        if st.button("Configuracoes", key="nav_config", use_container_width=True,
                     type="primary" if ativo else "secondary"):
            st.session_state.modulo_ativo = "config"
            st.rerun()

    st.markdown('<div style="border-top:1px solid #e2e8f0;margin:14px 8px 10px;"></div>',
                unsafe_allow_html=True)
    st.markdown('<span class="nav-section">Em Breve</span>', unsafe_allow_html=True)
    for lbl in ["Painel Atendente","ERP Base","Analytics"]:
        st.markdown(f'<div class="nav-soon">{lbl}<span class="soon-tag">em breve</span></div>',
                    unsafe_allow_html=True)
    st.markdown('<div style="border-top:1px solid #e2e8f0;margin:14px 8px 8px;"></div>',
                unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.7rem;color:#b0bec5;padding:0 4px 16px;">'
                'v2.0 · Firebase · Brasília (BRT)</div>', unsafe_allow_html=True)

# ── CABEÇALHO — sem seletor de data ───────────────────────────────
lb        = get_logo()
logo_html = (f'<img src="data:image/png;base64,{lb}" style="height:50px;margin-right:18px;">'
             if lb else "")
pills = "".join(
    f'<span class="ks-pill">{"Rastreio" if m=="rastreio" else "Tickets"}</span>'
    for m in mods if m in ("rastreio","tickets")
)

hc1, hc2 = st.columns([9, 1])
with hc1:
    st.markdown(f"""
    <div class="ks-header">
        {logo_html}
        <div style="flex:1;">
            <div class="ks-title">Painel de Entregas · KingStar</div>
            <div class="ks-sub">
                KingStar Colchoes &nbsp;·&nbsp; Eco 360° &nbsp;·&nbsp; SimpliRoute &nbsp;·&nbsp;
                <span style="color:#C9A84C;font-weight:700;">Tempo Real</span>
                &nbsp;·&nbsp; {agora_brt()}
            </div>
        </div>
        <div style="text-align:right;white-space:nowrap;">
            <div style="font-size:0.88rem;font-weight:700;color:#2c3e50;margin-bottom:4px;">{user['nome']}</div>
            <div>{pills}<span class="ks-nivel">{papel.upper()}</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)
with hc2:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Sair", key="btn_sair", use_container_width=True):
        st.session_state.user = None
        st.rerun()

# ── DADOS e ROTEAMENTO ────────────────────────────────────────────
datas_db   = obter_datas_disponiveis_db()
hoje       = hoje_brt()
ontem      = ontem_brt()
modulo_ativo = st.session_state.modulo_ativo

if modulo_ativo == "rastreio" and tem_permissao(user, "rastreio"):
    is_hoje = renderizar_rastreio(papel, user,
                                  datas_db=datas_db, pode_exp=pode_exportar(user))
    # Auto-refresh silencioso só quando logado e no dia atual
    if is_hoje and st.session_state.user is not None:
        time.sleep(20)
        st.rerun()

elif modulo_ativo == "tickets" and tem_permissao(user, "tickets"):
    renderizar_tickets(papel)

elif modulo_ativo == "config" and papel == "adm":
    st.subheader("⚙️ Configurações")
    aba_u, aba_m = st.tabs(["👥 Usuários", "🔒 Permissões por Módulo"])

    with aba_u:
        with st.expander("➕ Cadastrar Novo Usuário", expanded=True):
            with st.form("form_novo"):
                c1, c2  = st.columns(2)
                n_nome  = c1.text_input("Nome Completo")
                n_user  = c2.text_input("Login")
                n_senha = c1.text_input("Senha", type="password")
                n_nivel = c2.selectbox("Nível", ["operacional","supervisor","adm"])
                ma, mb  = st.columns(2)
                m_r     = ma.checkbox("Rastreio", value=True)
                m_t     = mb.checkbox("Tickets", value=n_nivel in ("supervisor","adm"))
                if st.form_submit_button("Criar"):
                    if n_nome and n_user and n_senha:
                        ms = [m for m,v in [("rastreio",m_r),("tickets",m_t),("exportar",m_r)] if v]
                        criar_usuario(n_nome, n_user, n_senha, n_nivel, ms)
                        st.success(f"Usuário **{n_user}** criado!")
                        time.sleep(1); st.rerun()
                    else: st.warning("Preencha todos os campos.")
        st.markdown("---")
        for i_u, u in enumerate(listar_usuarios()):
            uname = u.get("usuario", f"u{i_u}")
            with st.expander(f"**{u.get('nome','—')}** · `{uname}` · {u.get('role','—').upper()}"):
                if uname != "admin":
                    if st.button("Excluir", key=f"del_{uname}_{i_u}"):
                        deletar_usuario(uname); st.rerun()

    with aba_m:
        for i_u, u in enumerate(listar_usuarios()):
            uname = u.get("usuario", f"u{i_u}")
            umods = u.get("modulos", MODULOS_PADRAO.get(u.get("role","operacional"), []))
            with st.expander(f"**{u.get('nome','—')}** · `{uname}`"):
                ma, mb = st.columns(2)
                nr = ma.checkbox("Rastreio", value="rastreio" in umods, key=f"r_{uname}")
                nt = mb.checkbox("Tickets",  value="tickets"  in umods, key=f"t_{uname}")
                if st.button("Salvar", key=f"sv_{uname}", type="primary"):
                    ns = [m for m,v in [("rastreio",nr),("tickets",nt),("exportar",nr)] if v]
                    atualizar_modulos_usuario(uname, ns)
                    st.success("Salvo!"); time.sleep(.5); st.rerun()
else:
    st.warning("Módulo não disponível para seu perfil.")
