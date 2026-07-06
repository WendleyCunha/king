"""
KingStar — Módulo de Tickets  (v3 + patch de performance)
─────────────────────────────────────────────────────────────────────────────
Correções / novidades desta versão:
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
  [6] ADM pode excluir TODOS os tickets pelo painel Sync Zendesk.
  [7] PERFORMANCE: listar_tickets() agora é cacheada (ttl curto) e toda
      função de escrita (criar/atualizar/comentar/excluir) invalida esse
      cache explicitamente. Antes, listar_tickets() baixava a coleção
      inteira do Firestore em TODO rerun da tela de Tickets (que acontece
      a cada clique — responder, mudar status, abrir popup etc.), e esse
      custo só cresce conforme o histórico de tickets aumenta.
  [8] TICKET FINALIZADO passa a ser somente leitura: não é mais possível
      comentar nem alterar status depois que o autor valida e encerra.
  [9] HISTÓRICO POR CLIENTE: ao abrir um novo chamado, o código do cliente
      é conferido contra os tickets já existentes. Se o cliente já tiver
      chamado(s) anterior(es), eles são listados (com o histórico de
      comentários) tanto na tela de abertura quanto dentro do detalhe do
      ticket — assim vários chamados do mesmo cliente (assuntos diferentes)
      ficam "amarrados" por um histórico único, sem misturar as conversas
      de cada chamado.
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
    "finalizado":   ("Finalizado",   "#F3ECD9","#6B5A2A","#A98C3D"),
    "cancelado":    ("Cancelado",    "#F1F5F9","#475569","#64748B"),
}

PRIO_CFG = {
    "urgente": ("Urgente","#EFD9A0","#6B4E0F"),
    "alta":    ("Alta",   "#FFF7ED","#9A3412"),
    "normal":  ("Normal", "#F0FDF4","#166534"),
    "baixa":   ("Baixa",  "#F1F5F9","#475569"),
}

STATUS_ABERTOS = ("aberto", "em_andamento", "aguardando")  # pendentes p/ SLA

# ── Paleta dourada (sem vermelho) ──────────────────────────────────
GOLD       = "#C9A84C"   # dourado base
GOLD_WARN  = "#D4A12C"   # faltando <30min  (ouro médio)
GOLD_VENC  = "#8A6D1F"   # SLA vencido      (ouro escuro / bronze)
GREEN_OK   = "#16A34A"   # barra saudável

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
    listar_tickets.clear()
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

def sla_estado(t) -> str:
    """Retorna o estado do SLA: 'ok', 'warn' (faltam <=30min) ou 'venc' (estourou).
    Só vale para tickets pendentes; resolvidos/cancelados sempre 'ok'."""
    if t.get("status") not in STATUS_ABERTOS:
        return "ok"
    try:
        dt = datetime.fromisoformat(str(t.get("criado_em","")).replace(" ","T")).replace(tzinfo=BRT)
        limite = dt + timedelta(hours=t.get("horas_sla", 24))
        restante = (limite - datetime.now(BRT)).total_seconds()
    except Exception:
        return "ok"
    if restante <= 0:
        return "venc"
    if restante <= 1800:      # 30 minutos
        return "warn"
    return "ok"

def ticket_vencido_pendente(t) -> bool:
    """True se o SLA estourou E o ticket ainda está pendente."""
    if t.get("status") not in STATUS_ABERTOS:
        return False
    _, _, venc = sla_restante(t.get("criado_em",""), t.get("horas_sla", 24))
    return venc

# ── Classificação em filas MUTUAMENTE EXCLUSIVAS ───────────────────
def _atribuido_a(t, user) -> bool:
    """O ticket caiu para o usuário logado atender (atendente/atribuído)?"""
    uname = user.get("usuario","")
    nome  = user.get("nome","")
    return (uname in t.get("atendentes", [])
            or t.get("atribuido_para") in (uname, nome))

JANELA_VALIDACAO_H = 24   # horas que o autor tem para validar um ticket resolvido

def _horas_desde_atualizacao(t) -> float:
    try:
        dt = datetime.fromisoformat(str(t.get("atualizado_em","")).replace(" ","T")).replace(tzinfo=BRT)
        return (datetime.now(BRT) - dt).total_seconds() / 3600.0
    except Exception:
        return 0.0

def resolvido_em_validacao(t) -> bool:
    """Resolvido há menos de 24h, sem nova interação → ainda aguarda validação do autor."""
    return t.get("status") == "resolvido" and _horas_desde_atualizacao(t) < JANELA_VALIDACAO_H

def classificar_fila(t, user) -> str:
    """Retorna a ÚNICA caixa onde o ticket aparece (ou None se em nenhuma).
    O ticket nunca está em duas caixas — apenas caminha entre elas.

    Precedência:
      1) meus        → tickets ABERTOS pelo usuário logado.
                       Se resolvido: fica em 'meus' por até 24h para o autor VALIDAR;
                       depois disso (ou se finalizado/cancelado) sai de 'meus'.
      2) (a partir daqui, só tickets que caíram para EU atender)
      3) vencidos    → pendente e com SLA estourado.
      4) aberto      → recém-nascido (status 'aberto'), sem interação.
      5) urgente     → já em interação e prioridade urgente.
      6) em_andamento→ já em interação, prioridade normal.
      7) None        → resolvidos/finalizados/cancelados ou que não são meus.
    """
    uname = user.get("usuario","")
    # 1) Tickets que EU abri (acompanhamento / validação)
    if t.get("aberto_por") == uname:
        status = t.get("status")
        if status in ("cancelado", "finalizado"):
            return None
        if status == "resolvido":
            return "meus" if resolvido_em_validacao(t) else None
        return "meus"
    # 2) Daqui pra frente, só o que caiu para eu atender
    if not _atribuido_a(t, user):
        return None
    status = t.get("status")
    if status not in STATUS_ABERTOS:          # resolvido/finalizado/cancelado → fora
        return None
    # 3) SLA estourado tem prioridade
    if ticket_vencido_pendente(t):
        return "vencidos"
    # 4) Recém-nascido, sem interação
    if status == "aberto":
        return "aberto"
    # 5/6) Já em interação (em_andamento/aguardando)
    if t.get("prioridade") == "urgente":
        return "urgente"
    return "em_andamento"

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

# ── Histórico por CLIENTE (Regra nova) ─────────────────────────────
def normalizar_codigo_cliente(cod) -> str:
    """Normaliza o código do cliente para comparação (remove espaços)."""
    return str(cod or "").strip()

def tickets_do_cliente(cliente_codigo: str, excluir_id: str = None) -> list:
    """Busca, entre TODOS os tickets já existentes (qualquer departamento,
    qualquer atendente, qualquer status), todos os que pertencem ao mesmo
    código de cliente. É essa busca que 'amarra' vários chamados do mesmo
    cliente — mesmo com assuntos diferentes — a um histórico único.
    Ordenado do mais recente para o mais antigo."""
    cod = normalizar_codigo_cliente(cliente_codigo)
    if not cod:
        return []
    todos = listar_tickets()
    return sorted(
        [t for t in todos
         if normalizar_codigo_cliente(t.get("cliente_codigo")) == cod
         and t.get("id") != excluir_id],
        key=lambda x: x.get("criado_em",""), reverse=True
    )

def _render_bloco_historico_cliente(lista_tickets, titulo_vazio=None):
    """Renderiza a lista de tickets de um cliente (assunto, status, data)
    com o histórico de comentários de cada um, dentro de um expander."""
    for tc in lista_tickets:
        sv_tc = STATUS_CFG.get(tc.get("status","aberto"), (tc.get("status",""),))[0]
        st.markdown(_html(f"""
        <div style="border-bottom:1px solid #eee;padding:8px 0;">
            <b style="color:#2c3e50;">#{esc(tc.get("id_zendesk", str(tc.get("id",""))[:8]))}</b>
            — {esc(tc.get("assunto","—"))}
            &nbsp;·&nbsp; <span style="color:#6B5A2A;">{esc(sv_tc)}</span>
            &nbsp;·&nbsp; <span style="color:#64778d;">{esc(str(tc.get("criado_em",""))[:16])}</span>
            &nbsp;·&nbsp; 🏢 {esc(tc.get("departamento") or tc.get("categoria") or "—")}
        </div>"""), unsafe_allow_html=True)
        comentarios_tc = tc.get("comentarios", [])
        if comentarios_tc:
            for c in comentarios_tc:
                st.caption(f'💬 **{c.get("autor","")}** ({str(c.get("data",""))[:16]}): {c.get("texto","")}')
        else:
            st.caption("Sem comentários registrados neste chamado.")

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
@st.cache_data(ttl=10, show_spinner=False)
def listar_tickets() -> list:
    """
    OTIMIZADO: cacheada por 10s. Antes, essa função baixava a coleção
    'tickets' INTEIRA do Firestore em todo rerun da tela (que acontece a
    cada clique de responder/mudar status/abrir popup/paginar). O custo
    crescia junto com o histórico de tickets (incluindo os importados do
    Zendesk). Toda função de escrita abaixo chama listar_tickets.clear()
    para não mostrar dado desatualizado por mais que alguns segundos.
    """
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
    listar_tickets.clear()
    return ref.id

def atualizar_ticket(tid: str, dados: dict):
    dados["atualizado_em"] = agora_brt()
    get_db().collection(COLECAO).document(tid).update(dados)
    listar_tickets.clear()

def adicionar_comentario(tid: str, autor: str, texto: str):
    from google.cloud.firestore import ArrayUnion
    get_db().collection(COLECAO).document(tid).update({
        "comentarios": ArrayUnion([{
            "autor": autor, "texto": texto, "data": agora_brt()
        }]),
        "atualizado_em": agora_brt(),
    })
    listar_tickets.clear()

def vincular_ticket_relacionado(tid: str, novo_id: str):
    """Adiciona o id do novo chamado à lista 'tickets_relacionados' de um
    ticket anterior do mesmo cliente (amarração bidirecional, best-effort)."""
    try:
        from google.cloud.firestore import ArrayUnion
        get_db().collection(COLECAO).document(tid).update({
            "tickets_relacionados": ArrayUnion([novo_id]),
        })
    except Exception:
        pass
    listar_tickets.clear()

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
        listar_tickets.clear()
        return True, len(tickets), f"{len(tickets)} tickets sincronizados"
    except Exception as e:
        return False, 0, str(e)

# ── Exclusão total (ADM) ───────────────────────────────────────────
def deletar_todos_tickets() -> int:
    """Deleta TODOS os documentos da coleção de tickets. Retorna a quantidade."""
    db = get_db()
    total = 0
    while True:
        docs = list(db.collection(COLECAO).limit(400).stream())
        if not docs:
            break
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
            total += 1
        batch.commit()
    listar_tickets.clear()
    return total

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
    .tk-badge-red { background:#FBF3D9; color:#8A6D1F; }
    .tk-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:14px 16px; margin-bottom:8px; border-left:4px solid #C9A84C; }
    .tk-card.vencido { border-left:4px solid #8A6D1F; box-shadow:0 0 0 1px #E8D9A6 inset; }
    .tk-card-header { display:flex; justify-content:space-between;
        align-items:flex-start; margin-bottom:6px; }
    .tk-card-title { font-size:0.92rem; font-weight:700; color:#2c3e50; }
    .tk-card-meta { font-size:0.75rem; color:#64778d; margin-top:4px; }
    .tk-sla-bar { background:#e8ecf0; border-radius:4px; height:5px; margin:8px 0 4px; }
    .tk-sla-fill { height:5px; border-radius:4px; }
    .tk-sla-text { font-size:0.7rem; color:#64778d; }
    @keyframes tkpiscar { 0%,100%{opacity:1;} 50%{opacity:.30;} }
    .tk-blink { animation: tkpiscar 1s infinite;
        background:#8A6D1F; color:#fff; padding:2px 10px; border-radius:12px;
        font-size:0.72rem; font-weight:800; display:inline-block; }
    .tk-banner { animation: tkpiscar 1.2s infinite;
        background:#FBF3D9; color:#7A5C12; border:2px solid #8A6D1F;
        border-radius:10px; padding:12px 16px; margin-bottom:14px;
        font-weight:800; font-size:0.95rem; }
    .tk-equipe-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:14px 16px; margin-bottom:8px; border-top:4px solid #C9A84C; }

    /* ── Card clicável (o título é um botão) ── */
    div[class*="st-key-tkcard_"] button {
        text-align:left !important; justify-content:flex-start !important;
        background:#fff !important; border:1px solid #e2e8f0 !important;
        border-bottom:none !important; border-left:4px solid #C9A84C !important;
        border-radius:10px 10px 0 0 !important; color:#2c3e50 !important;
        font-weight:700 !important; font-size:0.92rem !important;
        padding:12px 14px 8px !important; margin-bottom:0 !important;
        transition:background .15s, box-shadow .15s; }
    div[class*="st-key-tkcard_"] button:hover {
        background:#FBF6E6 !important; border-color:#C9A84C !important; }
    div[class*="st-key-tkcard_venc_"] button {
        border-left-color:#8A6D1F !important; animation:tkbordapiscar 1s infinite; }
    div[class*="st-key-tkcard_warn_"] button {
        border-left-color:#D4A12C !important; animation:tkbordapiscarsuave 1.6s infinite; }
    @keyframes tkbordapiscar { 0%,100%{box-shadow:0 0 0 0 rgba(138,109,31,0);} 50%{box-shadow:0 0 0 3px rgba(138,109,31,.35);} }
    @keyframes tkbordapiscarsuave { 0%,100%{box-shadow:0 0 0 0 rgba(212,161,44,0);} 50%{box-shadow:0 0 0 3px rgba(212,161,44,.30);} }
    .tk-cardbody { background:#fff; border:1px solid #e2e8f0; border-top:none;
        border-left:4px solid #C9A84C; border-radius:0 0 10px 10px;
        padding:4px 14px 12px; margin:-10px 0 12px; }
    .tk-cardbody.venc { border-left-color:#8A6D1F; }
    .tk-cardbody.warn { border-left-color:#D4A12C; }
    .tk-cardmeta { font-size:0.75rem; color:#64778d; margin:2px 0 6px; }
    /* badges piscantes do SLA (paleta dourada) */
    .tk-blink-venc { animation:tkpiscar 1s infinite; background:#8A6D1F; color:#fff;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:800; }
    .tk-blink-warn { animation:tkpiscar 1.6s infinite; background:#FBF3D9; color:#7A5C12;
        border:1px solid #D4A12C; padding:1px 8px; border-radius:10px;
        font-size:0.7rem; font-weight:700; }
    .tk-badge-val { background:#F3ECD9; color:#6B5A2A; border:1px solid #A98C3D;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:700; }
    /* Botões "primary" e de formulário em dourado (some o vermelho do tema) */
    button[kind="primary"], button[kind="primaryFormSubmit"],
    button[data-testid="baseButton-primary"], button[data-testid="baseButton-primaryFormSubmit"],
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
        background-color:#C9A84C !important; border-color:#C9A84C !important;
        color:#fff !important; }
    button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover,
    button[data-testid="baseButton-primary"]:hover, button[data-testid="baseButton-primaryFormSubmit"]:hover,
    [data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background-color:#b8973f !important; border-color:#b8973f !important;
        color:#fff !important; }
    /* TODO botão de formulário (Salvar/Enviar/Encerrar) em dourado — robusto p/ qualquer versão */
    [data-testid="stFormSubmitButton"] button {
        background-color:#C9A84C !important; border-color:#C9A84C !important; color:#fff !important; }
    [data-testid="stFormSubmitButton"] button:hover {
        background-color:#b8973f !important; border-color:#b8973f !important; color:#fff !important; }
    /* Foco de campos em dourado (remove a borda vermelha do tema) */
    .stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
        border-color:#C9A84C !important; box-shadow:0 0 0 1px #C9A84C !important; }
    div[data-baseweb="select"] > div:focus-within,
    div[data-baseweb="select"] > div[aria-expanded="true"],
    div[data-baseweb="input"]:focus-within {
        border-color:#C9A84C !important; box-shadow:0 0 0 1px #C9A84C !important; }
    /* cursor/realce do baseweb (caret) que fica vermelho */
    div[data-baseweb="base-input"] input { caret-color:#C9A84C !important; }
    </style>
    """), unsafe_allow_html=True)

    # ── Estado ────────────────────────────────────────────────────
    if "tk_fila"    not in st.session_state: st.session_state.tk_fila    = "meus"
    if "tk_detalhe" not in st.session_state: st.session_state.tk_detalhe = None
    if "tk_modo"    not in st.session_state: st.session_state.tk_modo    = "lista"

    uname = user.get("usuario","")

    # ── Conjuntos das filas (MUTUAMENTE EXCLUSIVOS) ───────────────
    # Cada ticket cai em no máximo uma caixa de trabalho (classificar_fila).
    buckets = {"meus": [], "aberto": [], "em_andamento": [], "urgente": [], "vencidos": []}
    for t in todos:
        f = classificar_fila(t, user)
        if f:
            buckets[f].append(t)
    meus      = buckets["meus"]
    f_abertos = buckets["aberto"]
    f_andam   = buckets["em_andamento"]
    f_urg     = buckets["urgente"]
    f_venc    = buckets["vencidos"]
    f_global  = todos_geral                                          # GLOBAL: de todos

    # ── Largura ajustável dos painéis ─────────────────────────────
    with st.expander("↔️ Ajustar largura dos painéis", expanded=False):
        st.slider("Largura da coluna de filas", 0.6, 2.4,
                  float(st.session_state.get("tk_larg", 1.0)), 0.1, key="tk_larg")
    larg = float(st.session_state.get("tk_larg", 1.0))

    # ── Layout: filas + barra vertical + conteúdo ─────────────────
    col_filas, col_sep, col_main = st.columns([larg, 0.06, 4.0])

    with col_sep:
        st.markdown(_html(
            '<div style="border-left:2px solid #C9A84C;min-height:680px;'
            'width:1px;margin:0 auto;opacity:.6;"></div>'
        ), unsafe_allow_html=True)

    with col_filas:
        st.markdown("**Filas de Trabalho**")
        caixa1 = [
            ("meus",         "📌 Meus tickets", len(meus)),
            ("aberto",       "Abertos",         len(f_abertos)),
            ("em_andamento", "Em andamento",    len(f_andam)),
            ("urgente",      "Urgentes",        len(f_urg)),
            ("vencidos",     "SLA vencidos",    len(f_venc)),
        ]
        for key, label, qtd in caixa1:
            if st.button(f"{label}  ({qtd})", key=f"fila_{key}",
                         use_container_width=True,
                         type="primary" if st.session_state.tk_fila == key else "secondary"):
                st.session_state.tk_fila    = key
                st.session_state.tk_modo    = "lista"
                st.session_state.tk_detalhe = None
                st.rerun()

        # Caixa separada — VISÃO GLOBAL (todos os tickets de todos)
        st.markdown('<div style="border-top:1px dashed #cbd5e1;margin:14px 0 6px;"></div>',
                    unsafe_allow_html=True)
        st.caption("VISÃO GLOBAL")
        if st.button(f"🌐 Todos os tickets  ({len(f_global)})", key="fila_global",
                     use_container_width=True,
                     type="primary" if st.session_state.tk_fila == "global" else "secondary"):
            st.session_state.tk_fila    = "global"
            st.session_state.tk_modo    = "lista"
            st.session_state.tk_detalhe = None
            st.rerun()

        st.markdown("---")
        st.markdown("**Ações**")
        if st.button("➕ Novo Ticket", use_container_width=True, type="primary"):
            st.session_state.tk_modo = "novo"; st.rerun()

        if papel in ("supervisor", "adm"):
            if st.button("📊 Visão Geral da Operação", use_container_width=True,
                         type="primary" if st.session_state.tk_modo == "equipe" else "secondary"):
                st.session_state.tk_modo = "equipe"; st.rerun()

        if papel == "adm":
            if st.button("🔄 Sync Zendesk", use_container_width=True):
                st.session_state.tk_modo = "sync"; st.rerun()

    # ── Conteúdo principal ────────────────────────────────────────
    with col_main:
        modo = st.session_state.tk_modo

        # Banner piscante de SLA vencido — em qualquer modo (paleta dourada)
        if f_venc:
            st.markdown(_html(
                f'<div class="tk-banner">⏳ {len(f_venc)} ticket(s) com SLA ESTOURADO '
                f'aguardando tratativa! Verifique a fila "SLA vencidos".</div>'
            ), unsafe_allow_html=True)

        # ══ LISTA ════════════════════════════════════════════════
        if modo in ("lista", None):
            fila = st.session_state.tk_fila
            mapa_fila = {
                "meus": meus, "aberto": f_abertos, "em_andamento": f_andam,
                "urgente": f_urg, "vencidos": f_venc, "global": f_global,
            }
            filtrados = mapa_fila.get(fila, todos)

            busca = st.text_input("", placeholder="Busca global: ID, assunto, cliente, código, descrição, comentário...",
                                  label_visibility="collapsed", key="tk_busca")
            if busca:
                b = busca.strip().lower()
                filtrados = [t for t in filtrados if b in texto_busca(t)]

            nomes_fila = {k: l for k, l, _ in caixa1}
            nomes_fila["global"] = "🌐 Todos os tickets"
            st.markdown(f"**{nomes_fila.get(fila, fila)} — {len(filtrados)} ticket(s)**")

            if not filtrados:
                st.info("Nenhum ticket nesta fila.")
            else:
                _render_lista_em_grid(filtrados, user, papel, fila)

        # ══ DETALHE ══════════════════════════════════════════════
        elif modo == "detalhe":
            _render_detalhe(st.session_state.tk_detalhe, user, papel)

        # ══ NOVO TICKET (Regras 2, 3, 4) ════════════════════════
        elif modo == "novo":
            _render_novo(user)

        # ══ VISÃO GERAL DA OPERAÇÃO (só supervisor/adm) ══════════
        elif modo == "equipe":
            if papel not in ("supervisor", "adm"):
                st.warning("🔒 Acesso restrito a Supervisores e Administradores.")
                st.session_state.tk_modo = "lista"
            else:
                _render_visao_geral_operacao(user, papel, todos_geral)

        # ══ SYNC ZENDESK ═════════════════════════════════════════
        elif modo == "sync":
            _render_sync()


