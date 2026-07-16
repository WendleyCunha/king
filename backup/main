import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import os, time, base64

from database import (
    verificar_login, criar_usuario, listar_usuarios, deletar_usuario,
    atualizar_modulos_usuario, alterar_senha_usuario,
    obter_tickets_db, obter_datas_disponiveis_db,
    modulos_do_usuario, tem_permissao, pode_exportar, pode_deletar,
    MODULOS_PADRAO,
    # ── novas funções ──
    listar_departamentos, criar_departamento, deletar_departamento,
    atualizar_departamento_usuario, redefinir_senha_usuario,
)
from modulo.mod_rastreio import renderizar_rastreio

try:
    from modulo.mod_home import renderizar_home
except Exception as _erro_import_home:
    def renderizar_home(papel, user=None, _erro=_erro_import_home):
        st.error("⚠️ Falha ao carregar o módulo Meu Dia. Detalhe técnico abaixo:")
        st.exception(_erro)

try:
    from modulo.mod_tickets import renderizar_tickets
except ImportError:
    def renderizar_tickets(papel, user=None): st.info("🚧 Módulo de Tickets em desenvolvimento...")

try:
    from modulo.mod_cartas import renderizar_cartas
except Exception as _erro_import_cartas:
    def renderizar_cartas(papel, user=None, _erro=_erro_import_cartas):
        st.error("⚠️ Falha ao carregar o módulo de Cartas. Detalhe técnico abaixo:")
        st.exception(_erro)

try:
    from modulo.mod_chat import renderizar_chat
except Exception as _erro_import_chat:
    def renderizar_chat(papel, user=None, _erro=_erro_import_chat):
        st.error("⚠️ Falha ao carregar o módulo de Chat. Detalhe técnico abaixo:")
        st.exception(_erro)

try:
    from database_chat import listar_conversas_com_nao_lidas
except Exception:
    def listar_conversas_com_nao_lidas(_lista):
        return []

st.set_page_config(
    page_title="KingStar · Painel Integrado",
    layout="wide", page_icon="🚚",
    initial_sidebar_state="expanded"
)

BRT = timezone(timedelta(hours=-3))
def agora_brt(): return datetime.now(BRT).strftime("%H:%M:%S")

def get_logo():
    if os.path.exists("logo.png"):
        with open("logo.png","rb") as f: return base64.b64encode(f.read()).decode()
    return None

def _total_chat_pendentes():
    """
    Soma as mensagens não lidas de motoristas em todas as conversas (visão ADM).
    OTIMIZADO: listar_conversas_com_nao_lidas agora lê 1 doc-resumo pequeno
    por motorista (não mais até 1000 mensagens por motorista) — ver
    database_chat.py. Ainda assim, cacheia por alguns segundos porque essa
    função roda no sidebar, ou seja, em TODO rerun de QUALQUER página.
    """
    try:
        motoristas_ids = tuple(
            u["usuario"] for u in listar_usuarios() if u.get("role") == "motorista"
        )
        return _total_chat_pendentes_cache(motoristas_ids)
    except Exception:
        return 0

@st.cache_data(ttl=5, show_spinner=False)
def _total_chat_pendentes_cache(motoristas_ids: tuple) -> int:
    return sum(c["nao_lidas"] for c in listar_conversas_com_nao_lidas(list(motoristas_ids)))

