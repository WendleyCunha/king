"""
KingStar — Módulo de Tickets  (v3)
─────────────────────────────────────────────────────────────────────────────
Correções / novidades nesta versão:
  [1] Bug do HTML aparecendo como código-fonte → corrigido com _html()
      (remove a indentação que o Markdown interpretava como bloco de código)
      + escape do texto livre do usuário (assunto, descrição, etc).
  [2] Abertura escolhe o DEPARTAMENTO. Só usuários do depto tratam o ticket
      (roteamento via resolver_destinatario_ticket).
  [3] Só aparecem as TABULAÇÕES vinculadas ao departamento escolhido.
  [4] SLA vem da tabulação e gera ALERTA PISCANTE quando vence com ticket pendente.
  [5] Visibilidade por papel:
        - operacional → só os próprios tickets
        - supervisor  → todos os tickets + aba "Equipe" do seu departamento
        - adm         → tudo de todos
"""
import streamlit as st
import pandas as pd
import time
import sys
import os
import html as _htmlmod
from datetime import datetime, timezone, timedelta

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _root not in sys.path:
    sys.path.insert(0, _root)

from database import (
    get_db,
    listar_departamentos, listar_tabulacoes, resolver_destinatario_ticket,
    listar_usuarios,
)

BRT     = timezone(timedelta(hours=-3))
COLECAO = "tickets"

# ── Configurações Zendesk ─────────────────────────────────────────
ZENDESK_SUBDOMAIN = "kingstarcolchoessupport"
ZENDESK_EMAIL     = "wendley.cunha@kingstarcolchoes.com.br"
ZENDESK_TOKEN     = "tXqPtSws0qZMh4uiZnADQbeqUd2t2UjHUFlliTP8"
ZENDESK_VIEW_ID   = "30824480549655"

STATUS_CFG = {
    "aberto":       ("Aberto",       "#FEF9C3","#854D0E","#CA8A04"),
    "em_andamento": ("Em Andamento", "#EFF6FF","#1D5FAE","#2563EB"),
    "aguardando":   ("Aguardando",   "#FFF7ED","#9A3412","#EA580C"),
    "resolvido":    ("Resolvido",    "#DCFCE7","#15803D","#16A34A"),
    "cancelado":    ("Cancelado",    "#F1F5F9","#475569","#64748B"),
}

PRIO_CFG = {
    "urgente": ("Urgente","#FEE2E2","#991B1B"),
    "alta":    ("Alta",   "#FFF7ED","#9A3412"),
    "normal":  ("Normal", "#F0FDF4","#166534"),
    "baixa":   ("Baixa",  "#F1F5F9","#475569"),
}

STATUS_ABERTOS = ("aberto", "em_andamento", "aguardando")  # pendentes p/ SLA

# ── Helpers ────────────────────────────────────────────────────────
def agora_brt() -> str:
    return datetime.now(BRT).strftime("%Y-%m-%d %H:%M:%S")

def _html(s: str) -> str:
    """Remove a indentação de cada linha (que vira 'bloco de código' no Markdown)."""
    return "\n".join(linha.lstrip() for linha in s.splitlines())

def esc(v) -> str:
    """Escapa texto livre do usuário antes de injetar no HTML."""
    return _htmlmod.escape(str(v if v is not None else ""))

def texto_busca(t) -> str:
    """Concatena tudo que é pesquisável de um ticket (busca global)."""
    partes = [
        t.get("id",""), t.get("id_zendesk",""), t.get("assunto",""),
        t.get("descricao",""), t.get("solicitante_nome",""),
        t.get("cliente_nome",""), t.get("cliente_codigo",""),
        t.get("tabulacao",""), t.get("departamento",""),
        t.get("categoria",""), t.get("subcategoria",""),
        t.get("prioridade",""), t.get("status",""),
    ]
    for a in t.get("atendentes", []):
        partes.append(a)
    for c in t.get("comentarios", []):
        partes.append(c.get("texto",""))
        partes.append(c.get("autor",""))
    return " ".join(str(p) for p in partes if p).lower()

def transferir_tickets(tids: list, novo_responsavel: str):
    """Reatribui uma lista de tickets para um novo responsável (atendente)."""
    db = get_db()
    batch = db.batch()
    n = 0
    for tid in tids:
        ref = db.collection(COLECAO).document(tid)
        batch.update(ref, {
            "atendentes": [novo_responsavel],
            "atribuido_para": novo_responsavel,
            "atualizado_em": agora_brt(),
        })
        n += 1
        if n % 450 == 0:
            batch.commit(); batch = db.batch()
    batch.commit()
    return n