# ───────────────────────────────────────────────────────────────────
# PAGINAÇÃO (9 tickets por página, em qualquer grid de cards)
# ───────────────────────────────────────────────────────────────────
PAGE_SIZE_CARDS = 9

def _paginar(lista, chave_estado):
    """Recorta a lista na página atual (guardada em session_state) e
    retorna os itens da página + info de navegação."""
    total = len(lista)
    total_paginas = max(1, (total + PAGE_SIZE_CARDS - 1) // PAGE_SIZE_CARDS)
    pag_key = f"tk_pag_{chave_estado}"
    if pag_key not in st.session_state:
        st.session_state[pag_key] = 1
    pag_atual = min(st.session_state[pag_key], total_paginas)
    inicio = (pag_atual - 1) * PAGE_SIZE_CARDS
    fim    = inicio + PAGE_SIZE_CARDS
    return lista[inicio:fim], pag_atual, total_paginas, pag_key, total

def _nav_paginas(pag_atual, total_paginas, pag_key, total):
    """Botões Anterior/Próxima + indicador 'Página X de Y'."""
    if total_paginas <= 1:
        return
    st.markdown('<div style="margin-top:6px;"></div>', unsafe_allow_html=True)
    cnav1, cnav2, cnav3 = st.columns([1, 2, 1])
    with cnav1:
        if st.button("← Anterior", key=f"{pag_key}_prev",
                     disabled=(pag_atual <= 1), use_container_width=True):
            st.session_state[pag_key] = pag_atual - 1
            st.rerun()
    with cnav2:
        st.markdown(
            f'<div style="text-align:center;color:#64778d;font-size:0.85rem;'
            f'padding-top:6px;">Página {pag_atual} de {total_paginas} · {total} ticket(s)</div>',
            unsafe_allow_html=True)
    with cnav3:
        if st.button("Próxima →", key=f"{pag_key}_next",
                     disabled=(pag_atual >= total_paginas), use_container_width=True):
            st.session_state[pag_key] = pag_atual + 1
            st.rerun()


# ───────────────────────────────────────────────────────────────────
# COMPONENTES
# ───────────────────────────────────────────────────────────────────
def _render_lista_em_grid(filtrados, user, papel, fila):
    """Mostra os tickets em CARDS lado a lado (grid de 3 ou 4 colunas),
    com opção de organizar por Motivo (Tabulação), Departamento ou sem
    agrupamento. Vale para qualquer fila e qualquer papel (atendente ou
    supervisor) — não substitui nenhuma função existente, só a forma
    de exibição da lista."""
    ctrl1, ctrl2 = st.columns([2, 1])
    with ctrl1:
        modo_agrupar = st.selectbox(
            "🗂️ Organizar por",
            ["Motivo (Tabulação)", "Departamento", "Sem agrupamento"],
            index=0, key=f"tk_agrupar_{fila}"
        )
    with ctrl2:
        n_cols = st.selectbox(
            "🔳 Cards por linha", [3, 4], index=0, key=f"tk_ncols_{fila}"
        )

    from collections import defaultdict
    grupos = defaultdict(list)
    if modo_agrupar == "Departamento":
        for t in filtrados:
            grupos[t.get("departamento") or t.get("categoria") or "—"].append(t)
    elif modo_agrupar == "Motivo (Tabulação)":
        for t in filtrados:
            grupos[t.get("tabulacao") or "Sem tabulação"].append(t)
    else:
        grupos["__todos__"] = filtrados

    for chave in sorted(grupos.keys()):
        lst = grupos[chave]
        n_venc = sum(1 for t in lst if ticket_vencido_pendente(t))
        extra = (f' · <span style="color:#8A6D1F;font-weight:700;">⏳ {n_venc} com prazo '
                 f'estourado</span>') if n_venc else ""

        if modo_agrupar != "Sem agrupamento":
            icone = "📋" if modo_agrupar == "Motivo (Tabulação)" else "🏢"
            st.markdown(_html(
                f'<div style="margin:14px 0 6px;font-weight:700;color:#2c3e50;">'
                f'{icone} {esc(chave)} <span style="color:#64778d;font-weight:500;">— '
                f'{len(lst)} ticket(s)</span>{extra}</div>'), unsafe_allow_html=True)

        pagina_itens, pag_atual, total_paginas, pag_key, total = _paginar(
            lst, f"lista_{fila}_{chave}"
        )
        for i in range(0, len(pagina_itens), n_cols):
            cols_grid = st.columns(n_cols)
            for j, t in enumerate(pagina_itens[i:i + n_cols]):
                with cols_grid[j]:
                    _render_card_clicavel(t, user, papel)
        _nav_paginas(pag_atual, total_paginas, pag_key, total)


def _render_card_clicavel(t, user, papel):
    """Card cujo título é um BOTÃO (clica em cima → abre o popup).
    Borda/realce piscam conforme o SLA (suave a 30min, forte se vencido)
    e a barra de tempo (verde/âmbar/vermelha) é mantida."""
    tid    = t.get("id","")
    estado = sla_estado(t)                       # ok | warn | venc
    sl, spct, svenc = sla_restante(t.get("criado_em",""), t.get("horas_sla",24))
    sv = STATUS_CFG.get(t.get("status","aberto"), ("—",))[0]
    pv = PRIO_CFG.get(t.get("prioridade","normal"), ("—",))[0]
    icon = "🔗" if "zendesk" in t.get("origem","") else "🏠"
    idv  = t.get("id_zendesk", tid[:8])
    titulo = str(t.get("assunto","Sem título"))[:60]
    dep    = t.get("departamento") or t.get("categoria") or "—"
    cliente = t.get("cliente_nome") or t.get("solicitante_nome") or "—"
    cli_cod = t.get("cliente_codigo")
    cliente_txt = cliente + (f" ({cli_cod})" if cli_cod else "")
    num_com = len(t.get("comentarios", []))

    # Cor da barra de tempo (mantém o verde quando saudável)
    if   estado == "venc": barra = GOLD_VENC
    elif estado == "warn": barra = GOLD_WARN
    elif spct > 70:        barra = "#CA8A04"
    else:                  barra = "#16A34A"

    # Badge piscante por estado
    if estado == "venc":
        badge = '<span class="tk-blink-venc">⛔ SLA VENCIDO</span>'
    elif estado == "warn":
        badge = '<span class="tk-blink-warn">⏰ Faltam &lt; 30min</span>'
    else:
        badge = ""

    # Aguardando validação do autor (resolvido, dentro da janela de 24h)
    if t.get("status") == "resolvido" and t.get("aberto_por") == user.get("usuario") \
            and resolvido_em_validacao(t):
        badge += ' <span class="tk-badge-val">✔ valide este chamado</span>'

    # Título clicável = abre o popup
    if st.button(f"{icon}  #{idv} — {titulo}", key=f"tkcard_{estado}_{tid}",
                 use_container_width=True):
        abrir_ticket_popup(tid, user, papel)

    meta_com = f" &nbsp;·&nbsp; 💬 {num_com}" if num_com else ""
    st.markdown(_html(f"""
    <div class="tk-cardbody {estado if estado!='ok' else ''}">
        <div class="tk-cardmeta">
            🏢 {esc(dep)} &nbsp;·&nbsp; 🧾 {esc(cliente_txt)} &nbsp;·&nbsp;
            <b>{esc(sv)}</b> / {esc(pv)}{meta_com} &nbsp; {badge}
        </div>
        <div class="tk-sla-bar">
            <div class="tk-sla-fill" style="width:{spct:.0f}%;background:{barra};"></div>
        </div>
        <div class="tk-sla-text">SLA: <b style="color:{barra};">{esc(sl)}</b></div>
    </div>"""), unsafe_allow_html=True)


def _render_card(t):
    tid   = t.get("id","")
    sl, spct, svenc = sla_restante(t.get("criado_em",""), t.get("horas_sla",24))
    sv, sbg, sc, _  = STATUS_CFG.get(t.get("status","aberto"),("—","#fff","#000","#000"))
    pv, pbg, pc     = PRIO_CFG.get(t.get("prioridade","normal"),("—","#fff","#000"))
    origem_icon = "🔗" if "zendesk" in t.get("origem","") else "🏠"
    sla_cor = GOLD_VENC if svenc else ("#CA8A04" if spct>70 else GREEN_OK)
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
    sla_cor = GOLD_VENC if svenc else ("#CA8A04" if spct>70 else GREEN_OK)
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

    # ── Histórico do CLIENTE — outros chamados com o mesmo código ──
    # Mesmo cliente pode ter vários tickets (assuntos diferentes); todos
    # ficam amarrados aqui via cliente_codigo, sem misturar as conversas.
    relacionados = tickets_do_cliente(t.get("cliente_codigo"), excluir_id=tid)
    if relacionados:
        abertos_rel = sum(1 for x in relacionados if x.get("status") in STATUS_ABERTOS)
        with st.expander(
            f"🗂 Histórico do cliente — {len(relacionados)} outro(s) chamado(s)"
            + (f" ({abertos_rel} em aberto)" if abertos_rel else ""),
            expanded=False
        ):
            _render_bloco_historico_cliente(relacionados)

    # Descrição — texto puro e seguro
    st.markdown("**📝 Descrição**")
    st.text_area("Descrição", value=str(t.get("descricao") or t.get("assunto","—")),
                 height=140, disabled=True, label_visibility="collapsed",
                 key=f"desc_{tid}")

    status_atual = t.get("status", "aberto")
    terminal     = status_atual in ("finalizado", "cancelado")
    finalizado   = status_atual == "finalizado"
    pode_agir    = (papel in ("supervisor", "adm")) or _atribuido_a(t, user)
    # Status editável só pelo atendente/supervisor/adm e enquanto não terminal.
    # A PRIORIDADE nunca é editável aqui (vem do cadastro da tabulação).
    status_edit  = pode_agir and not terminal
    # Status que o atendente pode definir (sem 'finalizado' — isso é da validação do autor)
    STATUS_OPC   = [k for k in STATUS_CFG.keys() if k != "finalizado"]

    # ── Tratativa: Status + Prioridade + resposta + Enviar (tudo junto) ──
    # Ticket FINALIZADO é somente leitura: não pode comentar nem mudar status.
    st.markdown("---")
    if finalizado:
        st.info("🔒 Este chamado está **finalizado** e foi encerrado definitivamente. "
                 "Não é mais possível comentar ou alterar o status — consulte o "
                 "histórico abaixo.")
    else:
        with st.form(f"form_trat_{tid}", clear_on_submit=True):
            cs1, cs2 = st.columns(2)
            with cs1:
                if status_edit:
                    idx = STATUS_OPC.index(status_atual) if status_atual in STATUS_OPC else 0
                    novo_status = st.selectbox("Status", STATUS_OPC, index=idx,
                                               format_func=lambda k: STATUS_CFG[k][0],
                                               key=f"det_status_{tid}")
                else:
                    novo_status = status_atual
                    st.markdown("**Status**")
                    st.markdown(pill(sv, sbg, sc), unsafe_allow_html=True)
            with cs2:
                st.markdown("**Prioridade**")
                st.markdown(
                    pill(pv, pbg, pc) +
                    ' <span style="font-size:0.7rem;color:#94a3b8;">(definida na tabulação)</span>',
                    unsafe_allow_html=True)

            novo_com = st.text_area("Escrever resposta / comentário", height=90,
                                    placeholder="Digite a tratativa...", key=f"com_{tid}")
            enviar = st.form_submit_button("Enviar", type="primary", use_container_width=True)

            if enviar:
                updates = {}
                if status_edit and novo_status != status_atual:
                    updates["status"] = novo_status
                tem_com = bool(novo_com and novo_com.strip())
                if tem_com:
                    adicionar_comentario(tid, user.get("nome",""), novo_com.strip())
                if updates:
                    atualizar_ticket(tid, updates)
                if tem_com or updates:
                    msg = "Enviado!"
                    if updates.get("status") == "resolvido":
                        msg = ("✅ Ticket marcado como Resolvido! Saiu das suas tratativas e "
                               "permanece em 'Todos os tickets'.")
                    st.success(msg); time.sleep(.5)
                    if updates.get("status") in ("resolvido", "cancelado"):
                        st.session_state.tk_modo = "lista"; st.session_state.tk_detalhe = None
                    st.rerun()
                else:
                    st.warning("Escreva uma resposta ou altere o status antes de enviar.")

    # ── Histórico dos comentários ──
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

    # ── Validação do AUTOR (no FIM do layout) ──
    # Quando resolvido, quem abriu valida (encerra) ou reabre.
    # (Ticket já finalizado não passa por aqui — status_atual != "resolvido".)
    if status_atual == "resolvido" and t.get("aberto_por") == user.get("usuario"):
        st.markdown("---")
        st.markdown(_html(
            '<div style="background:#F3ECD9;border:1px solid #A98C3D;border-radius:10px;'
            'padding:12px 14px;margin:6px 0 10px;color:#6B5A2A;font-weight:600;">'
            '✔ Este chamado foi marcado como <b>Resolvido</b>. Valide para encerrar '
            'definitivamente, ou reabra se não foi resolvido.<br>'
            '<span style="font-weight:500;font-size:0.82rem;">Sem ação em 24h, ele é '
            'encerrado automaticamente.</span></div>'), unsafe_allow_html=True)
        cva, cvb = st.columns(2)
        if cva.button("✅ Validar e encerrar", key=f"val_{tid}", type="primary",
                      use_container_width=True):
            atualizar_ticket(tid, {"status": "finalizado"})
            st.success("Chamado encerrado!"); time.sleep(.5)
            st.session_state.tk_modo = "lista"; st.session_state.tk_detalhe = None; st.rerun()
        if cvb.button("↩️ Reabrir chamado", key=f"reab_{tid}", use_container_width=True):
            atualizar_ticket(tid, {"status": "em_andamento"})
            st.success("Chamado reaberto!"); time.sleep(.5); st.rerun()


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

    # ── Regra nova: CÓDIGO DO CLIENTE fora do form, para validar/buscar
    # histórico ao vivo (mesmo padrão do departamento/tabulação acima).
    st.markdown("**Dados do cliente**")
    cl1, cl2 = st.columns([1, 2])
    cli_codigo = cl1.text_input("Código do cliente *", placeholder="Ex: 10234", key="novo_cli_codigo")
    cli_nome   = cl2.text_input("Nome do cliente *", placeholder="Ex: João da Silva", key="novo_cli_nome")

    cod_norm = normalizar_codigo_cliente(cli_codigo)
    tickets_cliente = tickets_do_cliente(cod_norm) if cod_norm else []
    if tickets_cliente:
        abertos_cli = sum(1 for x in tickets_cliente if x.get("status") in STATUS_ABERTOS)
        st.markdown(_html(f"""
        <div class="tk-banner">
            🗂 Este código de cliente já possui <b>{len(tickets_cliente)}</b> chamado(s)
            anterior(es){f" ({abertos_cli} em aberto)" if abertos_cli else ""}.
            O novo chamado será aberto separadamente, com <b>assunto próprio</b>, mas ficará
            <b>amarrado ao mesmo histórico do cliente</b> (visível dentro do ticket).
        </div>"""), unsafe_allow_html=True)
        with st.expander(f"📜 Ver histórico deste cliente ({len(tickets_cliente)} chamado(s))"):
            _render_bloco_historico_cliente(tickets_cliente)
    elif cod_norm:
        st.caption("✅ Nenhum chamado anterior encontrado para este código de cliente — será o primeiro dele.")

    with st.form("form_novo_ticket", clear_on_submit=True):
        assunto = st.text_input("Assunto *", placeholder="Descreva o problema")
        descricao  = st.text_area("Descrição *", height=120)

        st.caption(f"🙋 Solicitante (automático): **{user.get('nome','—')}**  ·  "
                   f"🎯 Prioridade (definida pela tabulação): **{prio_padrao}**")

        if st.form_submit_button("🚀 Abrir Chamado", type="primary", use_container_width=True):
            if not assunto.strip() or not descricao.strip():
                st.error("Preencha Assunto e Descrição.")
            elif not cod_norm or not cli_nome.strip():
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
                    "cliente_codigo": cod_norm,
                    "cliente_nome": cli_nome.strip(),
                    "solicitante_nome": user.get("nome",""),   # sempre o logado
                    "aberto_por": user.get("usuario",""),
                    # Amarração com o histórico do cliente (snapshot no momento
                    # da abertura; a exibição em tela sempre recalcula ao vivo
                    # via tickets_do_cliente, então continua correta mesmo se
                    # novos tickets surgirem depois).
                    "tickets_relacionados": [x.get("id") for x in tickets_cliente],
                })
                # Amarra de volta: cada ticket anterior do cliente passa a
                # referenciar este novo também (histórico bidirecional).
                for tc in tickets_cliente:
                    if tc.get("id"):
                        vincular_ticket_relacionado(tc["id"], novo_id)
                aviso_hist = (f" 🗂 Amarrado ao histórico de {len(tickets_cliente)} "
                              f"chamado(s) anterior(es) deste cliente."
                              if tickets_cliente else "")
                st.success(f"✅ Chamado **#{novo_id[:8]}** aberto em **{dep_sel}**! "
                           f"Roteado para: {atend_prev}.{aviso_hist}")
                st.balloons(); time.sleep(1.5)
                st.session_state.tk_modo = "lista"; st.rerun()