# ── CSS ───────────────────────────────────────────────────────────
st.markdown("""
<style>
.stApp { background-color: #f4f6f9; }
.block-container { padding-top: 4rem !important; }

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
.ks-header {
    background:#ffffff; border-left:5px solid #C9A84C;
    border-radius:12px; padding:16px 24px; margin-bottom:20px;
    box-shadow:0 2px 8px rgba(0,0,0,0.05);
    display:flex; align-items:center; gap:18px;
}
/* Cabeçalho FIXO ao rolar a página */
div[data-testid="stHorizontalBlock"]:has(.ks-header) {
    position: sticky; top: 0; z-index: 999;
    background: #f4f6f9; padding-top: 6px; padding-bottom: 6px;
}
.ks-title { font-size:1.4rem; font-weight:800; color:#2c3e50; margin:0; }
.ks-sub { font-size:0.8rem; color:#64778d; margin-top:3px; }
.ks-pill { display:inline-block; padding:3px 10px; border-radius:10px;
    font-size:0.72rem; font-weight:700; margin-right:3px;
    background:rgba(52,152,219,.1); color:#2471a3; }
.ks-nivel { display:inline-block; padding:3px 10px; border-radius:10px;
    font-size:0.72rem; font-weight:700;
    background:rgba(201,168,76,.15); color:#7a5f1a; }
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
.driver-card { background:#fff; border:1px solid #e2e8f0; border-radius:12px;
    padding:14px; margin-bottom:6px; border-top:4px solid #C9A84C; }
.tag { display:inline-block; padding:3px 9px; border-radius:10px;
    font-size:0.73rem; font-weight:700; margin:2px; }
.tg { background:rgba(201,168,76,.12); color:#7a5f1a; }
.tn { background:rgba(46,204,113,.1);  color:#1e8449; }
.tb { background:rgba(52,152,219,.1);  color:#2471a3; }
.tr { background:rgba(231,76,60,.1);   color:#a93226; }

/* ═══════════════════════════════════════════════════════════════
   RESPONSIVO — CELULAR (telas até 768px)
   Empilha as colunas do Streamlit (KPIs, filtros, cabeçalho, chat)
   em vez de espremer tudo lado a lado, e ajusta tamanhos de fonte
   e espaçamento pra caber bem na tela pequena.
   ═══════════════════════════════════════════════════════════════ */
@media (max-width: 768px) {
    .block-container {
        padding-top: 3rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
    }

    /* Empilha qualquer linha de colunas (KPIs, filtros do Rastreio,
       cabeçalho, colunas do Chat) em vez de espremer horizontalmente */
    div[data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        width: 100% !important;
        min-width: 100% !important;
        flex: 1 1 100% !important;
        margin-bottom: 6px;
    }

    /* Cabeçalho: título compacto */
    .ks-header {
        padding: 12px 14px !important;
        gap: 10px !important;
    }
    .ks-title { font-size: 1.1rem !important; }
    .ks-sub   { font-size: 0.72rem !important; }

    /* KPIs: menores pra caber 1 por linha sem ficar gigante */
    .kpi-card { padding: 12px 10px !important; }
    .kpi-value { font-size: 1.5rem !important; }
    .kpi-label { font-size: 0.68rem !important; }

    /* Botões e inputs com alvo de toque melhor no dedo */
    .stButton > button, .stTextInput input, .stSelectbox, .stDateInput input {
        min-height: 42px !important;
        font-size: 0.95rem !important;
    }

    /* Tabelas: permite rolar horizontalmente em vez de cortar colunas */
    div[data-testid="stDataFrame"] {
        overflow-x: auto !important;
    }

    /* Popup/dialog do motorista ocupa a tela quase inteira no celular */
    div[role="dialog"] {
        width: 95vw !important;
        max-width: 95vw !important;
    }
}
</style>
""", unsafe_allow_html=True)

# ── INIT SESSION STATE ─────────────────────────────────────────────
if "user"         not in st.session_state: st.session_state.user = None
if "modulo_ativo" not in st.session_state: st.session_state.modulo_ativo = "home"

