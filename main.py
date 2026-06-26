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
/* Remove padding padrão */
.block-container { padding-top: 1rem !important; }

/* Sidebar minimalista — só navegação */
section[data-testid="stSidebar"] {
    background: #1a242f !important;
    min-width: 220px !important; max-width: 220px !important;
}
section[data-testid="stSidebar"] * { color: #a0b0c0 !important; }

/* Cabeçalho */
.ks-header {
    display: flex; align-items: center; justify-content: space-between;
    background: #ffffff; border-radius: 12px; padding: 14px 24px;
    margin-bottom: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    border-left: 5px solid #C9A84C;
}
.ks-header-left  { display: flex; align-items: center; gap: 16px; }
.ks-header-right { display: flex; align-items: center; gap: 12px; }
.ks-user-pill {
    display: flex; align-items: center; gap: 8px;
    background: #f4f6f9; border-radius: 20px; padding: 6px 14px;
    font-size: 0.85rem; font-weight: 600; color: #2c3e50;
}
.ks-nivel-badge {
    padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;
    background: rgba(201,168,76,.2); color: #b0913b;
}
.ks-mod-badge {
    padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;
    background: rgba(52,152,219,.12); color: #2980b9; margin-right: 4px;
}

/* KPI cards */
.kpi-card {
    background: #fff; border-radius: 12px; padding: 18px 14px;
    text-align: center; border-top: 4px solid #C9A84C;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05); height: 100%;
}
.kpi-label { color: #64778d; font-size: 0.78rem; font-weight: 600;
             text-transform: uppercase; letter-spacing: 1px; }
.kpi-value { color: #2c3e50; font-size: 2rem; font-weight: 800; line-height: 1.2; margin-top: 4px; }
.kpi-sub   { color: #C9A84C; font-size: 0.82rem; margin-top: 3px; font-weight: 600; }
.kpi-card.notif  { border-top-color: #27ae60; } .kpi-card.notif .kpi-value  { color: #2ecc71; }
.kpi-card.falhou { border-top-color: #e74c3c; } .kpi-card.falhou .kpi-value { color: #e74c3c; }
.kpi-card.sucesso{ border-top-color: #2980b9; } .kpi-card.sucesso .kpi-value{ color: #3498db; }

/* Driver card */
.driver-card {
    background: #fff; border: 1px solid #dbe2e9; border-radius: 12px;
    padding: 14px; margin-bottom: 6px; border-top: 4px solid #C9A84C;
}
.tag { display:inline-block; padding:3px 10px; border-radius:12px;
       font-size:0.75rem; font-weight:700; margin:2px; }
.tag-gold  { background:rgba(201,168,76,.15); color:#b0913b; }
.tag-green { background:rgba(46,204,113,.12); color:#27ae60; }
.tag-blue  { background:rgba(52,152,219,.12); color:#2980b9; }
.tag-red   { background:rgba(231,76,60,.12);  color:#c0392b; }

/* Sidebar nav links */
.nav-modulo {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 16px; border-radius: 8px; margin: 2px 8px;
    font-size: 0.88rem; font-weight: 500; cursor: pointer;
    transition: background .15s;
}
.nav-modulo:hover { background: rgba(255,255,255,.08); }
.nav-modulo.active { background: rgba(201,168,76,.2); color: #C9A84C !important; font-weight: 700; }
.nav-section-title {
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.5px; color: #4a6278 !important;
    padding: 16px 16px 6px; margin: 0;
}
.soon-badge {
    font-size: 0.6rem; background: rgba(255,255,255,.1);
    padding: 2px 6px; border-radius: 8px; margin-left: auto;
}
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

# ── SIDEBAR — só navegação ────────────────────────────────────────
with st.sidebar:
    lb = logo_b64()
    if lb:
        st.markdown(f'<div style="text-align:center;padding:20px 0 12px;"><img src="data:image/png;base64,{lb}" style="height:50px;filter:brightness(1.1);"></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="text-align:center;padding:20px 0;font-size:1.5rem;">🚚</div>', unsafe_allow_html=True)

    st.markdown('<div style="border-top:1px solid #2d3d4f;margin:0 16px 8px;"></div>', unsafe_allow_html=True)
    st.markdown('<p class="nav-section-title">Operacional</p>', unsafe_allow_html=True)

    nav_items = [
        ("rastreio",  "🚚", "Rastreio",       "rastreio"  in mods, False),
        ("tickets",   "🎫", "Tickets",         "tickets"   in mods, False),
        ("exportar",  "📥", "Exportar",        pode_exportar(user),  False),
    ]
    nav_em_breve = [
        ("atendente", "💬", "Painel Atendente", False, True),
        ("erp",       "🗂️",  "ERP Base",         False, True),
        ("analytics", "📊", "Analytics",        False, True),
    ]

    for key, icon, label, liberado, soon in nav_items:
        if not liberado: continue
        ativo = "active" if st.session_state.modulo_ativo == key else ""
        if st.button(f"{icon}  {label}", key=f"nav_{key}", use_container_width=True,
                     type="primary" if ativo else "secondary"):
            st.session_state.modulo_ativo = key
            st.rerun()

    if papel == "adm":
        if st.button("⚙️  Configurações", key="nav_config", use_container_width=True,
                     type="primary" if st.session_state.modulo_ativo=="config" else "secondary"):
            st.session_state.modulo_ativo = "config"
            st.rerun()

    st.markdown('<p class="nav-section-title" style="margin-top:16px;">Em Breve</p>', unsafe_allow_html=True)
    for key, icon, label, _, _ in nav_em_breve:
        st.markdown(f'<div class="nav-modulo" style="opacity:.45;">{icon} {label} <span class="soon-badge" style="color:#4a6278 !important;">soon</span></div>', unsafe_allow_html=True)

    st.markdown('<div style="border-top:1px solid #2d3d4f;margin:16px 16px 8px;"></div>', unsafe_allow_html=True)
    st.markdown('<p class="nav-section-title">Sistema</p>', unsafe_allow_html=True)
    st.markdown(f'<div style="padding:8px 16px;font-size:0.78rem;color:#4a6278 !important;">v2.0 · Firebase · BRT</div>', unsafe_allow_html=True)

# ── DADOS ─────────────────────────────────────────────────────────
datas_db   = obter_datas_disponiveis_db()
hoje       = hoje_brt()
ontem      = ontem_brt()
datas_disp = [d["data"] for d in datas_db]

# ── CABEÇALHO com usuário, data e sair ───────────────────────────
lb = logo_b64()
html_logo = f'<img src="data:image/png;base64,{lb}" style="height:44px;">' if lb else "🚚"

mods_html = "".join([
    f'<span class="ks-mod-badge">{"🚚" if m=="rastreio" else "🎫" if m=="tickets" else "📥"} {m.capitalize()}</span>'
    for m in mods
])

# Selectbox de data no cabeçalho
opcoes_datas = []
if hoje in datas_disp or not datas_disp: opcoes_datas.append(f"Hoje ({hoje})")
if ontem in datas_disp: opcoes_datas.append(f"Ontem ({ontem})")
for item in datas_db:
    if item["data"] not in (hoje, ontem):
        try:    opcoes_datas.append(f"{datetime.strptime(item['data'],'%Y-%m-%d').strftime('%d/%m/%Y')} — {item['total']}")
        except: opcoes_datas.append(item["data"])
if not opcoes_datas: opcoes_datas = [f"Hoje ({hoje})"]

hc1, hc2, hc3, hc4, hc5 = st.columns([1.2, 3, 2, 1.5, 0.8])
with hc1:
    if lb: st.markdown(f'<div style="padding:6px 0;">{html_logo}</div>', unsafe_allow_html=True)
with hc2:
    st.markdown(f"""
    <div style="padding:6px 0;">
        <div style="font-size:1.1rem;font-weight:800;color:#2c3e50;">Painel Integrado · KingStar</div>
        <div style="font-size:0.8rem;color:#64778d;">Eco 360º · SimpliRoute · <span style="color:#C9A84C;font-weight:700;">🕐 {agora_brt()}</span></div>
    </div>""", unsafe_allow_html=True)
with hc3:
    data_sel = st.selectbox("", opcoes_datas, label_visibility="collapsed", key="data_sel_header")
with hc4:
    st.markdown(f"""
    <div style="padding:6px 0;text-align:right;">
        <div style="font-size:0.82rem;font-weight:700;color:#2c3e50;">👤 {user['nome']}</div>
        <div>{mods_html}<span class="ks-nivel-badge">{papel.upper()}</span></div>
    </div>""", unsafe_allow_html=True)
with hc5:
    if st.button("Sair", key="btn_sair"):
        st.session_state.user = None
        st.rerun()

st.markdown('<hr style="margin:0 0 16px;border:none;border-top:1px solid #e8ecf0;">', unsafe_allow_html=True)

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