# ═══════════════════════════════════════════════════════════════════
# VISÃO GERAL DA OPERAÇÃO — bloco exclusivo de Supervisor/ADM.
# Código totalmente separado da experiência do atendente comum.
# Estrutura em ABAS:
#   📊 Dashboard       → KPIs gerais, top atendente, motivo mais acionado
#   👥 Por Atendente   → produtividade individual + transferência de tickets
#   📋 Por Motivo      → volume por tabulação + quem está com cada uma
#   ⏳ SLA Perdido      → ranking de quem mais perdeu SLA e detalhe dos casos
#   📥 Exportar         → relatório completo em Excel (.xlsx, 3 abas)
# Filtros de Atendente e Motivo no topo valem para TODAS as abas.
# ═══════════════════════════════════════════════════════════════════

def sla_foi_perdido(t) -> bool:
    """Define se o SLA deste ticket foi (ou está) estourado, mesmo que o
    ticket já tenha sido resolvido/finalizado/cancelado:
      - Pendente  → usa o relógio atual (ticket_vencido_pendente).
      - Encerrado → compara o tempo entre abertura e a última atualização
        registrada (proxy de quando foi tratado) contra o SLA da tabulação.
    Isso permite contabilizar perdas de SLA HISTÓRICAS no relatório, não só
    as que ainda estão pendentes agora."""
    if t.get("status") in STATUS_ABERTOS:
        return ticket_vencido_pendente(t)
    try:
        criado = datetime.fromisoformat(str(t.get("criado_em","")).replace(" ","T")).replace(tzinfo=BRT)
        atualz = datetime.fromisoformat(str(t.get("atualizado_em","")).replace(" ","T")).replace(tzinfo=BRT)
        horas_decorridas = (atualz - criado).total_seconds() / 3600.0
        return horas_decorridas > t.get("horas_sla", 24)
    except Exception:
        return False


