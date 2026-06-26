import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, timezone
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

st.set_page_config(page_title="KingStar · Painel Integrado", layout="wide", page_icon="🚚",
                   initial_sidebar_state="expanded")

BRT = timezone(timedelta(hours=-3))
def agora_brt():   return datetime.now(BRT).strftime("%H:%M:%S")
def hoje_brt():    return datetime.now(BRT).date().isoformat()
def ontem_brt():   return (datetime.now(BRT).date() - timedelta(days=1)).isoformat()

def logo_b64():
    if os.path.exists("logo.png"):
        with open("logo.png","rb") as f: return base64.b64encode(f.read()).decode()
    return None

# ── CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Fundo geral */
.stApp { background-color: #f4f6f9; }
.block-container { padding-top: 0.5rem !important; }

/* ── Sidebar clara ── */
section[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    border-right: 1px solid #dbe2e9 !important;
}
/* Remove ícone/seta do collapse da sidebar */
section[data-testid="stSidebar"] button[data-testid="baseButton-headerNoPadding"] { display: none !important; }
/* Botões da sidebar sem borda/sombra padrão do Streamlit */
section[data-testid="stSidebar"] .stButton > button {
    border: 1px solid #dbe2e9 !important;
    background: #f8f9fa !important;
    color: #2c3e50 !important;
    font-weight: 500 !important;
    font-size: 0.88rem !important;
    text-align: left !important;
    border-radius: 8px !important;
    margin-bottom: 4px !important;
    padding: 10px 14px !important;
    width: 100% !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: #f0f2f5 !important;
    border-color: #C9A84C !important;
}
/* Botão ativo (primary) na sidebar */
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: rgba(201,168,76,0.12) !important;
    border-color: #C9A84C !important;
    color: #8a6a1e !important;
    font-weight: 700 !important;
}
/* Títulos de seção na sidebar */
.nav-section-title {
    font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.5px; color: #9aabb8;
    padding: 14px 4px 6px; margin: 0; display: block;
}
/* Item "em breve" na sidebar */
.nav-soon {
    padding: 8px 14px; border-radius: 8px; font-size: 0.85rem;
    color: #b0bec5; display: flex; align-items: center;
    justify-content: space-between; margin-bottom: 2px;
}
.soon-badge {
    font-size: 0.62rem; background: #f0f2f5; color: #9aabb8;
    padding: 2px 7px; border-radius: 8px; font-weight: 600;
}

