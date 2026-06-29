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
    atualizar_departamento_usuario,
    listar_tabulacoes, criar_tabulacao, atualizar_tabulacao, deletar_tabulacao,
)
from modulo.mod_rastreio import renderizar_rastreio

try:
    from modulo.mod_tickets import renderizar_tickets
except ImportError:
    def renderizar_tickets(papel, user=None): st.info("🚧 Módulo de Tickets em desenvolvimento...")

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
</style>
""", unsafe_allow_html=True)

# ── INIT SESSION STATE ─────────────────────────────────────────────
if "user"         not in st.session_state: st.session_state.user = None
if "modulo_ativo" not in st.session_state: st.session_state.modulo_ativo = "rastreio"

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
                st.rerun()
            else:
                st.error("Credenciais inválidas.")
    st.stop()

# ── USUÁRIO CONFIRMADO ────────────────────────────────────────────
user  = st.session_state.user
papel = user.get("role", "operacional")
mods  = modulos_do_usuario(user)

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

    for key, label in [("rastreio","Rastreio"), ("tickets","Tickets")]:
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

# ── DADOS ─────────────────────────────────────────────────────────
datas_db     = obter_datas_disponiveis_db()
modulo_ativo = st.session_state.modulo_ativo

# ── ROTEAMENTO ────────────────────────────────────────────────────
if modulo_ativo == "rastreio" and tem_permissao(user, "rastreio"):
    is_hoje = renderizar_rastreio(
        papel, user, datas_db=datas_db, pode_exp=pode_exportar(user)
    )
    # Auto-refresh via meta HTML — não bloqueia o thread, não causa flash
    if is_hoje:
        st.markdown(
            '<meta http-equiv="refresh" content="20">',
            unsafe_allow_html=True
        )

elif modulo_ativo == "tickets" and tem_permissao(user, "tickets"):
    renderizar_tickets(papel, user)

elif modulo_ativo == "config" and papel == "adm":
    st.subheader("⚙️ Configurações")
    aba_u, aba_m, aba_dep, aba_tab = st.tabs(
        ["👥 Usuários", "🔒 Permissões", "🏢 Departamentos", "📋 Tabulação"]
    )

    # ─── ABA USUÁRIOS ─────────────────────────────────────────────
    with aba_u:
        deps      = listar_departamentos()
        dep_nomes = [d["nome"] for d in deps]

        with st.expander("➕ Cadastrar Novo Usuário", expanded=True):
            if not dep_nomes:
                st.info("⚠️ Cadastre um departamento na aba **Departamentos** antes de criar usuários.")
            with st.form("form_novo"):
                c1, c2  = st.columns(2)
                n_nome  = c1.text_input("Nome Completo")
                n_user  = c2.text_input("Login")
                n_senha = c1.text_input("Senha", type="password")
                n_nivel = c2.selectbox("Nível", ["operacional","supervisor","adm"])
                # ── Campo DEPARTAMENTO (Regra 1) ──
                n_dep   = st.selectbox("Departamento",
                                       options=(["— Selecione —"] + dep_nomes),
                                       help="Tickets do departamento caem automaticamente para este usuário.")
                ma, mb  = st.columns(2)
                m_r     = ma.checkbox("Rastreio", value=True)
                m_t     = mb.checkbox("Tickets", value=n_nivel in ("supervisor","adm"))
                if st.form_submit_button("Criar"):
                    if not (n_nome and n_user and n_senha):
                        st.warning("Preencha todos os campos.")
                    elif n_dep == "— Selecione —":
                        st.warning("Selecione um departamento.")
                    else:
                        ms = [m for m,v in [("rastreio",m_r),("tickets",m_t),("exportar",m_r)] if v]
                        criar_usuario(n_nome, n_user, n_senha, n_nivel, ms, departamento=n_dep)
                        st.success(f"Usuário **{n_user}** criado no depto **{n_dep}**!")
                        time.sleep(1); st.rerun()

        st.markdown("---")
        st.markdown("### Usuários Ativos")
        for i_u, u in enumerate(listar_usuarios()):
            uname = u.get("usuario", f"u{i_u}")
            dep   = u.get("departamento", "—") or "—"
            with st.expander(f"**{u.get('nome','—')}** · `{uname}` · {u.get('role','—').upper()} · 🏢 {dep}"):
                # Trocar departamento de usuário existente
                if dep_nomes:
                    idx = (dep_nomes.index(dep) + 1) if dep in dep_nomes else 0
                    novo_dep = st.selectbox("Departamento",
                                            ["— Selecione —"] + dep_nomes,
                                            index=idx, key=f"dep_{uname}_{i_u}")
                    if st.button("💾 Atualizar departamento", key=f"svdep_{uname}_{i_u}"):
                        if novo_dep != "— Selecione —":
                            atualizar_departamento_usuario(uname, novo_dep)
                            st.success("Departamento atualizado!"); time.sleep(.5); st.rerun()
                if uname != "admin":
                    if st.button("🗑️ Excluir usuário", key=f"del_{uname}_{i_u}"):
                        deletar_usuario(uname); st.rerun()

    # ─── ABA PERMISSÕES ───────────────────────────────────────────
    with aba_m:
        st.markdown("### Permissões por Usuário")
        for i_u, u in enumerate(listar_usuarios()):
            uname = u.get("usuario", f"u{i_u}")
            umods = u.get("modulos", MODULOS_PADRAO.get(u.get("role","operacional"), []))
            dep   = u.get("departamento", "—") or "—"
            with st.expander(f"**{u.get('nome','—')}** · `{uname}` · 🏢 {dep}"):
                ma, mb = st.columns(2)
                nr = ma.checkbox("Rastreio", value="rastreio" in umods, key=f"r_{uname}")
                nt = mb.checkbox("Tickets",  value="tickets"  in umods, key=f"t_{uname}")
                if st.button("💾 Salvar", key=f"sv_{uname}", type="primary"):
                    ns = [m for m,v in [("rastreio",nr),("tickets",nt),("exportar",nr)] if v]
                    atualizar_modulos_usuario(uname, ns)
                    st.success("Salvo!"); time.sleep(.5); st.rerun()

    # ─── ABA DEPARTAMENTOS ────────────────────────────────────────
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
            tabs_dep  = [t for t in listar_tabulacoes() if t.get("departamento") == dep["nome"]]
            with st.expander(f"🏢 **{dep['nome']}** · 👤 {len(users_dep)} usuário(s) · 📋 {len(tabs_dep)} tabulação(ões)"):
                if dep.get("descricao"):
                    st.caption(dep["descricao"])
                if users_dep:
                    st.markdown("**Usuários:** " + ", ".join(f"`{u['usuario']}`" for u in users_dep))
                if tabs_dep:
                    st.markdown("**Tabulações:** " + ", ".join(f"`{t['nome']}`" for t in tabs_dep))
                if st.button(f"🗑️ Excluir '{dep['nome']}'", key=f"deldep_{dep['id']}"):
                    ok, msg = deletar_departamento(dep["id"])
                    (st.success if ok else st.error)(msg)
                    if ok: time.sleep(.5); st.rerun()

    # ─── ABA TABULAÇÃO ────────────────────────────────────────────
    with aba_tab:
        st.markdown("### 📋 Tabulações por Departamento")
        st.caption("Crie motivos/categorias por departamento e vincule atendentes específicos "
                   "(ou deixe liberado para todo o departamento).")

        deps           = listar_departamentos()
        dep_nomes      = [d["nome"] for d in deps]
        todos_usuarios = listar_usuarios()

        with st.expander("➕ Nova Tabulação", expanded=True):
            if not dep_nomes:
                st.warning("⚠️ Cadastre um departamento antes de criar tabulações.")
            else:
                with st.form("form_tab"):
                    tc1, tc2 = st.columns(2)
                    t_nome = tc1.text_input("Nome da Tabulação",
                                            placeholder="Ex: Troca de produto, Entrega atrasada...")
                    t_dep  = tc2.selectbox("Departamento", dep_nomes)
                    t_desc = st.text_area("Descrição (opcional)", height=70)

                    # Atendentes do departamento escolhido (Regra 4)
                    users_do_dep = [u for u in todos_usuarios if u.get("departamento") == t_dep]
                    opts = {u["usuario"]: u.get("nome", u["usuario"]) for u in users_do_dep}
                    t_atendentes = st.multiselect(
                        "Atendentes específicos (vazio = todo o departamento)",
                        options=list(opts.keys()),
                        format_func=lambda x: f"{opts.get(x,x)} ({x})"
                    )
                    tp1, tp2 = st.columns(2)
                    t_prio  = tp1.selectbox("Prioridade padrão", ["Normal","Alta","Urgente","Baixa"])
                    t_sla   = tp2.number_input("SLA (horas)", min_value=1, max_value=720, value=24, step=1)

                    if st.form_submit_button("Criar Tabulação"):
                        ok, msg = criar_tabulacao(
                            nome=t_nome, departamento=t_dep, descricao=t_desc,
                            atendentes=t_atendentes, prioridade=t_prio, sla_horas=t_sla
                        )
                        (st.success if ok else st.error)(msg)
                        if ok: time.sleep(.8); st.rerun()
                st.caption("💡 Os atendentes listados são apenas os do departamento selecionado.")

        st.markdown("---")
        filtro = st.selectbox("🔍 Filtrar por departamento", ["Todos"] + dep_nomes, key="tab_filtro")
        tabulacoes = listar_tabulacoes()
        if filtro != "Todos":
            tabulacoes = [t for t in tabulacoes if t.get("departamento") == filtro]

        if not tabulacoes:
            st.info("Nenhuma tabulação cadastrada.")
        for tab in tabulacoes:
            atend = tab.get("atendentes", [])
            atend_str = (", ".join(f"`{a}`" for a in atend) if atend else "🌐 Todo o departamento")
            with st.expander(f"📋 **{tab['nome']}** · 🏢 {tab.get('departamento','—')} · ⏱ {tab.get('sla_horas',24)}h"):
                st.markdown(f"**Atendentes:** {atend_str}")
                if tab.get("descricao"):
                    st.markdown(f"**Descrição:** {tab['descricao']}")

                st.markdown("**Editar:**")
                users_dep = [u for u in todos_usuarios if u.get("departamento") == tab.get("departamento")]
                opts = {u["usuario"]: u.get("nome", u["usuario"]) for u in users_dep}
                # garante que atendentes já salvos apareçam mesmo se trocaram de depto
                for a in atend:
                    opts.setdefault(a, a)
                novos = st.multiselect(
                    "Atendentes", options=list(opts.keys()), default=atend,
                    format_func=lambda x: f"{opts.get(x,x)} ({x})",
                    key=f"atd_{tab['id']}"
                )
                e1, e2 = st.columns(2)
                nova_prio = e1.selectbox("Prioridade", ["Normal","Alta","Urgente","Baixa"],
                                         index=["Normal","Alta","Urgente","Baixa"].index(tab.get("prioridade","Normal")),
                                         key=f"prio_{tab['id']}")
                novo_sla  = e2.number_input("SLA (h)", min_value=1, max_value=720,
                                            value=int(tab.get("sla_horas",24)), key=f"sla_{tab['id']}")
                b1, b2 = st.columns(2)
                if b1.button("💾 Salvar", key=f"svtab_{tab['id']}", type="primary"):
                    ok, msg = atualizar_tabulacao(tab["id"], atendentes=novos,
                                                  prioridade=nova_prio, sla_horas=novo_sla)
                    (st.success if ok else st.error)(msg)
                    if ok: time.sleep(.5); st.rerun()
                if b2.button("🗑️ Excluir", key=f"deltab_{tab['id']}"):
                    ok, msg = deletar_tabulacao(tab["id"])
                    (st.success if ok else st.error)(msg)
                    if ok: time.sleep(.5); st.rerun()

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
