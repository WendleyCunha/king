"""
KingStar — Módulo de Tickets — common.py
─────────────────────────────────────────────────────────────────────────────
Camada compartilhada (sem UI própria, exceto _render_bloco_historico_cliente
que é um bloquinho reaproveitado em vários lugares): constantes, helpers de
formatação, lógica de SLA em cascata, pendências entre setores, classificação
de filas, visibilidade por papel, histórico por cliente e todo o CRUD do
Firestore (tickets, comentários, sync Zendesk, exclusão total).

Todo o resto do pacote `tickets/` importa deste arquivo.
"""
import streamlit as st
import pandas as pd
import time
import sys
import os
import uuid
import html as _htmlmod
from datetime import datetime, timezone, timedelta

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
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
BLUE_INFO  = "#60A5FA"   # interação nova (azul-claro)

# ── Paleta de cores por Departamento (setor) ───────────────────────
DEPT_PALETTE = [
    "#2563EB", "#16A34A", "#DB2777", "#7C3AED", "#EA580C",
    "#0EA5E9", "#CA8A04", "#059669", "#D946EF", "#0D9488",
    "#DC2626", "#4F46E5", "#65A30D", "#C2410C", "#0891B2",
]

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
        t.get("motivo_pai",""), t.get("motivo_filho",""), t.get("etapa_atual",""),
    ]
    for a in t.get("atendentes", []):
        partes.append(a)
    for c in t.get("comentarios", []):
        partes.append(c.get("texto",""))
        partes.append(c.get("autor",""))
    for s in t.get("solicitacoes_setor", []):
        partes.append(s.get("setor_destino",""))
        partes.append(s.get("setor_origem",""))
        partes.append(s.get("mensagem",""))
        partes.append(s.get("resposta",""))
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

# ── SLA em cascata (SLA1 = Motivo Pai / SLA2 = Etapa vermelha travada) ──
def deadline_ativo(t) -> tuple:
    """Retorna (datetime_limite ou None, origem) onde origem é:
      'etapa' → SLA2 (etapa vermelha já travada, com data confirmada)
      'pai'   → SLA1 (prazo do Motivo Pai, ou horas_sla legado p/ tickets
                antigos/Zendesk que não usam a árvore de motivos)
    """
    if t.get("etapa_vermelha") and t.get("etapa_data_prevista"):
        try:
            d = datetime.fromisoformat(str(t["etapa_data_prevista"]))
            d = d.replace(hour=23, minute=59, second=59, tzinfo=BRT)
            return d, "etapa"
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(str(t.get("criado_em","")).replace(" ","T")).replace(tzinfo=BRT)
    except Exception:
        return None, "pai"
    if t.get("sla1_prazo_dias") is not None:
        return dt + timedelta(days=t.get("sla1_prazo_dias")), "pai"
    return dt + timedelta(hours=t.get("horas_sla", 24)), "pai"

def sla_label(t) -> str:
    _, origem = deadline_ativo(t)
    return "Prazo da etapa" if origem == "etapa" else "SLA"