def _gerar_excel_relatorio(tickets: list, nomes_users: dict) -> bytes:
    """Gera o relatório completo em Excel com 3 abas: Por Atendente,
    Por Motivo e Detalhe Completo."""
    import pandas as pd
    from io import BytesIO
    from collections import defaultdict

    # ── Detalhe completo ──
    linhas = []
    for t in tickets:
        ats = t.get("atendentes") or ([t.get("atribuido_para")] if t.get("atribuido_para") else [])
        atend_nomes = ", ".join(nomes_users.get(a, a) for a in ats) if ats else "— ninguém —"
        linhas.append({
            "ID":                  t.get("id_zendesk", str(t.get("id",""))[:8]),
            "Assunto":             t.get("assunto",""),
            "Departamento":        t.get("departamento",""),
            "Motivo (Tabulação)":  t.get("tabulacao") or "Sem tabulação",
            "Status":              STATUS_CFG.get(t.get("status",""), (t.get("status",""),))[0],
            "Prioridade":          PRIO_CFG.get(t.get("prioridade",""), (t.get("prioridade",""),))[0],
            "Atendente(s)":        atend_nomes,
            "Aberto por":          t.get("aberto_por",""),
            "Cliente":             t.get("cliente_nome",""),
            "Criado em":           t.get("criado_em",""),
            "Atualizado em":       t.get("atualizado_em",""),
            "SLA (h)":             t.get("horas_sla",24),
            "SLA Perdido":         "Sim" if sla_foi_perdido(t) else "Não",
        })
    df_detalhe = pd.DataFrame(linhas)

    # ── Resumo por atendente ──
    resumo_at = defaultdict(lambda: {"total":0, "pendentes":0, "sla_perdido":0})
    for t in tickets:
        ats = t.get("atendentes") or ([t.get("atribuido_para")] if t.get("atribuido_para") else [])
        if not ats:
            ats = ["— ninguém —"]
        for a in ats:
            nome = nomes_users.get(a, a)
            resumo_at[nome]["total"] += 1
            if t.get("status") in STATUS_ABERTOS:
                resumo_at[nome]["pendentes"] += 1
            if sla_foi_perdido(t):
                resumo_at[nome]["sla_perdido"] += 1
    df_atend = pd.DataFrame([
        {"Atendente": k, "Total de Tickets": v["total"], "Pendentes": v["pendentes"],
         "SLA Perdido": v["sla_perdido"]}
        for k, v in sorted(resumo_at.items(), key=lambda x: -x[1]["total"])
    ])

    # ── Resumo por motivo ──
    resumo_mot = defaultdict(lambda: {"total":0, "pendentes":0, "sla_perdido":0})
    for t in tickets:
        mot = t.get("tabulacao") or "Sem tabulação"
        resumo_mot[mot]["total"] += 1
        if t.get("status") in STATUS_ABERTOS:
            resumo_mot[mot]["pendentes"] += 1
        if sla_foi_perdido(t):
            resumo_mot[mot]["sla_perdido"] += 1
    df_motivo = pd.DataFrame([
        {"Motivo": k, "Total de Tickets": v["total"], "Pendentes": v["pendentes"],
         "SLA Perdido": v["sla_perdido"]}
        for k, v in sorted(resumo_mot.items(), key=lambda x: -x[1]["total"])
    ])

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        for nome_aba, df in [("Por Atendente", df_atend), ("Por Motivo", df_motivo),
                              ("Detalhe Completo", df_detalhe)]:
            df.to_excel(writer, index=False, sheet_name=nome_aba)
            ws = writer.sheets[nome_aba]
            for i, col in enumerate(df.columns):
                tam = df[col].astype(str).map(len).max() if len(df) else 0
                largura = max(tam, len(col)) + 2
                ws.set_column(i, i, largura)
    buf.seek(0)
    return buf.getvalue()