/* ── Cabeçalho ── */
.ks-header {
    display: flex; align-items: center;
    background: #ffffff; border-radius: 12px; padding: 16px 24px;
    margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    border-left: 5px solid #C9A84C; gap: 16px;
}
.ks-title { font-size: 1.5rem; font-weight: 800; color: #2c3e50; margin: 0; }
.ks-sub   { font-size: 0.82rem; color: #64778d; margin: 2px 0 0; }
.ks-sep   { flex: 1; }
.ks-nivel-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;
    background: rgba(201,168,76,.15); color: #8a6a1e;
}
.ks-mod-pill {
    display: inline-block; padding: 3px 10px; border-radius: 10px;
    font-size: 0.72rem; font-weight: 700; margin-right: 3px;
    background: rgba(52,152,219,.1); color: #2980b9;
}

/* ── KPI cards ── */
.kpi-card {
    background: #fff; border-radius: 12px; padding: 18px 14px;
    text-align: center; border-top: 4px solid #C9A84C;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05); height: 100%;
}
.kpi-label { color: #64778d; font-size: 0.75rem; font-weight: 600;
             text-transform: uppercase; letter-spacing: 1px; }
.kpi-value { color: #2c3e50; font-size: 2rem; font-weight: 800; line-height: 1.2; margin-top: 4px; }
.kpi-sub   { color: #C9A84C; font-size: 0.8rem; margin-top: 3px; font-weight: 600; }
.kpi-card.notif  { border-top-color: #27ae60; } .kpi-card.notif .kpi-value  { color: #2ecc71; }
.kpi-card.falhou { border-top-color: #e74c3c; } .kpi-card.falhou .kpi-value { color: #e74c3c; }
.kpi-card.sucesso{ border-top-color: #2980b9; } .kpi-card.sucesso .kpi-value{ color: #3498db; }

/* ── Driver card ── */
.driver-card {
    background: #fff; border: 1px solid #dbe2e9; border-radius: 12px;
    padding: 14px; margin-bottom: 6px; border-top: 4px solid #C9A84C;
}
.tag { display:inline-block; padding:3px 10px; border-radius:12px;
       font-size:0.75rem; font-weight:700; margin:2px; }
.tag-gold  { background:rgba(201,168,76,.15); color:#8a6a1e; }
.tag-green { background:rgba(46,204,113,.12); color:#27ae60; }
.tag-blue  { background:rgba(52,152,219,.12); color:#2980b9; }
.tag-red   { background:rgba(231,76,60,.12);  color:#c0392b; }
</style>
""", unsafe_allow_html=True)

# ── LOGIN ─────────────────────────────────────────────────────────
if "user" not in st.session_state: st.session_state.user = None
if "modulo_ativo" not in st.session_state: st.session_state.modulo_ativo = "rastreio"

if not st.session_state.user:
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col2, _ = st.columns([1,1,1])
    with col2:
        lb = logo_b64()
        if lb: st.markdown(f'<div style="text-align:center;margin-bottom:20px;"><img src="data:image/png;base64,{lb}" style="height:80px;"></div>', unsafe_allow_html=True)
        st.markdown("<h2 style='text-align:center;color:#2c3e50;margin-bottom:24px;'>🔐 Acesso Restrito</h2>", unsafe_allow_html=True)
        usuario = st.text_input("Usuário", placeholder="seu.usuario")
        senha   = st.text_input("Senha", type="password", placeholder="••••••••")
        if st.button("Entrar no Sistema", type="primary", use_container_width=True):
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

# ── SIDEBAR — navegação clara ─────────────────────────────────────
with st.sidebar:
    lb = logo_b64()
    if lb:
        st.markdown(f'<div style="text-align:center;padding:20px 0 16px;"><img src="data:image/png;base64,{lb}" style="height:52px;"></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="text-align:center;padding:20px 0;color:#2c3e50;font-weight:700;font-size:1.1rem;">KingStar</div>', unsafe_allow_html=True)

    st.markdown('<div style="border-top:1px solid #dbe2e9;margin:0 8px 12px;"></div>', unsafe_allow_html=True)
    st.markdown('<span class="nav-section-title">Operacional</span>', unsafe_allow_html=True)

    nav_items = [
        ("rastreio", "Rastreio",  "rastreio" in mods),
        ("tickets",  "Tickets",   "tickets"  in mods),
        ("exportar", "Exportar",  pode_exportar(user)),
    ]

    for key, label, liberado in nav_items:
        if not liberado: continue
        ativo = st.session_state.modulo_ativo == key
        if st.button(label, key=f"nav_{key}", use_container_width=True,
                     type="primary" if ativo else "secondary"):
            st.session_state.modulo_ativo = key
            st.rerun()

    if papel == "adm":
        ativo_cfg = st.session_state.modulo_ativo == "config"
        if st.button("Configuracoes", key="nav_config", use_container_width=True,
                     type="primary" if ativo_cfg else "secondary"):
            st.session_state.modulo_ativo = "config"
            st.rerun()

    st.markdown('<div style="border-top:1px solid #dbe2e9;margin:16px 8px 12px;"></div>', unsafe_allow_html=True)
    st.markdown('<span class="nav-section-title">Em Breve</span>', unsafe_allow_html=True)

    for label in ["Painel Atendente", "ERP Base", "Analytics"]:
        st.markdown(
            f'<div class="nav-soon">{label} <span class="soon-badge">em breve</span></div>',
            unsafe_allow_html=True)

    st.markdown('<div style="border-top:1px solid #dbe2e9;margin:16px 8px 8px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 16px;font-size:0.72rem;color:#9aabb8;">v2.0 · Firebase · Brasília (BRT)</div>', unsafe_allow_html=True)

# ── DADOS ─────────────────────────────────────────────────────────
datas_db   = obter_datas_disponiveis_db()
hoje       = hoje_brt()
ontem      = ontem_brt()
datas_disp = [d["data"] for d in datas_db]

# ── CABEÇALHO ─────────────────────────────────────────────────────
lb        = logo_b64()
mods_html = "".join([
    f'<span class="ks-mod-pill">{"Rastreio" if m=="rastreio" else "Tickets" if m=="tickets" else "Exportar"}</span>'
    for m in mods
])

opcoes_datas = []
if hoje in datas_disp or not datas_disp: opcoes_datas.append(f"Hoje ({hoje})")
if ontem in datas_disp: opcoes_datas.append(f"Ontem ({ontem})")
for item in datas_db:
    if item["data"] not in (hoje, ontem):
        try:    opcoes_datas.append(f"{datetime.strptime(item['data'],'%Y-%m-%d').strftime('%d/%m/%Y')} — {item['total']}")
        except: opcoes_datas.append(item["data"])
if not opcoes_datas: opcoes_datas = [f"Hoje ({hoje})"]

# Linha 1 do cabeçalho: logo + título + usuário + sair
hc1, hc2, hc3, hc4 = st.columns([1, 3.5, 2.5, 0.7])
with hc1:
    if lb:
        st.markdown(f'<div style="padding:4px 0;"><img src="data:image/png;base64,{lb}" style="height:48px;"></div>', unsafe_allow_html=True)
with hc2:
    st.markdown(f"""
    <div style="padding:5px 0;">
        <div style="font-size:1.25rem;font-weight:800;color:#2c3e50;line-height:1.2;">Painel de Entregas · KingStar</div>
        <div style="font-size:0.8rem;color:#64778d;margin-top:2px;">
            KingStar Colchoes &nbsp;·&nbsp; Eco 360° &nbsp;·&nbsp; SimpliRoute &nbsp;·&nbsp;
            <span style="color:#C9A84C;font-weight:700;">Tempo Real</span>
            &nbsp;·&nbsp; <span style="color:#aaa;">{agora_brt()}</span>
        </div>
    </div>""", unsafe_allow_html=True)
with hc3:
    st.markdown('<div style="padding-top:4px;">', unsafe_allow_html=True)
    data_sel = st.selectbox("Periodo", opcoes_datas, label_visibility="collapsed", key="data_sel_header")
    st.markdown('</div>', unsafe_allow_html=True)
with hc4:
    st.markdown(f"""
    <div style="padding:5px 0;text-align:right;">
        <div style="font-size:0.85rem;font-weight:700;color:#2c3e50;">{user['nome']}</div>
        <div style="margin-top:3px;">{mods_html}<span class="ks-nivel-badge">{papel.upper()}</span></div>
    </div>""", unsafe_allow_html=True)
    if st.button("Sair", key="btn_sair"):
        st.session_state.user = None
        st.rerun()

st.markdown('<hr style="margin:4px 0 16px;border:none;border-top:1px solid #e8ecf0;">', unsafe_allow_html=True)

# Resolve data_consulta
if   "Hoje"  in data_sel: data_consulta = hoje
elif "Ontem" in data_sel: data_consulta = ontem
else:
    try:    data_consulta = datetime.strptime(data_sel.split("—")[0].strip(),"%d/%m/%Y").strftime("%Y-%m-%d")
    except: data_consulta = hoje
is_hoje = (data_consulta == hoje)

tickets_raw  = obter_tickets_db(data_consulta)
df_principal = pd.DataFrame(tickets_raw) if tickets_raw else pd.DataFrame()
modulo_ativo = st.session_state.modulo_ativo

# ── ROTEAMENTO DE MÓDULOS ─────────────────────────────────────────
if modulo_ativo == "rastreio" and tem_permissao(user, "rastreio"):
    renderizar_rastreio(df_principal, data_consulta, papel, user)

elif modulo_ativo == "tickets" and tem_permissao(user, "tickets"):
    renderizar_tickets(papel)

elif modulo_ativo == "exportar" and pode_exportar(user):
    from modulo.mod_rastreio import renderizar_exportar
    renderizar_exportar(df_principal, data_consulta, datas_db)

elif modulo_ativo == "config" and papel == "adm":
    st.subheader("⚙️ Configurações e Gestão de Acessos")

    with st.expander("➕ Cadastrar Novo Usuário", expanded=True):
        with st.form("form_novo_user"):
            c1, c2     = st.columns(2)
            novo_nome  = c1.text_input("Nome Completo")
            novo_user  = c2.text_input("Usuário (Login)")
            nova_senha = c1.text_input("Senha", type="password")
            novo_nivel = c2.selectbox("Nível", ["operacional","supervisor","adm"])
            st.markdown("**Módulos liberados:**")
            mc1,mc2,mc3 = st.columns(3)
            mr = mc1.checkbox("🚚 Rastreio", value=True)
            mt = mc2.checkbox("🎫 Tickets",  value=novo_nivel in ("supervisor","adm"))
            me = mc3.checkbox("📥 Exportar", value=novo_nivel in ("supervisor","adm"))
            if st.form_submit_button("Criar Acesso"):
                if novo_nome and novo_user and nova_senha:
                    ms = [m for m,v in [("rastreio",mr),("tickets",mt),("exportar",me)] if v]
                    criar_usuario(novo_nome, novo_user, nova_senha, novo_nivel, ms)
                    st.success(f"Usuário **{novo_user}** criado!")
                    time.sleep(1); st.rerun()
                else: st.warning("Preencha todos os campos.")

    st.markdown("---")
    st.markdown("### 👤 Usuários Ativos")
    for i_u, u in enumerate(listar_usuarios()):
        uname  = u.get("usuario", f"u{i_u}")
        univel = str(u.get("role","—")).upper()
        umods  = u.get("modulos", MODULOS_PADRAO.get(u.get("role","operacional"),[]))
        with st.expander(f"**{u.get('nome','—')}**  ·  `{uname}`  ·  {univel}"):
            col_m, col_d = st.columns([2,1])
            with col_m:
                mc1,mc2,mc3 = st.columns(3)
                nr = mc1.checkbox("🚚 Rastreio", value="rastreio" in umods, key=f"r_{uname}")
                nt = mc2.checkbox("🎫 Tickets",  value="tickets"  in umods, key=f"t_{uname}")
                ne = mc3.checkbox("📥 Exportar", value="exportar" in umods, key=f"e_{uname}")
                if st.button("💾 Salvar", key=f"sm_{uname}"):
                    ns = [m for m,v in [("rastreio",nr),("tickets",nt),("exportar",ne)] if v]
                    atualizar_modulos_usuario(uname, ns)
                    st.success("Salvo!"); time.sleep(.5); st.rerun()
            with col_d:
                if uname != "admin":
                    if st.button("🗑️ Excluir usuário", key=f"del_{uname}_{i_u}"):
                        deletar_usuario(uname); st.rerun()
else:
    st.warning("🔒 Você não tem permissão para acessar este módulo.")

# ── AUTO-REFRESH sem contador ─────────────────────────────────────
# Usa st.fragment + rerun condicional para não bloquear a UI
if is_hoje and modulo_ativo == "rastreio":
    time.sleep(20)
    st.rerun()