def sla_restante(t) -> tuple:
    """Retorna (texto, pct_usado, vencido) considerando o prazo ATIVO."""
    limite, origem = deadline_ativo(t)
    if limite is None:
        return "—", 0, False
    inicio_str = t.get("etapa_definida_em") if origem == "etapa" else t.get("criado_em")
    try:
        inicio = datetime.fromisoformat(str(inicio_str).replace(" ","T")).replace(tzinfo=BRT)
    except Exception:
        inicio = limite - timedelta(hours=24)
    agora  = datetime.now(BRT)
    total  = (limite - inicio).total_seconds() or 1
    pct    = min(max((agora - inicio).total_seconds() / total * 100, 0), 100)
    diff   = (limite - agora).total_seconds()
    if diff <= 0:
        return "Expirado", 100, True
    h = int(diff // 3600); m = int((diff % 3600) // 60)
    return (f"{h}h {m}m" if h > 0 else f"{m}min"), pct, False

def pill(texto, bg, cor):
    return (f'<span style="background:{bg};color:{cor};padding:2px 10px;'
            f'border-radius:12px;font-size:0.72rem;font-weight:700;">{esc(texto)}</span>')

def sla_estado(t) -> str:
    """Retorna o estado do SLA ATIVO: 'ok', 'warn' (<=30min) ou 'venc'.
    Só vale para tickets pendentes; resolvidos/cancelados sempre 'ok'."""
    if t.get("status") not in STATUS_ABERTOS:
        return "ok"
    limite, _ = deadline_ativo(t)
    if limite is None:
        return "ok"
    restante = (limite - datetime.now(BRT)).total_seconds()
    if restante <= 0:
        return "venc"
    if restante <= 1800:
        return "warn"
    return "ok"

def ticket_vencido_pendente(t) -> bool:
    """True se o prazo ATIVO estourou E o ticket ainda está pendente."""
    if t.get("status") not in STATUS_ABERTOS:
        return False
    _, _, venc = sla_restante(t)
    return venc

def sla_foi_perdido(t) -> bool:
    """SLA (ativo — pai ou etapa) foi/está estourado, mesmo se o ticket já
    tiver sido resolvido/finalizado/cancelado (usa 'atualizado_em' como
    proxy de quando foi tratado)."""
    if t.get("status") in STATUS_ABERTOS:
        return ticket_vencido_pendente(t)
    limite, _ = deadline_ativo(t)
    if limite is None:
        return False
    try:
        atualz = datetime.fromisoformat(str(t.get("atualizado_em","")).replace(" ","T")).replace(tzinfo=BRT)
        return atualz > limite
    except Exception:
        return False

# ── Interação / alerta azul ─────────────────────────────────────────
def tem_interacao_nao_vista(t, user) -> bool:
    """True se houve uma interação de OUTRA pessoa que o(s) responsável(is)
    ainda não 'atendeu' (a única forma de limpar é o próprio responsável
    interagir de volta — comentário, mudança de status ou classificação)."""
    uname = user.get("usuario","")
    if uname not in t.get("atendentes", []):
        return False
    if t.get("ultima_interacao_autor") == uname:
        return False
    return bool(t.get("ultima_interacao_em"))

# ── Pendências entre Setores (cor por setor + solicitação/resposta) ────
def cor_departamento(nome_dep: str) -> str:
    """Cor do setor: usa o campo 'cor' cadastrado em Departamentos
    (Configurações → Departamentos) se existir; senão gera uma cor estável
    via hash do nome (sempre a mesma cor pro mesmo setor, mesmo sem cadastro)."""
    nome_dep = nome_dep or "—"
    try:
        for d in listar_departamentos():
            if d.get("nome") == nome_dep and d.get("cor"):
                return d["cor"]
    except Exception:
        pass
    idx = sum(ord(c) for c in str(nome_dep)) % len(DEPT_PALETTE)
    return DEPT_PALETTE[idx]

def _swatch_dept(nome_dep: str) -> str:
    """Emoji quadradinho aproximando a cor do setor — só pra dar uma pista
    visual no rótulo da aba (abas do Streamlit não aceitam HTML/CSS)."""
    cor = cor_departamento(nome_dep).lstrip("#")
    try:
        r, g, b = int(cor[0:2], 16), int(cor[2:4], 16), int(cor[4:6], 16)
    except Exception:
        return "🏢"
    if r > 190 and g < 100 and b < 130:  return "🟥"
    if r > 190 and 100 <= g < 180 and b < 100: return "🟧"
    if r > 190 and g > 190 and b < 120:  return "🟨"
    if g > 130 and r < 110 and b < 150:  return "🟩"
    if b > 170 and r < 130:               return "🟦"
    if r > 110 and b > 170 and g < 110:  return "🟪"
    if r > 130 and g > 60 and b < 90:    return "🟫"
    return "🏢"

def _novo_id_curto() -> str:
    return uuid.uuid4().hex[:10]

def solicitacoes_abertas(t) -> list:
    """Lista de pedidos (a outro setor) que ainda NÃO têm resposta registrada."""
    sols = t.get("solicitacoes_setor", []) or []
    respondidos = {s.get("pedido_id") for s in sols if s.get("tipo") == "resposta"}
    return [s for s in sols if s.get("tipo") == "pedido" and s.get("id") not in respondidos]

def solicitacoes_abertas_para_setor(t, setor: str) -> list:
    return [s for s in solicitacoes_abertas(t) if s.get("setor_destino") == setor]

def ticket_tem_pendencia_para_setor(t, setor: str) -> bool:
    return bool(solicitacoes_abertas_para_setor(t, setor))

def registrar_solicitacao_setor(tid: str, t: dict, setor_destino: str, mensagem: str, user: dict):
    """Cria uma pendência para outro setor DENTRO do mesmo ticket (não cria
    ticket novo — preserva o histórico único por cliente)."""
    from google.cloud.firestore import ArrayUnion
    pedido = {
        "id": _novo_id_curto(),
        "tipo": "pedido",
        "setor_origem": t.get("departamento") or t.get("categoria") or "—",
        "setor_destino": setor_destino,
        "mensagem": mensagem,
        "solicitado_por": user.get("usuario", ""),
        "solicitado_por_nome": user.get("nome", ""),
        "solicitado_em": agora_brt(),
    }
    get_db().collection(COLECAO).document(tid).update({
        "solicitacoes_setor": ArrayUnion([pedido]),
        "atualizado_em": agora_brt(),
        "ultima_interacao_em": agora_brt(),
        "ultima_interacao_autor": user.get("usuario", ""),
    })
    # também entra no chat unificado do ticket, pra quem só olha comentários
    adicionar_comentario(
        tid, user.get("nome", ""), user.get("usuario", ""),
        f"📨 Solicitação para o setor **{setor_destino}**: {mensagem}"
    )
    listar_tickets.clear()

def responder_solicitacao_setor(tid: str, pedido: dict, resposta_texto: str, user: dict):
    """Fecha uma pendência de setor, registrando a resposta (sem apagar o
    pedido original — o histórico completo fica sempre visível)."""
    from google.cloud.firestore import ArrayUnion
    resposta = {
        "id": _novo_id_curto(),
        "tipo": "resposta",
        "pedido_id": pedido.get("id"),
        "setor_origem": pedido.get("setor_destino"),
        "setor_destino": pedido.get("setor_origem"),
        "resposta": resposta_texto,
        "respondido_por": user.get("usuario", ""),
        "respondido_por_nome": user.get("nome", ""),
        "respondido_em": agora_brt(),
    }
    get_db().collection(COLECAO).document(tid).update({
        "solicitacoes_setor": ArrayUnion([resposta]),
        "atualizado_em": agora_brt(),
        "ultima_interacao_em": agora_brt(),
        "ultima_interacao_autor": user.get("usuario", ""),
    })
    adicionar_comentario(
        tid, user.get("nome", ""), user.get("usuario", ""),
        f"✅ Setor **{pedido.get('setor_destino')}** respondeu a solicitação "
        f"de **{pedido.get('setor_origem')}**: {resposta_texto}"
    )
    listar_tickets.clear()

def tickets_pendentes_do_setor(tickets: list, setor: str) -> list:
    """Tickets que o SETOR precisa tratar, pra alimentar a aba dele em
    'Filas de Trabalho'. Isso inclui DOIS casos, não só um:
      1) Tickets abertos DIRETAMENTE para esse setor (departamento == setor)
         e ainda pendentes — é o caso mais comum (ex.: abri um chamado pra
         TI, ele precisa aparecer na aba da TI).
      2) Tickets de QUALQUER outro setor que tenham uma solicitação aberta
         (pendência entre setores) direcionada a esse setor.
    Sem isso, um ticket aberto direto pro setor nunca aparecia na aba dele
    (só apareceria se alguém tivesse criado uma solicitação manual/automática
    — o que é um caso à parte, não o principal)."""
    out = []
    for t in tickets:
        if t.get("status") not in STATUS_ABERTOS:
            continue
        dono = (t.get("departamento") or t.get("categoria") or "") == setor
        solicitado = ticket_tem_pendencia_para_setor(t, setor)
        if dono or solicitado:
            out.append(t)
    return out

def departamentos_com_pendencia(tickets: list) -> dict:
    """{nome_setor: qtd_tickets_pendentes} pra montar o contador nas abas por setor."""
    from collections import defaultdict
    cont = defaultdict(int)
    setores = set()
    for t in tickets:
        setores.add(t.get("departamento") or t.get("categoria") or "")
        for s in solicitacoes_abertas(t):
            setores.add(s.get("setor_destino", "—"))
    for setor in setores:
        if not setor:
            continue
        qtd = len(tickets_pendentes_do_setor(tickets, setor))
        if qtd:
            cont[setor] = qtd
    return dict(cont)

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
    """Retorna a ÚNICA caixa onde o ticket aparece (ou None se em nenhuma)."""
    uname = user.get("usuario","")
    if t.get("aberto_por") == uname:
        status = t.get("status")
        if status in ("cancelado", "finalizado"):
            return None
        if status == "resolvido":
            return "meus" if resolvido_em_validacao(t) else None
        return "meus"
    if not _atribuido_a(t, user):
        return None
    status = t.get("status")
    if status not in STATUS_ABERTOS:
        return None
    if ticket_vencido_pendente(t):
        return "vencidos"
    if status == "aberto":
        return "aberto"
    if t.get("prioridade") == "urgente":
        return "urgente"
    return "em_andamento"

# ── Visibilidade por papel (Regra 5) ───────────────────────────────
def _usuario_atende(t, user) -> bool:
    uname = user.get("usuario","")
    nome  = user.get("nome","")
    if (uname in t.get("atendentes", [])
            or t.get("atribuido_para") in (uname, nome)
            or t.get("aberto_por") == uname):
        return True
    # participou de alguma pendência entre setores (pediu ou foi solicitado)
    dep_user = user.get("departamento")
    if dep_user:
        for s in t.get("solicitacoes_setor", []):
            if s.get("tipo") == "pedido" and dep_user in (s.get("setor_destino"), s.get("setor_origem")):
                return True
    return False

def ticket_visivel(t, user, papel) -> bool:
    if papel == "adm":
        return True
    if papel == "supervisor":
        return t.get("departamento","") == (user.get("departamento","") or "—")
    return _usuario_atende(t, user)

# ── Histórico por CLIENTE (Regra nova) ─────────────────────────────
def normalizar_codigo_cliente(cod) -> str:
    return str(cod or "").strip()

def tickets_do_cliente(cliente_codigo: str, excluir_id: str = None) -> list:
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

# ── CRUD Firestore ─────────────────────────────────────────────────
@st.cache_data(ttl=10, show_spinner=False)
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
        "historico_etapas": [],
        "solicitacoes_setor": [],
        "sla1_definido": False,
        "sla1_cumprido": None,
        "etapa_vermelha": False,
        "etapa_travada": False,
    }
    base.update(dados)
    base.setdefault("status", "aberto")
    base.setdefault("horas_sla", 24)
    ref.set(base)
    listar_tickets.clear()
    return ref.id