def _render_visao_geral_operacao(user, papel, todos_geral):
    st.markdown("### 📊 Visão Geral da Operação")
    if st.button("← Voltar"):
        st.session_state.tk_modo = "lista"; st.rerun()

    # adm escolhe o depto; supervisor fica fixo no seu próprio departamento
    if papel == "adm":
        dep_nomes = [d["nome"] for d in listar_departamentos()]
        if not dep_nomes:
            st.info("Nenhum departamento cadastrado."); return
        dep_alvo = st.selectbox("Departamento", dep_nomes, key="vg_dep")
    else:
        dep_alvo = user.get("departamento","") or "—"
        st.markdown(f"Departamento: **{dep_alvo}**")

    usuarios_dep = [u for u in listar_usuarios() if u.get("departamento") == dep_alvo]
    tickets_dep  = [t for t in todos_geral if t.get("departamento") == dep_alvo]
    nomes_users  = {u.get("usuario",""): u.get("nome", u.get("usuario","")) for u in usuarios_dep}

    if not usuarios_dep:
        st.info("Nenhum atendente vinculado a este departamento.")
        return

    # ── Filtros globais — valem para todas as abas abaixo ─────────
    st.markdown("---")
    fc1, fc2, fc3 = st.columns([1, 1, 1.2])
    with fc1:
        op_sel = st.multiselect(
            "👤 Filtrar por atendente",
            options=sorted(nomes_users.values()),
            key="vg_filtro_operador",
        )
    motivos_disponiveis = sorted({(t.get("tabulacao") or "Sem tabulação") for t in tickets_dep})
    with fc2:
        mot_sel = st.multiselect(
            "📋 Filtrar por motivo (tabulação)",
            options=motivos_disponiveis,
            key="vg_filtro_motivo",
        )

    hoje = datetime.now(BRT).date()
    primeiro_dia_mes = hoje.replace(day=1)
    with fc3:
        periodo = st.date_input(
            "📅 Período (Criado em) — para fechamento mensal",
            value=(primeiro_dia_mes, hoje),
            format="DD/MM/YYYY",
            key="vg_filtro_periodo",
        )
    # st.date_input em modo intervalo só fecha o tuple (ini, fim) quando o
    # usuário escolhe as DUAS datas; enquanto isso, mantém só uma — nesse
    # caso ainda não filtramos por data.
    if isinstance(periodo, (tuple, list)) and len(periodo) == 2:
        data_ini, data_fim = periodo
    else:
        data_ini, data_fim = None, None

    def _data_ticket(t):
        try:
            return datetime.fromisoformat(
                str(t.get("criado_em", "")).replace(" ", "T")
            ).date()
        except Exception:
            return None

    def _passa_filtro(t):
        if mot_sel and (t.get("tabulacao") or "Sem tabulação") not in mot_sel:
            return False
        if op_sel:
            ats = t.get("atendentes") or ([t.get("atribuido_para")] if t.get("atribuido_para") else [])
            nomes_at = [nomes_users.get(a, a) for a in ats]
            if not any(n in op_sel for n in nomes_at):
                return False
        if data_ini and data_fim:
            d = _data_ticket(t)
            if d is None or not (data_ini <= d <= data_fim):
                return False
        return True

    tickets_filtrados = [t for t in tickets_dep if _passa_filtro(t)]
    filtros_ativos = op_sel or mot_sel or (data_ini and data_fim)
    if filtros_ativos:
        periodo_txt = f" · período {data_ini.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}" \
                      if (data_ini and data_fim) else ""
        st.caption(f"🔎 Filtro ativo{periodo_txt} — exibindo {len(tickets_filtrados)} "
                   f"de {len(tickets_dep)} ticket(s).")

    aba_dash, aba_atend, aba_motivo, aba_sla, aba_export = st.tabs(
        ["📊 Dashboard", "👥 Por Atendente", "📋 Por Motivo", "⏳ SLA Perdido", "📥 Exportar"]
    )

    with aba_dash:
        _aba_dashboard(tickets_filtrados, usuarios_dep, nomes_users)

    with aba_atend:
        _aba_por_atendente(tickets_filtrados, usuarios_dep, user, papel)

    with aba_motivo:
        _aba_por_motivo(tickets_filtrados, dep_alvo, nomes_users)

    with aba_sla:
        _aba_sla_perdido(tickets_filtrados, nomes_users, user, papel)

    with aba_export:
        _aba_exportar(tickets_filtrados, nomes_users, dep_alvo, data_ini, data_fim)


