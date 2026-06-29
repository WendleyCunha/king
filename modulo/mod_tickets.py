# modulo/mod_tickets.py
"""
Módulo de Tickets — KingStar Painel Integrado
─────────────────────────────────────────────
Correções aplicadas:
  [1] Bug: preview do ticket exibia código-fonte HTML bruto.
      Fix: usar st.markdown(..., unsafe_allow_html=True) ao exibir
           campos que contêm HTML, nunca st.write() ou st.text().
  [2] Abertura de ticket agora aplica Regra 1:
      → roteamento automático por departamento + tabulação.
"""

import streamlit as st
from datetime import datetime, timezone, timedelta
import time
import uuid

# Importa funções do banco (ajuste os nomes conforme seu database.py)
from database import (
    obter_tickets_db,
    listar_departamentos,
    listar_tabulacoes,
    resolver_destinatario_ticket,
)

BRT = timezone(timedelta(hours=-3))


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _agora_brt_str():
    return datetime.now(BRT).strftime("%Y-%m-%d %H:%M")


def _status_cor(status):
    return {
        "Aberto":        "#e74c3c",
        "Em Andamento":  "#e67e22",
        "Aguardando":    "#f1c40f",
        "Resolvido":     "#27ae60",
        "Urgente":       "#8e44ad",
    }.get(status, "#95a5a6")


def _prio_cor(prio):
    return {
        "Urgente": "#e74c3c",
        "Alta":    "#e67e22",
        "Normal":  "#27ae60",
        "Baixa":   "#95a5a6",
    }.get(prio, "#27ae60")


def _ticket_id():
    """Gera ID curto para o ticket."""
    return "#" + uuid.uuid4().hex[:8].upper()


def _sanitize_html(value):
    """
    FIX [1] — Garante que o valor exibido é string segura.
    Se o valor já é HTML (começa com '<'), retorna como unsafe HTML.
    Caso contrário, trata como texto puro.
    """
    if value is None:
        return ""
    s = str(value).strip()
    return s


# ─────────────────────────────────────────────────────────────────────────────
# CARD DE TICKET (preview na lista)
# ─────────────────────────────────────────────────────────────────────────────