def atualizar_ticket(tid: str, dados: dict, interacao_de: str = None):
    dados = dict(dados)
    dados["atualizado_em"] = agora_brt()
    if interacao_de:
        dados["ultima_interacao_em"]     = agora_brt()
        dados["ultima_interacao_autor"]  = interacao_de
    get_db().collection(COLECAO).document(tid).update(dados)
    listar_tickets.clear()

def adicionar_comentario(tid: str, autor_nome: str, autor_usuario: str, texto: str):
    from google.cloud.firestore import ArrayUnion
    get_db().collection(COLECAO).document(tid).update({
        "comentarios": ArrayUnion([{
            "autor": autor_nome, "texto": texto, "data": agora_brt()
        }]),
        "atualizado_em": agora_brt(),
        "ultima_interacao_em": agora_brt(),
        "ultima_interacao_autor": autor_usuario,
    })
    listar_tickets.clear()

def vincular_ticket_relacionado(tid: str, novo_id: str):
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
                "departamento": "",
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

def _caminho_motivo(t) -> str:
    partes = [p for p in [t.get("motivo_pai"), t.get("motivo_filho"), t.get("etapa_atual")] if p]
    return " › ".join(partes) if partes else ""

# ───────────────────────────────────────────────────────────────────
# PAGINAÇÃO (9 tickets por página, em qualquer lista de tirinhas)
# ───────────────────────────────────────────────────────────────────
PAGE_SIZE_CARDS = 9

def _paginar(lista, chave_estado):
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