# ── LOGIN — PARE AQUI SE NÃO LOGADO ──────────────────────────────
if st.session_state.user is None:
    # Esconde sidebar durante login
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display: none !important; }
    </style>""", unsafe_allow_html=True)
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col, _ = st.columns([1,1,1])
    with col:
        lb = get_logo()
        if lb:
            st.markdown(
                f'<div style="text-align:center;margin-bottom:20px;">'
                f'<img src="data:image/png;base64,{lb}" style="height:80px;"></div>',
                unsafe_allow_html=True)
        st.markdown(
            "<h2 style='text-align:center;color:#2c3e50;margin-bottom:20px;'>🔐 Acesso Restrito</h2>",
            unsafe_allow_html=True)
        usuario = st.text_input("Usuário")
        senha   = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary", use_container_width=True):
            u = verificar_login(usuario, senha)
            if u:
                st.session_state.user = u
                # Regra: após o login, a primeira página é a Home (Meu Dia) —
                # exceto para motoristas, que não têm acesso a esse módulo e
                # vão direto para o Rastreio (suas próprias entregas).
                st.session_state.modulo_ativo = "rastreio" if u.get("role") == "motorista" else "home"
                st.rerun()
            else:
                st.error("Credenciais inválidas.")
    st.stop()

# ── USUÁRIO CONFIRMADO ────────────────────────────────────────────
user  = st.session_state.user
papel = user.get("role", "operacional")
mods  = modulos_do_usuario(user)

# ══════════════════════════════════════════════════════════════════
# VISÃO EXCLUSIVA DO MOTORISTA — sem sidebar, Rastreio e Chat em abas
# ══════════════════════════════════════════════════════════════════
if papel == "motorista":
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display: none !important; }
    .block-container { padding-top: 1.2rem !important; }
    </style>
    """, unsafe_allow_html=True)

    lb = get_logo()
    if lb:
        st.markdown(
            f'<div style="text-align:center;padding:6px 0 10px;">'
            f'<img src="data:image/png;base64,{lb}" style="height:44px;"></div>',
            unsafe_allow_html=True)

    aba_entregas, aba_chat = st.tabs(["🚚 Minhas Entregas", "💬 Chat"])
    with aba_entregas:
        renderizar_rastreio(papel, user, datas_db=[], pode_exp=False)
        if st.button("🔄 Atualizar entregas", key="btn_refresh_rastreio_motorista", use_container_width=True):
            st.rerun()

        # Nome do motorista + Sair ficam só aqui, no final da aba de entregas
        st.markdown("<hr style='margin:20px 0 14px;border:none;border-top:1px solid #eee;'>",
                    unsafe_allow_html=True)
        st.markdown(
            f"<div style='text-align:center;color:#64778d;font-size:0.85rem;margin-bottom:8px;'>"
            f"{user['nome']}</div>", unsafe_allow_html=True)
        if st.button("Sair", key="btn_sair_motorista", use_container_width=True):
            st.session_state.user = None
            st.rerun()

    with aba_chat:
        try:
            renderizar_chat(papel, user)
        except Exception as _erro_chat_runtime:
            st.error("⚠️ O Chat encontrou um problema e não pôde carregar agora.")
            st.code(f"{type(_erro_chat_runtime).__name__}: {_erro_chat_runtime}", language="text")

    st.stop()