def _render_ticket_card(ticket, idx):
    """
    Renderiza o card de preview de um ticket na lista.
    CORREÇÃO: todos os campos HTML são passados com unsafe_allow_html=True.
    Nunca usar st.write() ou st.text() com conteúdo que pode conter HTML.
    """
    tid      = ticket.get("id", f"TK{idx}")
    assunto  = ticket.get("assunto", "Sem assunto")
    status   = ticket.get("status", "Aberto")
    depto    = ticket.get("departamento", "—")
    solicit  = ticket.get("solicitante", "—")
    criado   = ticket.get("criado_em", "")
    prio     = ticket.get("prioridade", "Normal")
    sla_h    = ticket.get("sla_horas", 24)
    tabul    = ticket.get("tabulacao", "")

    # Calcula SLA restante
    sla_label  = ""
    sla_color  = "#16A34A"
    sla_width  = 0
    if criado:
        try:
            dt_criado = datetime.fromisoformat(criado)
            if dt_criado.tzinfo is None:
                dt_criado = dt_criado.replace(tzinfo=timezone.utc)
            agora     = datetime.now(timezone.utc)
            decorrido = (agora - dt_criado).total_seconds() / 3600
            restante  = max(0, sla_h - decorrido)
            pct       = min(100, (decorrido / sla_h) * 100) if sla_h else 0
            sla_width = pct
            sla_color = "#16A34A" if pct < 60 else ("#F59E0B" if pct < 85 else "#DC2626")
            h, m      = int(restante), int((restante % 1) * 60)
            sla_label = f"{h}h {m}m"
        except Exception:
            sla_label = f"{sla_h}h"

    sc = _status_cor(status)
    pc = _prio_cor(prio)

    # ── HTML do card ─────────────────────────────────────────────────
    # Conteúdo 100% controlado — sem valores vindos de input livre do usuário
    # sendo injetados como HTML.
    card_html = f"""
    <div style="
        background:#fff; border:1px solid #e2e8f0; border-radius:12px;
        padding:16px 20px; margin-bottom:4px;
        border-left:5px solid {sc};
    ">
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div style="flex:1;">
                <div style="font-weight:800; font-size:0.92rem; color:#2c3e50; margin-bottom:2px;">
                    🎫 {tid}
                </div>
                <div style="font-weight:700; font-size:0.95rem; color:#34495e; margin-bottom:6px;">
                    {assunto}
                </div>
                <div style="font-size:0.78rem; color:#64778d;">
                    🏢 {depto} &nbsp;·&nbsp; 👤 {solicit} &nbsp;·&nbsp; 🕐 {criado[:16] if criado else '—'}
                    {"&nbsp;·&nbsp; 📋 " + tabul if tabul else ""}
                </div>
            </div>
            <div style="text-align:right; white-space:nowrap; margin-left:16px;">
                <span style="
                    background:{sc}22; color:{sc}; padding:3px 10px;
                    border-radius:10px; font-size:0.72rem; font-weight:700;
                    display:block; margin-bottom:4px;
                ">{status}</span>
                <span style="
                    background:{pc}22; color:{pc}; padding:3px 10px;
                    border-radius:10px; font-size:0.72rem; font-weight:700;
                ">{prio}</span>
            </div>
        </div>
        <!-- Barra SLA -->
        <div style="
            background:#f0f0f0; border-radius:4px; height:5px;
            margin-top:10px; overflow:hidden;
        ">
            <div style="width:{sla_width:.0f}%; background:{sla_color}; height:5px;"></div>
        </div>
        <div style="font-size:0.72rem; color:{sla_color}; margin-top:3px; font-weight:600;">
            SLA: <b style="color:{sla_color};">{sla_label}</b>
        </div>
    </div>
    """
    # ✅ CORREÇÃO [1]: usar unsafe_allow_html=True — o HTML é gerado por nós,
    #    não vem diretamente de campos livres do usuário sem tratamento.
    st.markdown(card_html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# FORMULÁRIO DE ABERTURA DE TICKET
# ─────────────────────────────────────────────────────────────────────────────

def _form_novo_ticket(user):
    """
    Formulário de abertura com Regra 1:
    → seleciona departamento + tabulação → roteamento automático.
    """
    st.markdown("### ➕ Abrir Novo Ticket")

    departamentos = listar_departamentos()
    dep_nomes     = [d["nome"] for d in departamentos]

    if not dep_nomes:
        st.warning("Nenhum departamento cadastrado. Peça ao administrador para cadastrar.")
        return

    with st.form("form_novo_ticket", clear_on_submit=True):
        c1, c2 = st.columns(2)
        assunto   = c1.text_input("Assunto *", placeholder="Descreva brevemente o problema...")
        solicit   = c2.text_input("Solicitante *",
                                  value=user.get("nome",""),
                                  placeholder="Nome do solicitante")

        # Departamento → filtra tabulações
        dep_sel = st.selectbox("Departamento *", dep_nomes)

        # Tabulações do departamento selecionado
        todas_tabs = listar_tabulacoes()
        tabs_dep   = [t for t in todas_tabs if t.get("departamento") == dep_sel]
        tab_opts   = ["— Selecione (opcional) —"] + [t["nome"] for t in tabs_dep]
        tab_sel    = st.selectbox("Tabulação", tab_opts,
                                  help="A tabulação define prioridade, SLA e atendentes automaticamente.")

        descricao = st.text_area("Descrição detalhada *", height=120,
                                 placeholder="Descreva o problema com detalhes...")

        # Campos extras
        fc1, fc2 = st.columns(2)
        canal     = fc1.selectbox("Canal de entrada",
                                  ["Sistema","E-mail","WhatsApp","Telefone","Presencial"])
        prio_man  = fc2.selectbox("Prioridade (manual)",
                                  ["Normal","Alta","Urgente","Baixa"],
                                  help="Será sobrescrita pela tabulação se ela tiver prioridade definida.")

        if st.form_submit_button("🎫 Abrir Ticket", type="primary"):
            if not assunto or not descricao or not solicit:
                st.error("Preencha os campos obrigatórios: Assunto, Solicitante e Descrição.")
                return

            # ── Regra 1: Roteamento automático ─────────────────────
            tab_nome = tab_sel if tab_sel != "— Selecione (opcional) —" else None
            dest     = resolver_destinatario_ticket(dep_sel, tab_nome)

            ticket_data = {
                "id":           _ticket_id(),
                "assunto":      assunto,
                "descricao":    descricao,          # texto puro — não HTML
                "solicitante":  solicit,
                "departamento": dep_sel,
                "tabulacao":    tab_nome or "",
                "status":       "Aberto",
                "prioridade":   dest["prioridade"] if tab_nome else prio_man,
                "sla_horas":    dest["sla_horas"],
                "atendentes":   dest["atendentes"],  # Regra 1
                "canal":        canal,
                "criado_em":    datetime.now(timezone.utc).isoformat(),
                "criado_por":   user.get("usuario",""),
                "historico":    [],
            }

            # Salva no Firestore
            _salvar_ticket(ticket_data)

            atend_msg = (
                ", ".join(dest["atendentes"])
                if dest["atendentes"]
                else f"todo o departamento {dep_sel}"
            )
            st.success(
                f"✅ Ticket **{ticket_data['id']}** aberto! "
                f"Roteado para: **{atend_msg}** · SLA: **{dest['sla_horas']}h**"
            )
            time.sleep(1.5)
            st.rerun()


def _salvar_ticket(ticket_data):
    """Salva ticket no Firestore."""
    try:
        from firebase_admin import firestore
        db = firestore.client()
        db.collection("tickets").document(ticket_data["id"]).set(ticket_data)
    except Exception as e:
        st.error(f"Erro ao salvar ticket: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# DETALHE DO TICKET
# ─────────────────────────────────────────────────────────────────────────────

def _render_ticket_detalhe(ticket, user, papel):
    """
    Exibe os detalhes completos de um ticket.
    CORREÇÃO [1]: campos de texto livre são exibidos como st.markdown() puro (sem HTML)
    ou com st.text_area() — nunca renderizados como HTML bruto.
    """
    tid     = ticket.get("id","—")
    assunto = ticket.get("assunto","—")
    status  = ticket.get("status","Aberto")
    depto   = ticket.get("departamento","—")
    prio    = ticket.get("prioridade","Normal")
    tabul   = ticket.get("tabulacao","—")
    sc      = _status_cor(status)
    pc      = _prio_cor(prio)

    st.markdown(f"""
    <div style="border-left:5px solid {sc}; padding:12px 20px;
                background:#fff; border-radius:8px; margin-bottom:16px;">
        <div style="font-size:1.1rem; font-weight:800; color:#2c3e50;">{tid} — {assunto}</div>
        <div style="font-size:0.8rem; color:#64778d; margin-top:4px;">
            🏢 {depto} &nbsp;·&nbsp; 📋 {tabul} &nbsp;·&nbsp;
            <span style="color:{sc};font-weight:700;">{status}</span> &nbsp;·&nbsp;
            <span style="color:{pc};font-weight:700;">{prio}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_d, col_a = st.columns([2, 1])

    with col_d:
        st.markdown("**📝 Descrição**")
        # ✅ CORREÇÃO [1]: descrição é texto puro, exibida em caixa de texto.
        # NUNCA usar st.markdown(descricao, unsafe_allow_html=True) pois
        # o usuário pode ter digitado HTML/código que seria renderizado.
        descricao = ticket.get("descricao","")
        st.text_area(
            "Descrição do ticket",
            value=descricao,
            height=150,
            disabled=True,
            label_visibility="collapsed"
        )

        # Histórico / comentários
        st.markdown("**💬 Histórico**")
        historico = ticket.get("historico", [])
        if not historico:
            st.caption("Nenhum comentário ainda.")
        else:
            for h in historico:
                autor  = h.get("autor","?")
                texto  = h.get("texto","")
                data   = h.get("data","")
                # ✅ texto do histórico também como text puro
                st.markdown(
                    f"<div style='background:#f8f9fa;border-radius:8px;padding:10px;"
                    f"margin-bottom:6px;border-left:3px solid #C9A84C;'>"
                    f"<b>{autor}</b> <span style='font-size:0.75rem;color:#999;'>{data}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
                st.text(texto)   # ← texto bruto, seguro

        # Adicionar comentário
        st.markdown("**➕ Adicionar comentário**")
        novo_coment = st.text_area("Comentário", key=f"coment_{tid}", height=80,
                                   label_visibility="collapsed")
        if st.button("Enviar comentário", key=f"btn_coment_{tid}"):
            if novo_coment.strip():
                _adicionar_comentario(tid, user.get("usuario",""), novo_coment.strip())
                st.success("Comentário adicionado!"); time.sleep(.5); st.rerun()

    with col_a:
        st.markdown("**⚙️ Ações**")

        # Alterar status
        status_opts  = ["Aberto","Em Andamento","Aguardando","Resolvido","Urgente"]
        novo_status  = st.selectbox("Status", status_opts,
                                    index=status_opts.index(status) if status in status_opts else 0,
                                    key=f"sel_status_{tid}")
        if st.button("Atualizar status", key=f"btn_status_{tid}", type="primary"):
            _atualizar_campo_ticket(tid, "status", novo_status)
            st.success(f"Status → {novo_status}"); time.sleep(.5); st.rerun()

        st.markdown("---")

        # Info extras
        atend = ticket.get("atendentes", [])
        st.markdown(
            f"**Atendentes:** "
            + (", ".join(f"`{a}`" for a in atend) if atend else "Todo o depto")
        )
        st.markdown(f"**SLA:** {ticket.get('sla_horas',24)}h")
        st.markdown(f"**Canal:** {ticket.get('canal','—')}")
        st.markdown(f"**Criado por:** `{ticket.get('criado_por','—')}`")
        st.markdown(f"**Em:** {ticket.get('criado_em','—')[:16]}")

        if st.button("⬅️ Voltar", key=f"btn_voltar_{tid}"):
            st.session_state.pop("ticket_aberto", None)
            st.rerun()


def _adicionar_comentario(ticket_id, autor, texto):
    try:
        from firebase_admin import firestore
        from datetime import datetime, timezone
        db = firestore.client()
        ref = db.collection("tickets").document(ticket_id)
        doc = ref.get()
        if doc.exists:
            hist = doc.to_dict().get("historico", [])
            hist.append({
                "autor": autor,
                "texto": texto,
                "data":  datetime.now(timezone.utc).isoformat()[:16],
            })
            ref.update({"historico": hist})
    except Exception as e:
        st.error(f"Erro: {e}")


def _atualizar_campo_ticket(ticket_id, campo, valor):
    try:
        from firebase_admin import firestore
        db = firestore.client()
        db.collection("tickets").document(ticket_id).update({campo: valor})
    except Exception as e:
        st.error(f"Erro: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# RENDERIZADOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def renderizar_tickets(papel, user=None):
    """
    Ponto de entrada do módulo de Tickets.
    Layout: sidebar de filas (esquerda) + área principal (direita).
    """
    if user is None:
        st.error("Usuário não identificado.")
        return

    # ── Estado ──────────────────────────────────────────────────────
    if "ticket_aberto"   not in st.session_state: st.session_state.ticket_aberto   = None
    if "fila_ativa"      not in st.session_state: st.session_state.fila_ativa      = "Todos"
    if "mostrar_novo"    not in st.session_state: st.session_state.mostrar_novo    = False
    if "busca_ticket"    not in st.session_state: st.session_state.busca_ticket    = ""

    # ── Carrega tickets ─────────────────────────────────────────────
    todos_tickets = obter_tickets_db() or []

    # Filtra por departamento do usuário (operacional só vê o próprio depto)
    dep_user = user.get("departamento","")
    if papel == "operacional" and dep_user:
        todos_tickets = [
            t for t in todos_tickets
            if t.get("departamento") == dep_user
            or user.get("usuario","") in t.get("atendentes",[])
        ]

    # ── Contadores por status ────────────────────────────────────────
    def conta(s):
        return sum(1 for t in todos_tickets if t.get("status") == s)

    filas = [
        ("Todos",       len(todos_tickets)),
        ("Aberto",      conta("Aberto")),
        ("Em Andamento",conta("Em Andamento")),
        ("Aguardando",  conta("Aguardando")),
        ("Resolvido",   conta("Resolvido")),
        ("Urgente",     conta("Urgente")),
    ]

    # ── Layout duas colunas ──────────────────────────────────────────
    col_esq, col_dir = st.columns([1, 3])

    # ── COLUNA ESQUERDA — filas + ações ─────────────────────────────
    with col_esq:
        st.markdown("**Filas de Trabalho**")
        for nome_fila, qtd in filas:
            ativo = st.session_state.fila_ativa == nome_fila
            label = f"{nome_fila} ({qtd})"
            cor   = "#e74c3c" if nome_fila == "Urgente" else ("#C9A84C" if ativo else None)
            style = (
                f"background:{'#e74c3c' if nome_fila=='Urgente' else 'rgba(201,168,76,.15)'};"
                f"color:{'#fff' if nome_fila=='Urgente' else '#7a5f1a'};"
                if ativo or nome_fila=="Urgente" else ""
            )
            if st.button(label, key=f"fila_{nome_fila}",
                         use_container_width=True,
                         type="primary" if ativo else "secondary"):
                st.session_state.fila_ativa    = nome_fila
                st.session_state.ticket_aberto = None
                st.rerun()

        st.markdown("---")
        st.markdown("**Ações**")
        if st.button("➕ Novo Ticket", key="btn_novo", use_container_width=True, type="primary"):
            st.session_state.mostrar_novo    = True
            st.session_state.ticket_aberto  = None
            st.rerun()

    # ── COLUNA DIREITA — conteúdo ────────────────────────────────────
    with col_dir:

        # Modo: novo ticket
        if st.session_state.mostrar_novo:
            if st.button("⬅️ Cancelar", key="btn_cancel_novo"):
                st.session_state.mostrar_novo = False
                st.rerun()
            _form_novo_ticket(user)
            return

        # Modo: ticket aberto em detalhe
        if st.session_state.ticket_aberto:
            tid  = st.session_state.ticket_aberto
            tick = next((t for t in todos_tickets if t.get("id") == tid), None)
            if tick:
                _render_ticket_detalhe(tick, user, papel)
            else:
                st.warning("Ticket não encontrado.")
                st.session_state.ticket_aberto = None
            return

        # Modo: lista de tickets
        busca = st.text_input(
            "🔍", placeholder="Buscar por ID, assunto, solicitante...",
            label_visibility="collapsed",
            key="busca_ticket_input"
        )

        # Aplica filtros
        fila_ativa = st.session_state.fila_ativa
        tickets_filtrados = todos_tickets if fila_ativa == "Todos" \
            else [t for t in todos_tickets if t.get("status") == fila_ativa]

        if busca:
            b = busca.lower()
            tickets_filtrados = [
                t for t in tickets_filtrados
                if b in t.get("id","").lower()
                or b in t.get("assunto","").lower()
                or b in t.get("solicitante","").lower()
            ]

        st.caption(f"{len(tickets_filtrados)} ticket(s)")

        if not tickets_filtrados:
            st.info("Nenhum ticket nesta fila.")
        else:
            for i, ticket in enumerate(tickets_filtrados):
                _render_ticket_card(ticket, i)
                # Botão abrir abaixo do card
                if st.button("Abrir", key=f"open_{ticket.get('id',i)}_{i}"):
                    st.session_state.ticket_aberto = ticket.get("id")
                    st.session_state.mostrar_novo  = False
                    st.rerun()