def sla_restante(criado_em: str, horas_sla: int = 24) -> tuple:
    """Retorna (texto, pct_usado, vencido)."""
    try:
        dt = datetime.fromisoformat(criado_em.replace(" ","T")).replace(tzinfo=BRT)
        limite = dt + timedelta(hours=horas_sla)
        agora  = datetime.now(BRT)
        diff   = limite - agora
        total  = timedelta(hours=horas_sla).total_seconds()
        decorrido = (agora - dt).total_seconds()
        pct    = min(decorrido / total * 100, 100)
        if diff.total_seconds() <= 0:
            return "Expirado", 100, True
        h = int(diff.total_seconds() // 3600)
        m = int((diff.total_seconds() % 3600) // 60)
        return (f"{h}h {m}m" if h > 0 else f"{m}min"), pct, False
    except Exception:
        return "—", 0, False

def pill(texto, bg, cor):
    return (f'<span style="background:{bg};color:{cor};padding:2px 10px;'
            f'border-radius:12px;font-size:0.72rem;font-weight:700;">{esc(texto)}</span>')

def ticket_vencido_pendente(t) -> bool:
    """True se o SLA estourou E o ticket ainda está pendente."""
    if t.get("status") not in STATUS_ABERTOS:
        return False
    _, _, venc = sla_restante(t.get("criado_em",""), t.get("horas_sla", 24))
    return venc

# ── Visibilidade por papel (Regra 5) ───────────────────────────────
def _usuario_atende(t, user) -> bool:
    uname = user.get("usuario","")
    nome  = user.get("nome","")
    return (uname in t.get("atendentes", [])
            or t.get("atribuido_para") in (uname, nome)
            or t.get("aberto_por") == uname)

def ticket_visivel(t, user, papel) -> bool:
    if papel == "adm":
        return True
    if papel == "supervisor":
        return t.get("departamento","") == (user.get("departamento","") or "—")
    # operacional
    return _usuario_atende(t, user)

# ── Popup (modal) de detalhe ───────────────────────────────────────
def abrir_ticket_popup(tid, user, papel):
    """Abre o detalhe do ticket num POPUP (st.dialog). Se a versão do
    Streamlit não suportar, cai no modo detalhe inline."""
    deco = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)
    if deco is None:
        st.session_state.tk_detalhe = tid
        st.session_state.tk_modo    = "detalhe"
        st.rerun()
        return
    try:
        @deco("Detalhe do Ticket", width="large")
        def _popup():
            _carregar_e_render_detalhe(tid, user, papel, modal=True)
        _popup()
    except TypeError:
        # versões antigas sem o parâmetro width
        @deco("Detalhe do Ticket")
        def _popup2():
            _carregar_e_render_detalhe(tid, user, papel, modal=True)
        _popup2()

# ── CRUD Firestore ─────────────────────────────────────────────────
def listar_tickets() -> list:
    docs = get_db().collection(COLECAO).stream()
    return sorted(
        [d.to_dict() for d in docs],
        key=lambda x: x.get("criado_em",""), reverse=True
    )

def criar_ticket(dados: dict) -> str:
    ref  = get_db().collection(COLECAO).document()
    base = {
        "id": ref.id, "criado_em": agora_brt(),
        "atualizado_em": agora_brt(), "origem": "interno",
        "comentarios": [],
    }
    base.update(dados)                  # respeita status/horas_sla/prioridade enviados
    base.setdefault("status", "aberto")
    base.setdefault("horas_sla", 24)
    ref.set(base)
    return ref.id

def atualizar_ticket(tid: str, dados: dict):
    dados["atualizado_em"] = agora_brt()
    get_db().collection(COLECAO).document(tid).update(dados)

def adicionar_comentario(tid: str, autor: str, texto: str):
    from google.cloud.firestore import ArrayUnion
    get_db().collection(COLECAO).document(tid).update({
        "comentarios": ArrayUnion([{
            "autor": autor, "texto": texto, "data": agora_brt()
        }]),
        "atualizado_em": agora_brt(),
    })

# ── Sync Zendesk ───────────────────────────────────────────────────
def sync_zendesk() -> tuple:
    import requests as req
    url  = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/views/{ZENDESK_VIEW_ID}/tickets.json?per_page=100"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
    try:
        r = req.get(url, auth=auth, timeout=15)
        if r.status_code != 200:
            return False, 0, f"Zendesk retornou {r.status_code}"
        tickets = r.json().get("tickets", [])
        db    = get_db()
        batch = db.batch()
        mapa  = {"new":"aberto","open":"em_andamento","pending":"aguardando",
                 "hold":"aguardando","solved":"resolvido","closed":"resolvido"}
        mprio = {"urgent":"urgente","high":"alta","normal":"normal","low":"baixa"}
        for t in tickets:
            ref = db.collection(COLECAO).document(f"zendesk_{t['id']}")
            batch.set(ref, {
                "id":           f"zendesk_{t['id']}",
                "id_zendesk":   t["id"],
                "assunto":      t.get("subject",""),
                "descricao":    t.get("description",""),
                "status":       mapa.get(t.get("status","open"),"aberto"),
                "prioridade":   mprio.get(t.get("priority","normal"),"normal"),
                "categoria":    "Zendesk/TERMOS",
                "departamento": "",            # Zendesk não tem depto interno
                "tabulacao":    "",
                "criado_em":    t.get("created_at","")[:19].replace("T"," "),
                "atualizado_em":t.get("updated_at","")[:19].replace("T"," "),
                "origem":       "zendesk",
                "comentarios":  [],
                "horas_sla":    24,
            }, merge=True)
        batch.commit()
        return True, len(tickets), f"{len(tickets)} tickets sincronizados"
    except Exception as e:
        return False, 0, str(e)

# ═══════════════════════════════════════════════════════════════════
# RENDERIZAÇÃO
# ═══════════════════════════════════════════════════════════════════
def renderizar_tickets(papel: str, user: dict = None):
    if user is None:
        user = {"role": papel, "nome": "Usuário", "usuario": "user", "departamento": ""}

    todos_geral = listar_tickets()
    # Aplica visibilidade por papel (Regra 5)
    todos = [t for t in todos_geral if ticket_visivel(t, user, papel)]

    # ── Contagens por fila (já com escopo do papel) ───────────────
    ct = {
        "todos":       len(todos),
        "aberto":      sum(1 for t in todos if t.get("status")=="aberto"),
        "em_andamento":sum(1 for t in todos if t.get("status")=="em_andamento"),
        "aguardando":  sum(1 for t in todos if t.get("status")=="aguardando"),
        "resolvido":   sum(1 for t in todos if t.get("status")=="resolvido"),
        "urgente":     sum(1 for t in todos if t.get("prioridade")=="urgente"),
        "zendesk":     sum(1 for t in todos if "zendesk" in t.get("origem","")),
        "vencidos":    sum(1 for t in todos if ticket_vencido_pendente(t)),
    }

    # ── CSS específico do módulo ──────────────────────────────────
    st.markdown(_html("""
    <style>
    .tk-badge { background:#e2e8f0; color:#475569; padding:2px 8px;
        border-radius:10px; font-size:0.72rem; font-weight:700; }
    .tk-badge-red { background:#FEE2E2; color:#991B1B; }
    .tk-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:14px 16px; margin-bottom:8px; border-left:4px solid #C9A84C; }
    .tk-card.vencido { border-left:4px solid #DC2626; box-shadow:0 0 0 1px #FECACA inset; }
    .tk-card-header { display:flex; justify-content:space-between;
        align-items:flex-start; margin-bottom:6px; }
    .tk-card-title { font-size:0.92rem; font-weight:700; color:#2c3e50; }
    .tk-card-meta { font-size:0.75rem; color:#64778d; margin-top:4px; }
    .tk-sla-bar { background:#e8ecf0; border-radius:4px; height:5px; margin:8px 0 4px; }
    .tk-sla-fill { height:5px; border-radius:4px; }
    .tk-sla-text { font-size:0.7rem; color:#64778d; }
    @keyframes tkpiscar { 0%,100%{opacity:1;} 50%{opacity:.20;} }
    .tk-blink { animation: tkpiscar 1s infinite;
        background:#DC2626; color:#fff; padding:2px 10px; border-radius:12px;
        font-size:0.72rem; font-weight:800; display:inline-block; }
    .tk-banner { animation: tkpiscar 1.2s infinite;
        background:#FEE2E2; color:#991B1B; border:2px solid #DC2626;
        border-radius:10px; padding:12px 16px; margin-bottom:14px;
        font-weight:800; font-size:0.95rem; }
    .tk-equipe-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:14px 16px; margin-bottom:8px; border-top:4px solid #C9A84C; }
    </style>
    """), unsafe_allow_html=True)

    # ── Estado ────────────────────────────────────────────────────
    if "tk_fila"    not in st.session_state: st.session_state.tk_fila    = "todos"
    if "tk_detalhe" not in st.session_state: st.session_state.tk_detalhe = None
    if "tk_modo"    not in st.session_state: st.session_state.tk_modo    = "lista"

    # ── Layout: filas + barra vertical + conteúdo ─────────────────
    col_filas, col_sep, col_main = st.columns([1, 0.06, 3.4])

    with col_sep:
        st.markdown(_html(
            '<div style="border-left:2px solid #C9A84C;min-height:680px;'
            'width:1px;margin:0 auto;opacity:.6;"></div>'
        ), unsafe_allow_html=True)

    with col_filas:
        st.markdown("**Filas de Trabalho**")
        filas = [
            ("todos",        "Todos os Tickets", ct["todos"],        False),
            ("aberto",       "Abertos",          ct["aberto"],       False),
            ("em_andamento", "Em Andamento",     ct["em_andamento"], False),
            ("aguardando",   "Aguardando",       ct["aguardando"],   False),
            ("resolvido",    "Resolvidos",       ct["resolvido"],    False),
            ("urgente",      "Urgentes",         ct["urgente"],      ct["urgente"]>0),
            ("vencidos",     "SLA Vencido",      ct["vencidos"],     ct["vencidos"]>0),
            ("zendesk",      "Zendesk / TERMOS", ct["zendesk"],      False),
        ]
        for key, label, qtd, _alerta in filas:
            if st.button(f"{label}  ({qtd})", key=f"fila_{key}",
                         use_container_width=True,
                         type="primary" if st.session_state.tk_fila == key else "secondary"):
                st.session_state.tk_fila    = key
                st.session_state.tk_modo    = "lista"
                st.session_state.tk_detalhe = None
                st.rerun()

        st.markdown("---")
        st.markdown("**Ações**")
        if st.button("➕ Novo Ticket", use_container_width=True, type="primary"):
            st.session_state.tk_modo = "novo"; st.rerun()

        if papel in ("supervisor", "adm"):
            if st.button("👥 Equipe", use_container_width=True):
                st.session_state.tk_modo = "equipe"; st.rerun()

        if papel == "adm":
            if st.button("🔄 Sync Zendesk", use_container_width=True):
                st.session_state.tk_modo = "sync"; st.rerun()

    # ── Conteúdo principal ────────────────────────────────────────
    with col_main:
        modo = st.session_state.tk_modo

        # Banner piscante de SLA vencido (Regra 4) — em qualquer modo
        meus_vencidos   = [t for t in todos if ticket_vencido_pendente(t) and _usuario_atende(t, user)]
        escopo_vencidos = [t for t in todos if ticket_vencido_pendente(t)]
        alerta_lista = meus_vencidos if papel == "operacional" else escopo_vencidos
        if alerta_lista:
            st.markdown(_html(
                f'<div class="tk-banner">⚠️ {len(alerta_lista)} ticket(s) com SLA VENCIDO '
                f'aguardando tratativa! Verifique a fila "SLA Vencido".</div>'
            ), unsafe_allow_html=True)

        # ══ LISTA ════════════════════════════════════════════════
        if modo in ("lista", None):
            fila = st.session_state.tk_fila
            if   fila == "todos":    filtrados = todos
            elif fila == "urgente":  filtrados = [t for t in todos if t.get("prioridade")=="urgente"]
            elif fila == "vencidos": filtrados = [t for t in todos if ticket_vencido_pendente(t)]
            elif fila == "zendesk":  filtrados = [t for t in todos if "zendesk" in t.get("origem","")]
            else:                    filtrados = [t for t in todos if t.get("status")==fila]

            busca = st.text_input("", placeholder="Busca global: ID, assunto, cliente, código, descrição, comentário...",
                                  label_visibility="collapsed", key="tk_busca")
            if busca:
                b = busca.strip().lower()
                filtrados = [t for t in filtrados if b in texto_busca(t)]

            if not filtrados:
                st.info("Nenhum ticket nesta fila.")
            else:
                st.markdown(f"**{len(filtrados)} ticket(s)**")
                for t in filtrados:
                    _render_card(t)
                    id_vis = t.get("id_zendesk", t.get("id","")[:8])
                    # Botão full-width "colado" ao card → abre POPUP
                    if st.button(f"🔍  Abrir  #{id_vis}", key=f"open_{t.get('id','')}",
                                 use_container_width=True):
                        abrir_ticket_popup(t.get("id"), user, papel)

        # ══ DETALHE ══════════════════════════════════════════════
        elif modo == "detalhe":
            _render_detalhe(st.session_state.tk_detalhe, user, papel)

        # ══ NOVO TICKET (Regras 2, 3, 4) ════════════════════════
        elif modo == "novo":
            _render_novo(user)

        # ══ EQUIPE (Regra 5) ═════════════════════════════════════
        elif modo == "equipe":
            _render_equipe(user, papel, todos_geral)

        # ══ SYNC ZENDESK ═════════════════════════════════════════
        elif modo == "sync":
            _render_sync()


# ───────────────────────────────────────────────────────────────────
# COMPONENTES
# ───────────────────────────────────────────────────────────────────
def _render_card(t):
    tid   = t.get("id","")
    sl, spct, svenc = sla_restante(t.get("criado_em",""), t.get("horas_sla",24))
    sv, sbg, sc, _  = STATUS_CFG.get(t.get("status","aberto"),("—","#fff","#000","#000"))
    pv, pbg, pc     = PRIO_CFG.get(t.get("prioridade","normal"),("—","#fff","#000"))
    origem_icon = "🔗" if "zendesk" in t.get("origem","") else "🏠"
    sla_cor = "#DC2626" if svenc else ("#CA8A04" if spct>70 else "#16A34A")
    num_com = len(t.get("comentarios",[]))
    pendente_vencido = ticket_vencido_pendente(t)

    dep    = esc(t.get("departamento") or t.get("categoria") or "—")
    tabul  = esc(t.get("tabulacao") or "")
    titulo = esc(str(t.get("assunto","Sem título"))[:55])
    id_vis = esc(t.get("id_zendesk", tid[:8]))
    cliente = esc(t.get("cliente_nome") or t.get("solicitante_nome", t.get("solicitante","—")))
    cli_cod = t.get("cliente_codigo")
    cliente_txt = f"{cliente}" + (f" ({esc(cli_cod)})" if cli_cod else "")
    criado = esc(t.get("criado_em","")[:16])

    blink    = '<span class="tk-blink">SLA VENCIDO</span>' if pendente_vencido else ""
    meta_tab = f"&nbsp;·&nbsp; 📋 {tabul}" if tabul else ""
    meta_com = f"&nbsp;·&nbsp; 💬 {num_com}" if num_com else ""

    st.markdown(_html(f"""
    <div class="tk-card {'vencido' if pendente_vencido else ''}">
        <div class="tk-card-header">
            <div>
                <div class="tk-card-title">{origem_icon} #{id_vis} — {titulo}</div>
                <div class="tk-card-meta">
                    🏢 {dep}{meta_tab} &nbsp;·&nbsp; 🧾 {cliente_txt} &nbsp;·&nbsp; {criado}{meta_com}
                </div>
            </div>
            <div style="text-align:right;white-space:nowrap;">
                {blink} {pill(sv,sbg,sc)} {pill(pv,pbg,pc)}
            </div>
        </div>
        <div class="tk-sla-bar">
            <div class="tk-sla-fill" style="width:{spct:.0f}%;background:{sla_cor};"></div>
        </div>
        <div class="tk-sla-text">SLA: <b style="color:{sla_cor};">{esc(sl)}</b></div>
    </div>"""), unsafe_allow_html=True)


def _carregar_e_render_detalhe(tid, user, papel, modal=False):
    """Carrega o ticket e renderiza o corpo. Usado pelo popup e pelo modo inline."""
    if not tid:
        if not modal:
            st.session_state.tk_modo = "lista"; st.rerun()
        return
    doc = get_db().collection(COLECAO).document(tid).get()
    if not doc.exists:
        st.error("Ticket não encontrado.")
        return
    _detalhe_corpo(doc.to_dict(), tid, user, papel)


def _render_detalhe(tid, user, papel):
    """Modo inline (fallback quando não há st.dialog)."""
    if st.button("← Voltar para a fila"):
        st.session_state.tk_modo = "lista"; st.session_state.tk_detalhe = None; st.rerun()
    _carregar_e_render_detalhe(tid, user, papel, modal=False)


def _detalhe_corpo(t, tid, user, papel):
    sl, spct, svenc = sla_restante(t.get("criado_em",""), t.get("horas_sla",24))
    sv, sbg, sc, _  = STATUS_CFG.get(t.get("status","aberto"),("—","#fff","#000","#000"))
    pv, pbg, pc     = PRIO_CFG.get(t.get("prioridade","normal"),("—","#fff","#000"))
    sla_cor = "#DC2626" if svenc else ("#CA8A04" if spct>70 else "#16A34A")
    pendente_vencido = ticket_vencido_pendente(t)

    if pendente_vencido:
        st.markdown(_html('<div class="tk-banner">⚠️ Este ticket está com o SLA VENCIDO!</div>'),
                    unsafe_allow_html=True)

    id_vis = esc(t.get("id_zendesk", tid[:8]))
    titulo = esc(t.get("assunto","—"))
    dep    = esc(t.get("departamento") or t.get("categoria") or "—")
    tabul  = esc(t.get("tabulacao") or "—")
    criado = esc(t.get("criado_em","")[:16])
    atend  = t.get("atendentes", [])
    atend_str = esc(", ".join(atend)) if atend else "🌐 Todo o departamento"
    cli_cod  = esc(t.get("cliente_codigo") or "—")
    cli_nome = esc(t.get("cliente_nome") or "—")
    solicit  = esc(t.get("solicitante_nome") or "—")

    st.markdown(_html(f"""
    <div style="background:#fff;border:1px solid #e2e8f0;border-left:6px solid {sla_cor if pendente_vencido else '#C9A84C'};
                border-radius:12px;padding:18px 20px;margin-bottom:16px;">
        <h3 style="margin:0 0 6px;color:#2c3e50;">#{id_vis} — {titulo}</h3>
        <div style="margin-bottom:10px;">
            {pill(sv,sbg,sc)} {pill(pv,pbg,pc)}
            <span style="font-size:0.78rem;color:#64778d;margin-left:8px;">
                🏢 {dep} &nbsp;·&nbsp; 📋 {tabul} &nbsp;·&nbsp; {criado}
            </span>
        </div>
        <div style="font-size:0.8rem;color:#2c3e50;margin-bottom:6px;">
            🧾 Cliente: <b>{cli_nome}</b> &nbsp;·&nbsp; Código: <b>{cli_cod}</b>
        </div>
        <div style="font-size:0.78rem;color:#64778d;margin-bottom:8px;">
            🙋 Solicitante: {solicit} &nbsp;·&nbsp; 👥 Atendentes: {atend_str}
            &nbsp;·&nbsp; ⏱ SLA: <b style="color:{sla_cor};">{esc(sl)}</b>
        </div>
    </div>"""), unsafe_allow_html=True)

    # Descrição — texto puro e seguro
    st.markdown("**📝 Descrição**")
    st.text_area("Descrição", value=str(t.get("descricao") or t.get("assunto","—")),
                 height=140, disabled=True, label_visibility="collapsed",
                 key=f"desc_{tid}")

    # Ações — supervisor/adm (dentro de um FORM para gravar de forma confiável,
    # inclusive dentro do popup — assim mover de fila funciona)
    if papel in ("supervisor","adm"):
        with st.form(f"form_status_{tid}"):
            da1, da2 = st.columns(2)
            novo_status = da1.selectbox("Status", list(STATUS_CFG.keys()),
                index=list(STATUS_CFG.keys()).index(t.get("status","aberto")),
                format_func=lambda k: STATUS_CFG[k][0], key=f"det_status_{tid}")
            nova_prio = da2.selectbox("Prioridade", list(PRIO_CFG.keys()),
                index=list(PRIO_CFG.keys()).index(t.get("prioridade","normal")),
                format_func=lambda k: PRIO_CFG[k][0], key=f"det_prio_{tid}")
            if st.form_submit_button("💾 Salvar alterações", type="primary",
                                     use_container_width=True):
                atualizar_ticket(tid, {"status": novo_status, "prioridade": nova_prio})
                st.success("Atualizado! O ticket foi movido de fila.")
                time.sleep(.5); st.rerun()

    # Histórico
    st.markdown("#### 💬 Histórico")
    comentarios = t.get("comentarios", [])
    if not comentarios:
        st.caption("Nenhum comentário ainda.")
    else:
        for c in comentarios:
            alinha = "right" if c.get("autor") == user.get("nome") else "left"
            bg_com = "#EFF6FF" if alinha == "right" else "#f8f9fa"
            bord   = "#2563EB" if alinha == "right" else "#C9A84C"
            st.markdown(_html(
                f'<div style="text-align:{alinha};margin:6px 0;">'
                f'<div style="display:inline-block;background:{bg_com};'
                f'border-left:3px solid {bord};padding:8px 12px;'
                f'border-radius:8px;max-width:80%;text-align:left;">'
                f'<b style="font-size:0.8rem;">{esc(c.get("autor",""))}</b>'
                f'<span style="color:#64778d;font-size:0.72rem;margin-left:6px;">{esc(c.get("data","")[:16])}</span>'
                f'<br><span style="font-size:0.88rem;">{esc(c.get("texto",""))}</span>'
                f'</div></div>'), unsafe_allow_html=True)

    # Novo comentário
    st.markdown("---")
    with st.form(f"form_com_{tid}", clear_on_submit=True):
        novo_com = st.text_area("Escrever resposta / comentário", height=80,
                                placeholder="Digite a tratativa...")
        cc1, cc2 = st.columns([3,1])
        enviar = cc2.form_submit_button("Enviar", type="primary", use_container_width=True)
        encerrar = False
        if papel in ("supervisor","adm"):
            encerrar = cc1.form_submit_button("✅ Encerrar Ticket")
        if enviar and novo_com.strip():
            adicionar_comentario(tid, user.get("nome",""), novo_com.strip())
            st.success("Enviado!"); time.sleep(.3); st.rerun()
        if encerrar:
            atualizar_ticket(tid, {"status":"resolvido"})
            st.success("Ticket encerrado!"); time.sleep(.5)
            st.session_state.tk_modo = "lista"; st.session_state.tk_detalhe = None; st.rerun()


def _render_novo(user):
    st.markdown("### ➕ Abrir Novo Chamado")
    if st.button("← Voltar"):
        st.session_state.tk_modo = "lista"; st.rerun()

    deps = listar_departamentos()
    dep_nomes = [d["nome"] for d in deps]
    if not dep_nomes:
        st.warning("⚠️ Nenhum departamento cadastrado. Peça ao administrador para criar em "
                   "Configurações → Departamentos.")
        return

    # Regra 2: escolher o DEPARTAMENTO (selectbox FORA do form p/ filtrar tabulações ao vivo)
    dep_sel = st.selectbox("Departamento *", dep_nomes, key="novo_dep")

    # Regra 3: só tabulações do departamento escolhido
    tabs_dep  = [t for t in listar_tabulacoes() if t.get("departamento") == dep_sel]
    tab_nomes = [t["nome"] for t in tabs_dep]
    if tab_nomes:
        tab_sel = st.selectbox("Tabulação *", tab_nomes, key="novo_tab")
        tab_obj = next((t for t in tabs_dep if t["nome"] == tab_sel), None)
    else:
        st.info("Este departamento não tem tabulações. Cadastre em Configurações → Tabulação. "
                "O ticket será aberto sem tabulação (SLA padrão 24h, para todo o departamento).")
        tab_sel, tab_obj = None, None

    # Regra 4: SLA / prioridade derivados da tabulação
    sla_h = int(tab_obj.get("sla_horas", 24)) if tab_obj else 24
    prio_padrao = (tab_obj.get("prioridade","Normal").lower() if tab_obj else "normal")
    if prio_padrao not in PRIO_CFG: prio_padrao = "normal"

    # Prévia do roteamento
    dest = resolver_destinatario_ticket(dep_sel, tab_sel)
    atend_prev = ", ".join(dest["atendentes"]) if dest["atendentes"] else f"todo o depto {dep_sel}"
    st.caption(f"⏱ SLA: **{sla_h}h** · 🎯 Prioridade: **{prio_padrao}** · 👥 Vai para: **{atend_prev}**")

    with st.form("form_novo_ticket", clear_on_submit=True):
        assunto = st.text_input("Assunto *", placeholder="Descreva o problema")

        # Dados do CLIENTE (Solicitante = usuário logado, automático)
        cl1, cl2 = st.columns([1,2])
        cli_codigo = cl1.text_input("Código do cliente *", placeholder="Ex: 10234")
        cli_nome   = cl2.text_input("Nome do cliente *", placeholder="Ex: João da Silva")

        descricao  = st.text_area("Descrição *", height=120)

        st.caption(f"🙋 Solicitante (automático): **{user.get('nome','—')}**  ·  "
                   f"🎯 Prioridade (definida pela tabulação): **{prio_padrao}**")

        if st.form_submit_button("🚀 Abrir Chamado", type="primary", use_container_width=True):
            if not assunto.strip() or not descricao.strip():
                st.error("Preencha Assunto e Descrição.")
            elif not cli_codigo.strip() or not cli_nome.strip():
                st.error("Informe o Código e o Nome do cliente.")
            else:
                novo_id = criar_ticket({
                    "assunto": assunto.strip(), "descricao": descricao.strip(),
                    "departamento": dep_sel,
                    "tabulacao": tab_sel or "",
                    "categoria": dep_sel,             # compat. com telas antigas
                    "subcategoria": tab_sel or "",
                    "prioridade": prio_padrao,        # vem da tabulação (Regra 4)
                    "horas_sla": sla_h,
                    "atendentes": dest["atendentes"], # Regra 2
                    "cliente_codigo": cli_codigo.strip(),
                    "cliente_nome": cli_nome.strip(),
                    "solicitante_nome": user.get("nome",""),   # sempre o logado
                    "aberto_por": user.get("usuario",""),
                })
                st.success(f"✅ Chamado **#{novo_id[:8]}** aberto em **{dep_sel}**! "
                           f"Roteado para: {atend_prev}.")
                st.balloons(); time.sleep(1.5)
                st.session_state.tk_modo = "lista"; st.rerun()


def _render_equipe(user, papel, todos_geral):
    st.markdown("### 👥 Equipe & Tickets do Departamento")
    if st.button("← Voltar"):
        st.session_state.tk_modo = "lista"; st.rerun()

    # adm escolhe o depto; supervisor fica fixo no seu
    if papel == "adm":
        dep_nomes = [d["nome"] for d in listar_departamentos()]
        if not dep_nomes:
            st.info("Nenhum departamento cadastrado."); return
        dep_alvo = st.selectbox("Departamento", dep_nomes, key="eq_dep")
    else:
        dep_alvo = user.get("departamento","") or "—"
        st.markdown(f"Departamento: **{dep_alvo}**")

    usuarios_dep = [u for u in listar_usuarios() if u.get("departamento") == dep_alvo]
    tickets_dep  = [t for t in todos_geral if t.get("departamento") == dep_alvo]

    abertos  = sum(1 for t in tickets_dep if t.get("status") in STATUS_ABERTOS)
    vencidos = sum(1 for t in tickets_dep if ticket_vencido_pendente(t))
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Atendentes", len(usuarios_dep))
    k2.metric("Tickets (total)", len(tickets_dep))
    k3.metric("Pendentes", abertos)
    k4.metric("SLA vencido", vencidos)

    if vencidos:
        st.markdown(_html(f'<div class="tk-banner">⚠️ {vencidos} ticket(s) do departamento '
                          f'com SLA vencido!</div>'), unsafe_allow_html=True)

    st.markdown("---")
    if not usuarios_dep:
        st.info("Nenhum atendente vinculado a este departamento.")
        return

    for u in usuarios_dep:
        uname = u.get("usuario","")
        nome  = u.get("nome", uname)
        meus = [t for t in tickets_dep
                if uname in t.get("atendentes", [])
                or t.get("atribuido_para") in (uname, nome)
                or t.get("aberto_por") == uname]
        m_abertos  = sum(1 for t in meus if t.get("status") in STATUS_ABERTOS)
        m_vencidos = sum(1 for t in meus if ticket_vencido_pendente(t))
        alerta = '<span class="tk-blink">SLA VENCIDO</span>' if m_vencidos else ""
        st.markdown(_html(
            f'<div class="tk-equipe-card">'
            f'<b style="color:#2c3e50;">{esc(nome)}</b> '
            f'<span style="color:#64778d;font-size:0.8rem;">({esc(uname)} · {esc(u.get("role","—"))})</span>'
            f'<span style="float:right;">{alerta}</span><br>'
            f'<span style="font-size:0.8rem;color:#64778d;">'
            f'Total: {len(meus)} &nbsp;·&nbsp; Pendentes: {m_abertos} &nbsp;·&nbsp; '
            f'Vencidos: {m_vencidos}</span>'
            f'</div>'), unsafe_allow_html=True)

        if meus:
            with st.expander(f"Ver / Transferir tickets de {nome} ({len(meus)})"):
                # ── Transferência de responsável (férias/falta) ──
                dest_opts = {x["usuario"]: x.get("nome", x["usuario"])
                             for x in usuarios_dep if x.get("usuario") != uname}
                ids_meus = [t.get("id") for t in meus]
                labels   = {t.get("id"):
                            f"#{t.get('id_zendesk', t.get('id','')[:8])} — {str(t.get('assunto',''))[:40]}"
                            for t in meus}

                st.markdown("**🔁 Transferir responsável**")
                marcar_todos = st.checkbox("Marcar TODOS os tickets deste atendente",
                                           value=True, key=f"all_{uname}")
                if marcar_todos:
                    selec = ids_meus
                    st.caption(f"{len(selec)} ticket(s) selecionado(s).")
                else:
                    selec = st.multiselect("Selecione os tickets",
                                           options=ids_meus,
                                           format_func=lambda x: labels.get(x, x),
                                           key=f"sel_{uname}")

                if dest_opts:
                    novo_resp = st.selectbox(
                        "Novo responsável",
                        options=list(dest_opts.keys()),
                        format_func=lambda x: f"{dest_opts[x]} ({x})",
                        key=f"resp_{uname}")
                    if st.button(f"Transferir {len(selec)} ticket(s) → {dest_opts.get(novo_resp,'')}",
                                 key=f"tr_{uname}", type="primary", use_container_width=True):
                        if selec:
                            qt = transferir_tickets(selec, novo_resp)
                            st.success(f"✅ {qt} ticket(s) transferido(s) para "
                                       f"{dest_opts.get(novo_resp,'')}!")
                            time.sleep(.8); st.rerun()
                        else:
                            st.warning("Nenhum ticket selecionado.")
                else:
                    st.caption("⚠️ Não há outro atendente neste departamento para receber a transferência.")

                st.markdown("---")
                # ── Lista dos tickets ──
                for t in meus:
                    _render_card(t)
                    if st.button(f"🔍 Abrir #{t.get('id_zendesk', t.get('id','')[:8])}",
                                 key=f"eqopen_{uname}_{t.get('id','')}", use_container_width=True):
                        abrir_ticket_popup(t.get("id"), user, papel)


def _render_sync():
    st.markdown("### 🔄 Sincronização Zendesk")
    if st.button("← Voltar"):
        st.session_state.tk_modo = "lista"; st.rerun()

    st.info(f"API configurada: `{ZENDESK_SUBDOMAIN}` · View TERMOS: `{ZENDESK_VIEW_ID}`")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Fase 1 — Sync TERMOS**")
        st.caption("Copia os tickets da view TERMOS para o Firestore")
        if st.button("🔄 Sincronizar Agora", type="primary", use_container_width=True):
            with st.spinner("Consultando Zendesk..."):
                ok, qtd, msg = sync_zendesk()
            (st.success if ok else st.error)((("✅ " if ok else "❌ ") + msg))
    with c2:
        st.markdown("**Fase 3 — Importar Histórico**")
        st.caption("Importa TODOS os tickets antes de desligar a Zendesk")
        st.warning("Execute uma única vez na migração final.")
        if st.button("📦 Importar Tudo", use_container_width=True):
            import requests as req
            url   = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets.json?per_page=100"
            auth  = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
            total = 0
            prog  = st.progress(0, text="Importando...")
            mapa  = {"new":"aberto","open":"em_andamento","pending":"aguardando",
                     "hold":"aguardando","solved":"resolvido","closed":"resolvido"}
            mprio = {"urgent":"urgente","high":"alta","normal":"normal","low":"baixa"}
            while url:
                r = req.get(url, auth=auth, timeout=30)
                if r.status_code != 200: break
                data = r.json(); tickets = data.get("tickets",[])
                db = get_db(); batch = db.batch()
                for t in tickets:
                    ref = db.collection(COLECAO).document(f"zendesk_{t['id']}")
                    batch.set(ref, {
                        "id": f"zendesk_{t['id']}", "id_zendesk": t["id"],
                        "assunto": t.get("subject",""),
                        "status":  mapa.get(t.get("status","open"),"aberto"),
                        "prioridade": mprio.get(t.get("priority","normal"),"normal"),
                        "categoria": "Zendesk/Historico", "departamento":"", "tabulacao":"",
                        "criado_em": t.get("created_at","")[:19].replace("T"," "),
                        "atualizado_em": t.get("updated_at","")[:19].replace("T"," "),
                        "origem": "zendesk_historico", "comentarios": [], "horas_sla": 24,
                    }, merge=True)
                batch.commit(); total += len(tickets)
                prog.progress(min(total/500, 1.0), text=f"{total} importados...")
                url = data.get("next_page")
            prog.empty()
            st.success(f"✅ {total} tickets importados para o Firestore!")

    st.markdown("---")
    st.markdown("#### Tickets no Firestore por origem")
    todos2 = listar_tickets()
    from collections import Counter
    df_orig = pd.DataFrame(
        Counter(t.get("origem","interno") for t in todos2).items(),
        columns=["Origem","Qtd"]
    )
    st.dataframe(df_orig, use_container_width=True, hide_index=True)