# ── ABA: 📊 Dashboard ───────────────────────────────────────────────
def _aba_dashboard(tickets: list, usuarios_dep: list, nomes_users: dict):
    from collections import Counter

    total      = len(tickets)
    pendentes  = sum(1 for t in tickets if t.get("status") in STATUS_ABERTOS)
    sla_perd   = sum(1 for t in tickets if sla_foi_perdido(t))
    pct_cumprido = ((total - sla_perd) / total * 100) if total else 100.0

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(f'<div class="kpi-card gold"><div class="kpi-label">Total de Tickets</div>'
                f'<div class="kpi-value">{total}</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card blue"><div class="kpi-label">Pendentes</div>'
                f'<div class="kpi-value">{pendentes}</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card red"><div class="kpi-label">SLA Perdido</div>'
                f'<div class="kpi-value">{sla_perd}</div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="kpi-card green"><div class="kpi-label">SLA Cumprido</div>'
                f'<div class="kpi-value">{pct_cumprido:.0f}%</div></div>', unsafe_allow_html=True)

    st.markdown("")

    # Contagem por atendente (produtividade)
    cont_at = Counter()
    for t in tickets:
        ats = t.get("atendentes") or ([t.get("atribuido_para")] if t.get("atribuido_para") else [])
        if not ats: ats = ["— ninguém —"]
        for a in ats:
            cont_at[nomes_users.get(a, a)] += 1

    # Contagem por motivo
    cont_mot = Counter(t.get("tabulacao") or "Sem tabulação" for t in tickets)

    cmc1, cmc2 = st.columns(2)
    with cmc1:
        st.markdown("##### 🏆 Quem mais atendeu")
        if cont_at:
            top_nome, top_qtd = cont_at.most_common(1)[0]
            st.markdown(f'<div class="kpi-card gold"><div class="kpi-label">Top Atendente</div>'
                        f'<div class="kpi-value" style="font-size:1.3rem;">{esc(top_nome)}</div>'
                        f'<div class="kpi-sub">{top_qtd} ticket(s)</div></div>', unsafe_allow_html=True)
            st.markdown("")
            df_at = pd.DataFrame(cont_at.most_common(), columns=["Atendente", "Tickets"])
            st.dataframe(df_at, use_container_width=True, hide_index=True)
        else:
            st.caption("Sem dados.")
    with cmc2:
        st.markdown("##### 📋 Motivo mais acionado")
        if cont_mot:
            top_mot, top_qtd_mot = cont_mot.most_common(1)[0]
            st.markdown(f'<div class="kpi-card gold"><div class="kpi-label">Top Motivo</div>'
                        f'<div class="kpi-value" style="font-size:1.3rem;">{esc(top_mot)}</div>'
                        f'<div class="kpi-sub">{top_qtd_mot} ticket(s)</div></div>', unsafe_allow_html=True)
            st.markdown("")
            df_mot = pd.DataFrame(cont_mot.most_common(), columns=["Motivo", "Tickets"])
            st.dataframe(df_mot, use_container_width=True, hide_index=True)
        else:
            st.caption("Sem dados.")