# ── SIDEBAR ───────────────────────────────────────────────────────
with st.sidebar:
    lb = get_logo()
    if lb:
        st.markdown(
            f'<div style="text-align:center;padding:18px 0 14px;">'
            f'<img src="data:image/png;base64,{lb}" style="height:50px;"></div>',
            unsafe_allow_html=True)
    st.markdown('<div style="border-top:1px solid #e2e8f0;margin:0 8px 10px;"></div>',
                unsafe_allow_html=True)
    st.markdown('<span class="nav-section">Operacional</span>', unsafe_allow_html=True)

    if papel != "motorista":
        ativo_home = st.session_state.modulo_ativo == "home"
        if st.button("🏠 Meu Dia", key="nav_home", use_container_width=True,
                     type="primary" if ativo_home else "secondary"):
            st.session_state.modulo_ativo = "home"
            st.rerun()

    for key, label in [("rastreio","Rastreio"), ("tickets","Tickets"), ("cartas","Cartas")]:
        if key not in mods: continue
        lbl = label
        # Chat agora vive dentro do Rastreio (aba ao lado de Cadastros) —
        # o badge de mensagens pendentes aparece aqui, no botão Rastreio.
        # (cacheado por 5s em _total_chat_pendentes — ver database_chat.py
        # para o motivo da otimização; sem isso, essa chamada rodava
        # pesada a cada rerun de QUALQUER tela, não só do Chat.)
        if key == "rastreio" and papel in ("adm", "supervisor"):
            _pend_nav = _total_chat_pendentes()
            if _pend_nav:
                lbl = f"{label} 💬 🔴 {_pend_nav}"
        ativo = st.session_state.modulo_ativo == key
        if st.button(lbl, key=f"nav_{key}", use_container_width=True,
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
    for lbl in ["Painel Atendente", "ERP Base", "Analytics"]:
        st.markdown(
            f'<div class="nav-soon">{lbl}<span class="soon-tag">em breve</span></div>',
            unsafe_allow_html=True)
    st.markdown('<div style="border-top:1px solid #e2e8f0;margin:14px 8px 8px;"></div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.7rem;color:#b0bec5;padding:0 4px 16px;">'
        'v2.0 · Firebase · Brasília (BRT)</div>',
        unsafe_allow_html=True)

# ── CABEÇALHO ─────────────────────────────────────────────────────
lb        = get_logo()
logo_html = (f'<img src="data:image/png;base64,{lb}" style="height:50px;margin-right:18px;">'
             if lb else "")
_NOMES_MODULOS = {"rastreio": "Rastreio", "tickets": "Tickets", "cartas": "Cartas"}
pills = "".join(
    f'<span class="ks-pill">{_NOMES_MODULOS[m]}</span>'
    for m in mods if m in _NOMES_MODULOS
)

hc1, hc2 = st.columns([9, 1])
with hc1:
    st.markdown(f"""
    <div class="ks-header">
        {logo_html}
        <div style="flex:1;">
            <div class="ks-title">Painel KingStar</div>
            <div class="ks-sub">
                KingStar Colchoes &nbsp;·&nbsp; by Wendley &nbsp;·&nbsp;
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

# ── DADOS ─────────────────────────────────────────────────────────
modulo_ativo = st.session_state.modulo_ativo

# OTIMIZAÇÃO: obter_datas_disponiveis_db() varre a coleção 'entregas'
# inteira (todo o histórico de entregas já feitas) só para montar a
# lista de datas do seletor do Rastreio. Antes rodava incondicionalmente
# em TODA renderização (Tickets, Cartas, Configurações...), mesmo quando
# a tela em questão nunca usa esse dado. Agora só busca quando o módulo
# Rastreio está de fato aberto (também é cacheada por 60s em database.py).
datas_db = obter_datas_disponiveis_db() if modulo_ativo == "rastreio" else []

# Motorista não tem acesso ao módulo Home — se a sessão dele ainda
# apontar pra lá (ex: login antigo, antes dessa regra existir), redireciona.
if papel == "motorista" and modulo_ativo == "home":
    st.session_state.modulo_ativo = "rastreio"
    modulo_ativo = "rastreio"
    st.rerun()

# Chat deixou de ser um módulo próprio — agora é uma aba dentro do
# Rastreio (ao lado de Cadastros). Sessões antigas que ainda apontem
# pra "chat" são redirecionadas pra lá.
if modulo_ativo == "chat":
    st.session_state.modulo_ativo = "rastreio"
    modulo_ativo = "rastreio"
    st.rerun()

# ── NOTIFICAÇÃO DE CHAT NO PAINEL GERAL (visível em qualquer tela, exceto dentro do Rastreio) ──
if papel in ("adm", "supervisor") and modulo_ativo != "rastreio":
    _pend_geral = _total_chat_pendentes()
    if _pend_geral:
        st.info(f"💬 Você tem **{_pend_geral}** mensagem(ns) de motoristas aguardando resposta. "
                f"Acesse **Rastreio → aba Chat** para responder.")

# Se o módulo Rastreio precisar dessas datas mas o usuário navegou para
# outra aba antes deste ponto, garante que datas_db já esteja resolvido
# (evita usar variável desatualizada quando modulo_ativo mudou acima).
if modulo_ativo == "rastreio" and not datas_db:
    datas_db = obter_datas_disponiveis_db()

# ── ROTEAMENTO ────────────────────────────────────────────────────
if modulo_ativo == "home":
    renderizar_home(papel, user)

elif modulo_ativo == "rastreio" and tem_permissao(user, "rastreio"):
    is_hoje = renderizar_rastreio(
        papel, user, datas_db=datas_db, pode_exp=pode_exportar(user)
    )
    # Atualização manual em vez de streamlit-autorefresh: esse componente
    # tem um bug conhecido de deixar o timer JS "vivo" no navegador mesmo
    # depois de trocar de aba, o que pode travar OUTRAS telas do sistema
    # (Cartas, Tickets etc.) sem relação nenhuma com o Rastreio. Um botão
    # manual é 100% seguro e não tem esse risco.
    if is_hoje:
        if st.button("🔄 Atualizar rastreio", key="btn_refresh_rastreio"):
            st.rerun()

elif modulo_ativo == "tickets" and tem_permissao(user, "tickets"):
    renderizar_tickets(papel, user)

elif modulo_ativo == "cartas" and tem_permissao(user, "cartas"):
    renderizar_cartas(papel, user)

elif modulo_ativo == "config" and papel == "adm":
    st.subheader("⚙️ Configurações")

    # ── Helpers de gerenciamento (sub-abas por departamento) ──────────
    def _gerenciar_usuario(u, dep_nomes, ctx, idx):
        uname = u.get("usuario", f"u{idx}")
        dep   = u.get("departamento", "—") or "—"
        role  = u.get("role", "—")
        with st.expander(f"**{u.get('nome','—')}** · `{uname}` · {role.upper()} · 🏢 {dep}"):

            # Departamento
            if dep_nomes:
                ix = (dep_nomes.index(dep) + 1) if dep in dep_nomes else 0
                novo_dep = st.selectbox("Departamento", ["— Selecione —"] + dep_nomes,
                                        index=ix, key=f"dep_{ctx}_{uname}_{idx}")
                if st.button("💾 Atualizar departamento", key=f"svdep_{ctx}_{uname}_{idx}"):
                    if novo_dep != "— Selecione —":
                        atualizar_departamento_usuario(uname, novo_dep)
                        st.success("Departamento atualizado!"); time.sleep(.5); st.rerun()

            # Alterar senha (reset pelo admin)
            if uname != "admin":
                st.markdown("**🔑 Redefinir senha**")
                ns  = st.text_input("Nova senha", type="password", key=f"ns_{ctx}_{uname}_{idx}")
                ns2 = st.text_input("Confirmar nova senha", type="password", key=f"ns2_{ctx}_{uname}_{idx}")
                if st.button("Salvar nova senha", key=f"svsenha_{ctx}_{uname}_{idx}"):
                    if not ns or len(ns) < 6:
                        st.error("A senha deve ter pelo menos 6 caracteres.")
                    elif ns != ns2:
                        st.error("As senhas não coincidem.")
                    else:
                        ok, msg = redefinir_senha_usuario(uname, ns)
                        (st.success if ok else st.error)(msg)
                        if ok: time.sleep(.6); st.rerun()

            # Excluir
            if uname != "admin":
                st.markdown("---")
                if st.button("🗑️ Excluir usuário", key=f"del_{ctx}_{uname}_{idx}"):
                    deletar_usuario(uname); st.rerun()

    def _perm_card(u, ctx, idx):
        uname = u.get("usuario", f"u{idx}")
        umods = u.get("modulos", MODULOS_PADRAO.get(u.get("role","operacional"), []))
        with st.expander(f"**{u.get('nome','—')}** · `{uname}`"):
            ma, mb, mc = st.columns(3)
            nr = ma.checkbox("Rastreio", value="rastreio" in umods, key=f"r_{ctx}_{uname}_{idx}")
            nt = mb.checkbox("Tickets",  value="tickets"  in umods, key=f"t_{ctx}_{uname}_{idx}")
            nca = mc.checkbox("Cartas",  value="cartas"   in umods, key=f"c_{ctx}_{uname}_{idx}")
            if st.button("💾 Salvar", key=f"svperm_{ctx}_{uname}_{idx}", type="primary"):
                ns = [m for m,v in [("rastreio",nr),("tickets",nt),("cartas",nca),("exportar",nr)] if v]
                atualizar_modulos_usuario(uname, ns)
                st.success("Salvo!"); time.sleep(.5); st.rerun()

    aba_u, aba_m, aba_dep, aba_mot = st.tabs(
        ["👥 Usuários", "🔒 Permissões", "🏢 Departamentos", "🗂️ Motivos"]
    )

    # ─── ABA USUÁRIOS (sub-abas por departamento) ─────────────────
    with aba_u:
        deps      = listar_departamentos()
        dep_nomes = [d["nome"] for d in deps]

        with st.expander("➕ Cadastrar Novo Usuário", expanded=False):
            if not dep_nomes:
                st.info("⚠️ Cadastre um departamento na aba **Departamentos** antes de criar usuários.")
            with st.form("form_novo"):
                c1, c2  = st.columns(2)
                n_nome  = c1.text_input("Nome Completo")
                n_user  = c2.text_input("Login")
                n_senha = c1.text_input("Senha", type="password")
                n_nivel = c2.selectbox("Nível", ["operacional","supervisor","adm"])
                n_dep   = st.selectbox("Departamento",
                                       options=(["— Selecione —"] + dep_nomes),
                                       help="Tickets do departamento caem automaticamente para este usuário.")
                ma, mb, mc = st.columns(3)
                m_r     = ma.checkbox("Rastreio", value=True)
                m_t     = mb.checkbox("Tickets", value=n_nivel in ("supervisor","adm"))
                m_c     = mc.checkbox("Cartas", value=n_nivel in ("supervisor","adm"))
                if st.form_submit_button("Criar"):
                    if not (n_nome and n_user and n_senha):
                        st.warning("Preencha todos os campos.")
                    elif n_dep == "— Selecione —":
                        st.warning("Selecione um departamento.")
                    else:
                        ms = [m for m,v in [("rastreio",m_r),("tickets",m_t),("cartas",m_c),("exportar",m_r)] if v]
                        criar_usuario(n_nome, n_user, n_senha, n_nivel, ms, departamento=n_dep)
                        st.success(f"Usuário **{n_user}** criado no depto **{n_dep}**!")
                        time.sleep(1); st.rerun()

        st.markdown("---")
        st.markdown("### Usuários por Departamento")
        if not dep_nomes:
            st.info("Crie um departamento para organizar os usuários.")
        else:
            usuarios = listar_usuarios()
            sub = st.tabs([f"🏢 {d}" for d in dep_nomes] + ["📦 Outros"])
            for i, dn in enumerate(dep_nomes):
                with sub[i]:
                    ldep = [u for u in usuarios if u.get("departamento") == dn]
                    if not ldep:
                        st.caption("Nenhum usuário neste departamento.")
                    for j, u in enumerate(ldep):
                        _gerenciar_usuario(u, dep_nomes, f"u{i}", j)
            with sub[-1]:
                outros = [u for u in usuarios if (u.get("departamento") or "") not in dep_nomes]
                if not outros:
                    st.caption("Nenhum usuário sem departamento.")
                for j, u in enumerate(outros):
                    _gerenciar_usuario(u, dep_nomes, "uout", j)

    # ─── ABA PERMISSÕES (sub-abas por departamento) ───────────────
    with aba_m:
        deps      = listar_departamentos()
        dep_nomes = [d["nome"] for d in deps]
        st.markdown("### Permissões por Departamento")
        if not dep_nomes:
            st.info("Crie um departamento para organizar as permissões.")
        else:
            usuarios = listar_usuarios()
            sub = st.tabs([f"🏢 {d}" for d in dep_nomes] + ["📦 Outros"])
            for i, dn in enumerate(dep_nomes):
                with sub[i]:
                    ldep = [u for u in usuarios if u.get("departamento") == dn]
                    if not ldep:
                        st.caption("Nenhum usuário neste departamento.")
                    for j, u in enumerate(ldep):
                        _perm_card(u, f"p{i}", j)
            with sub[-1]:
                outros = [u for u in usuarios if (u.get("departamento") or "") not in dep_nomes]
                if not outros:
                    st.caption("Nenhum usuário sem departamento.")
                for j, u in enumerate(outros):
                    _perm_card(u, "pout", j)

    # ─── ABA DEPARTAMENTOS (sem divisão) ──────────────────────────
    with aba_dep:
        st.markdown("### 🏢 Departamentos")
        with st.expander("➕ Novo Departamento", expanded=True):
            with st.form("form_dep"):
                d_nome = st.text_input("Nome do Departamento",
                                       placeholder="Ex: Pós-venda, Logística, Financeiro...")
                d_desc = st.text_area("Descrição (opcional)", height=80)
                if st.form_submit_button("Criar Departamento"):
                    ok, msg = criar_departamento(d_nome, d_desc)
                    (st.success if ok else st.error)(msg)
                    if ok: time.sleep(.8); st.rerun()

        st.markdown("---")
        deps = listar_departamentos()
        if not deps:
            st.info("Nenhum departamento cadastrado ainda.")
        for dep in deps:
            users_dep = [u for u in listar_usuarios() if u.get("departamento") == dep["nome"]]
            with st.expander(f"🏢 **{dep['nome']}** · 👤 {len(users_dep)} usuário(s)"):
                if dep.get("descricao"):
                    st.caption(dep["descricao"])
                if users_dep:
                    st.markdown("**Usuários:** " + ", ".join(f"`{u['usuario']}`" for u in users_dep))
                if st.button(f"🗑️ Excluir '{dep['nome']}'", key=f"deldep_{dep['id']}"):
                    ok, msg = deletar_departamento(dep["id"])
                    (st.success if ok else st.error)(msg)
                    if ok: time.sleep(.5); st.rerun()

    # ─── ABA MOTIVOS (Motivo Pai → Motivo Filho → Etapa) ──────────
    # Substitui a lógica antiga de Tabulação para o módulo de Tickets:
    # Motivo Pai carrega o SLA de triagem (SLA1); Motivo Filho e Etapa são
    # escolhidos pelo atendente durante o atendimento (ver mod_tickets.py).
    # Etapas vermelhas exigem data futura (SLA2) e travam a trilha do ticket.
    with aba_mot:
        try:
            from modulo.mod_motivos import renderizar_motivos
            renderizar_motivos(papel, listar_usuarios())
        except Exception as _erro_import_motivos:
            st.error("⚠️ Falha ao carregar o cadastro de Motivos. Detalhe técnico abaixo:")
            st.exception(_erro_import_motivos)


else:
    # ── MINHA CONTA — qualquer usuário logado pode trocar a senha ──
    st.subheader("👤 Minha Conta")
    dep_user = user.get("departamento", "—") or "—"
    st.markdown(f"**Nome:** {user['nome']}  |  **Login:** `{user.get('usuario','')}`  |  "
                f"**Nível:** {papel.upper()}  |  **Departamento:** {dep_user}")
    st.markdown("---")
    st.markdown("### 🔑 Alterar Senha")
    with st.form("form_senha"):
        s_atual  = st.text_input("Senha atual", type="password")
        s_nova   = st.text_input("Nova senha", type="password")
        s_conf   = st.text_input("Confirmar nova senha", type="password")
        if st.form_submit_button("Alterar Senha", type="primary"):
            if not s_atual or not s_nova or not s_conf:
                st.warning("Preencha todos os campos.")
            elif s_nova != s_conf:
                st.error("As senhas não coincidem.")
            elif len(s_nova) < 6:
                st.error("A nova senha deve ter pelo menos 6 caracteres.")
            else:
                ok, msg = alterar_senha_usuario(user.get("usuario",""), s_atual, s_nova)
                if ok:
                    st.success(msg)
                    time.sleep(1)
                    st.session_state.user = None
                    st.rerun()
                else:
                    st.error(msg)

# ── BOTÃO MINHA CONTA na sidebar ──────────────────────────────────
with st.sidebar:
    st.markdown('<div style="border-top:1px solid #e2e8f0;margin:8px 8px 10px;"></div>',
                unsafe_allow_html=True)
    if st.button("👤 Minha Conta", key="nav_conta", use_container_width=True,
                 type="secondary"):
        st.session_state.modulo_ativo = "conta"
        st.rerun()