# ── ABA: 👥 Por Atendente (produtividade + transferência) ───────────
def _aba_por_atendente(tickets: list, usuarios_dep: list, user, papel):
    for u in usuarios_dep:
        uname = u.get("usuario","")
        nome  = u.get("nome", uname)
        meus = [t for t in tickets
                if uname in t.get("atendentes", [])
                or t.get("atribuido_para") in (uname, nome)
                or t.get("aberto_por") == uname]
        m_abertos    = sum(1 for t in meus if t.get("status") in STATUS_ABERTOS)
        m_sla_perd   = sum(1 for t in meus if sla_foi_perdido(t))
        alerta = f'<span class="tk-blink">⏳ {m_sla_perd} SLA perdido</span>' if m_sla_perd else ""
        st.markdown(_html(
            f'<div class="tk-equipe-card">'
            f'<b style="color:#2c3e50;">{esc(nome)}</b> '
            f'<span style="color:#64778d;font-size:0.8rem;">({esc(uname)} · {esc(u.get("role","—"))})</span>'
            f'<span style="float:right;">{alerta}</span><br>'
            f'<span style="font-size:0.8rem;color:#64778d;">'
            f'Total: {len(meus)} &nbsp;·&nbsp; Pendentes: {m_abertos} &nbsp;·&nbsp; '
            f'SLA perdido: {m_sla_perd}</span>'
            f'</div>'), unsafe_allow_html=True)

        if meus:
            meus_transferiveis = [t for t in meus if t.get("status") in STATUS_ABERTOS]
            with st.expander(f"Ver / Transferir tickets de {nome} ({len(meus)})"):
                # ── Transferência de responsável (férias/falta) ──
                # Só tickets ainda ABERTOS entram na transferência.
                # Tickets finalizados/cancelados são histórico e não são tratativa.
                dest_opts = {x["usuario"]: x.get("nome", x["usuario"])
                             for x in usuarios_dep if x.get("usuario") != uname}
                ids_meus = [t.get("id") for t in meus_transferiveis]
                labels   = {t.get("id"):
                            f"#{t.get('id_zendesk', t.get('id','')[:8])} — {str(t.get('assunto',''))[:40]}"
                            for t in meus_transferiveis}

                st.markdown("**🔁 Transferir responsável**")
                if not meus_transferiveis:
                    st.caption("✅ Nenhum ticket em aberto deste atendente — nada para transferir "
                               "(os finalizados/cancelados não entram na transferência).")
                else:
                    marcar_todos = st.checkbox("Marcar TODOS os tickets em aberto deste atendente",
                                               value=True, key=f"all_{uname}")
                    if marcar_todos:
                        selec = ids_meus
                        st.caption(f"{len(selec)} ticket(s) em aberto selecionado(s).")
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
                # ── Lista dos tickets (grid + paginação, igual à fila do atendente) ──
                n_cols_eq = st.selectbox(
                    "🔳 Cards por linha", [3, 4], index=0, key=f"eq_ncols_{uname}"
                )
                pagina_itens, pag_atual, total_paginas, pag_key, total = _paginar(
                    meus, f"eq_{uname}"
                )
                for i in range(0, len(pagina_itens), n_cols_eq):
                    cols_grid = st.columns(n_cols_eq)
                    for j, t in enumerate(pagina_itens[i:i + n_cols_eq]):
                        with cols_grid[j]:
                            _render_card(t)
                            if st.button(f"🔍 Abrir #{t.get('id_zendesk', t.get('id','')[:8])}",
                                         key=f"eqopen_{uname}_{t.get('id','')}",
                                         use_container_width=True):
                                abrir_ticket_popup(t.get("id"), user, papel)
                _nav_paginas(pag_atual, total_paginas, pag_key, total)


# ── ABA: 📋 Por Motivo (Tabulação) ───────────────────────────────────
def _aba_por_motivo(tickets: list, dep_alvo: str, nomes_users: dict):
    tabs_dep = [t for t in listar_tabulacoes() if t.get("departamento") == dep_alvo]

    def _resumo_quem(lista_tickets):
        from collections import Counter
        cont = Counter()
        for t in lista_tickets:
            ats = t.get("atendentes") or []
            if not ats and t.get("atribuido_para"):
                ats = [t.get("atribuido_para")]
            if not ats:
                cont["— ninguém atribuído —"] += 1
            for a in ats:
                cont[nomes_users.get(a, a)] += 1
        return cont

    if not tabs_dep:
        st.caption("Nenhuma tabulação cadastrada para este departamento.")
    else:
        for tb in tabs_dep:
            nome_tab = tb.get("nome", "—")
            tks_tab  = [t for t in tickets if t.get("tabulacao") == nome_tab]
            n_total  = len(tks_tab)
            n_pend   = sum(1 for t in tks_tab if t.get("status") in STATUS_ABERTOS)
            n_perd   = sum(1 for t in tks_tab if sla_foi_perdido(t))
            cont_at  = _resumo_quem(tks_tab)
            quem_str = ", ".join(f"{nome} ({qtd})" for nome, qtd in cont_at.most_common()) or "—"
            alerta   = f' <span class="tk-blink">⏳ {n_perd} c/ SLA perdido</span>' if n_perd else ""

            st.markdown(_html(
                f'<div class="tk-equipe-card">'
                f'<b style="color:#2c3e50;">📋 {esc(nome_tab)}</b>{alerta}<br>'
                f'<span style="font-size:0.8rem;color:#64778d;">'
                f'Total: {n_total} &nbsp;·&nbsp; Pendentes: {n_pend} &nbsp;·&nbsp; '
                f'SLA perdido: {n_perd}</span><br>'
                f'<span style="font-size:0.78rem;color:#64778d;">'
                f'👥 Com quem está: {esc(quem_str)}</span>'
                f'</div>'), unsafe_allow_html=True)

        sem_tab = [t for t in tickets if not t.get("tabulacao")]
        if sem_tab:
            cont_at  = _resumo_quem(sem_tab)
            quem_str = ", ".join(f"{nome} ({qtd})" for nome, qtd in cont_at.most_common()) or "—"
            st.markdown(_html(
                f'<div class="tk-equipe-card">'
                f'<b style="color:#64778d;">📋 Sem tabulação</b><br>'
                f'<span style="font-size:0.8rem;color:#64778d;">Total: {len(sem_tab)}</span><br>'
                f'<span style="font-size:0.78rem;color:#64778d;">'
                f'👥 Com quem está: {esc(quem_str)}</span>'
                f'</div>'), unsafe_allow_html=True)


# ── ABA: ⏳ SLA Perdido (ranking + detalhe dos responsáveis) ─────────
def _aba_sla_perdido(tickets: list, nomes_users: dict, user, papel):
    from collections import Counter

    perdidos = [t for t in tickets if sla_foi_perdido(t)]
    if not perdidos:
        st.success("✅ Nenhum ticket com SLA perdido neste recorte.")
        return

    st.markdown(f"##### ⏳ {len(perdidos)} ticket(s) com SLA perdido")
    st.caption("Inclui tickets pendentes vencidos agora e tickets já encerrados que "
               "ultrapassaram o SLA antes de serem tratados.")

    cont_resp = Counter()
    for t in perdidos:
        ats = t.get("atendentes") or ([t.get("atribuido_para")] if t.get("atribuido_para") else [])
        if not ats: ats = ["— ninguém —"]
        for a in ats:
            cont_resp[nomes_users.get(a, a)] += 1

    st.markdown("**Ranking de responsáveis por SLA perdido**")
    df_resp = pd.DataFrame(cont_resp.most_common(), columns=["Atendente", "SLA Perdido"])
    st.dataframe(df_resp, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("**Detalhe dos tickets com SLA perdido**")
    linhas = []
    for t in perdidos:
        ats = t.get("atendentes") or ([t.get("atribuido_para")] if t.get("atribuido_para") else [])
        atend_nomes = ", ".join(nomes_users.get(a, a) for a in ats) if ats else "— ninguém —"
        linhas.append({
            "ID": t.get("id_zendesk", str(t.get("id",""))[:8]),
            "Assunto": str(t.get("assunto",""))[:50],
            "Motivo": t.get("tabulacao") or "Sem tabulação",
            "Status": STATUS_CFG.get(t.get("status",""), (t.get("status",""),))[0],
            "Atendente(s)": atend_nomes,
            "Criado em": t.get("criado_em",""),
            "SLA (h)": t.get("horas_sla",24),
        })
    df_det = pd.DataFrame(linhas)
    st.dataframe(df_det, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.caption("Clique para abrir um ticket específico:")
    n_cols_sla = 3
    for i in range(0, len(perdidos), n_cols_sla):
        cols_grid = st.columns(n_cols_sla)
        for j, t in enumerate(perdidos[i:i + n_cols_sla]):
            with cols_grid[j]:
                _render_card(t)
                if st.button(f"🔍 Abrir #{t.get('id_zendesk', t.get('id','')[:8])}",
                             key=f"slaopen_{t.get('id','')}", use_container_width=True):
                    abrir_ticket_popup(t.get("id"), user, papel)


# ── ABA: 📥 Exportar (relatório completo em Excel) ──────────────────
def _aba_exportar(tickets: list, nomes_users: dict, dep_alvo: str, data_ini=None, data_fim=None):
    st.markdown("##### 📥 Relatório Completo")
    st.caption(
        "Gera uma planilha .xlsx com 3 abas: **Por Atendente** (produtividade e SLA perdido), "
        "**Por Motivo** (volume por tabulação) e **Detalhe Completo** (todos os tickets do "
        "recorte filtrado acima, ticket a ticket)."
    )
    periodo_txt = (f"{data_ini.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                   if (data_ini and data_fim) else "todo o histórico")
    st.markdown(f"Departamento: **{dep_alvo}** &nbsp;·&nbsp; Período: **{periodo_txt}** "
                f"&nbsp;·&nbsp; Tickets no relatório: **{len(tickets)}**")

    if not tickets:
        st.info("Nenhum ticket para exportar com os filtros atuais.")
        return

    sufixo_periodo = (f"{data_ini.strftime('%Y%m%d')}_a_{data_fim.strftime('%Y%m%d')}"
                       if (data_ini and data_fim) else datetime.now(BRT).strftime('%Y%m%d_%H%M'))
    xls_bytes = _gerar_excel_relatorio(tickets, nomes_users)
    st.download_button(
        "📊 Baixar Relatório Completo (.xlsx)",
        data=xls_bytes,
        file_name=f"Relatorio_Tickets_{dep_alvo}_{sufixo_periodo}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )


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
            listar_tickets.clear()
            st.success(f"✅ {total} tickets importados para o Firestore!")

    # ── Estatísticas ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Tickets no Firestore por origem")
    todos2 = listar_tickets()
    from collections import Counter
    df_orig = pd.DataFrame(
        Counter(t.get("origem","interno") for t in todos2).items(),
        columns=["Origem","Qtd"]
    )
    st.dataframe(df_orig, use_container_width=True, hide_index=True)

    # ── ⚠️ ZONA DE PERIGO — exclusão total (só ADM) ───────────────
    st.markdown("---")
    st.markdown(_html("""
    <div style="border:2px solid #8A6D1F;border-radius:12px;padding:16px 20px;
                background:#FBF3D9;margin-top:8px;">
        <span style="font-size:1rem;font-weight:800;color:#7A5C12;">
            ⚠️ Zona de Perigo — Exclusão Total de Tickets
        </span><br>
        <span style="font-size:0.82rem;color:#7A5C12;">
            Esta ação remove <b>permanentemente</b> todos os tickets do banco de dados.
            Não pode ser desfeita.
        </span>
    </div>
    """), unsafe_allow_html=True)

    st.markdown("")
    total_tickets = len(todos2)
    st.caption(f"Atualmente há **{total_tickets}** ticket(s) no banco de dados.")

    conf1 = st.checkbox(
        f"Confirmo que quero excluir TODOS os {total_tickets} ticket(s) do banco de dados.",
        key="del_conf1"
    )
    conf2 = st.checkbox(
        "Entendo que esta ação é IRREVERSÍVEL e não há como recuperar os dados.",
        key="del_conf2"
    )

    botao_ativo = conf1 and conf2
    if st.button(
        "🗑️ Excluir TODOS os tickets permanentemente",
        type="primary",
        use_container_width=True,
        disabled=not botao_ativo,
        key="btn_del_todos"
    ):
        with st.spinner(f"Excluindo {total_tickets} ticket(s)..."):
            qt = deletar_todos_tickets()
        st.success(f"✅ {qt} ticket(s) excluído(s) com sucesso. O banco de dados está vazio.")
        for k in ("del_conf1", "del_conf2"):
            if k in st.session_state:
                del st.session_state[k]
        time.sleep(1.5)
        st.rerun()
