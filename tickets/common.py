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
from google.cloud import firestore as _fs

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

WHATSAPP_COLECAO = "whatsapp_conversas"
JANELA_WHATSAPP_H = 24

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

STATUS_ABERTOS = ("aberto", "em_andamento", "aguardando")
STATUS_ENCERRADOS_DUPLICIDADE = ("finalizado", "cancelado")

GOLD       = "#C9A84C"
GOLD_WARN  = "#D4A12C"
GOLD_VENC  = "#8A6D1F"
GREEN_OK   = "#16A34A"
BLUE_INFO  = "#60A5FA"

DEPT_PALETTE = [
    "#2563EB", "#16A34A", "#DB2777", "#7C3AED", "#EA580C",
    "#0EA5E9", "#CA8A04", "#059669", "#D946EF", "#0D9488",
    "#DC2626", "#4F46E5", "#65A30D", "#C2410C", "#0891B2",
]

def agora_brt() -> str:
    return datetime.now(BRT).strftime("%Y-%m-%d %H:%M:%S")

def _html(s: str) -> str:
    return "\n".join(linha.lstrip() for linha in s.splitlines())

def esc(v) -> str:
    return _htmlmod.escape(str(v if v is not None else ""))

def texto_busca(t) -> str:
    partes = [
        t.get("id",""), t.get("id_zendesk",""), t.get("assunto",""),
        t.get("descricao",""), t.get("solicitante_nome",""),
        t.get("cliente_nome",""), t.get("cliente_codigo",""),
        t.get("cliente_telefone",""),
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

def _novo_id_curto() -> str:
    return uuid.uuid4().hex[:10]

def _normalizar_id_doc(cod: str) -> str:
    cod = (cod or "").strip().replace("/", "_").replace("#", "_")
    return cod[:200] or ("cliente_" + _novo_id_curto())

def _compor_id(container_id: str, sid: str) -> str:
    return f"{container_id}#{sid}"

def _decompor_id(tid: str):
    tid = str(tid or "")
    if "#" not in tid:
        return tid, "legacy"
    cid, sid = tid.rsplit("#", 1)
    return cid, sid

def _normalizar_container(raw: dict) -> dict:
    if not raw:
        return {"cliente_codigo": "", "cliente_nome": "", "solicitacoes": []}
    if isinstance(raw.get("solicitacoes"), list):
        return raw
    sol_legado = dict(raw)
    sol_legado.setdefault("sid", "legacy")
    return {
        "cliente_codigo": raw.get("cliente_codigo", ""),
        "cliente_nome": raw.get("cliente_nome", ""),
        "criado_em": raw.get("criado_em", ""),
        "atualizado_em": raw.get("atualizado_em", ""),
        "solicitacoes": [sol_legado],
    }

def _achatar(container_id: str, container: dict, sol: dict) -> dict:
    flat = dict(sol)
    flat["id"] = _compor_id(container_id, sol.get("sid", "legacy"))
    flat.setdefault("cliente_codigo", container.get("cliente_codigo", ""))
    flat.setdefault("cliente_nome", container.get("cliente_nome", ""))
    return flat

def _carregar_container(container_id: str):
    doc = get_db().collection(COLECAO).document(container_id).get()
    if not doc.exists:
        return None
    return _normalizar_container(doc.to_dict())

def buscar_ticket_por_id(tid: str):
    if not tid:
        return None
    cid, sid = _decompor_id(tid)
    container = _carregar_container(cid)
    if not container:
        return None
    for s in container.get("solicitacoes", []):
        if s.get("sid") == sid:
            return _achatar(cid, container, s)
    return None

def transferir_tickets(tids: list, novo_responsavel: str):
    from collections import defaultdict
    agrupado = defaultdict(list)
    for tid in tids:
        cid, sid = _decompor_id(tid)
        agrupado[cid].append(sid)

    db = get_db()
    n = 0
    for cid, sids in agrupado.items():
        ref = db.collection(COLECAO).document(cid)
        transaction = db.transaction()

        @_fs.transactional
        def _tx(transaction, ref=ref, sids=sids):
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return 0
            container = _normalizar_container(snap.to_dict())
            sols = list(container.get("solicitacoes", []))
            agora = agora_brt()
            qt = 0
            for i, s in enumerate(sols):
                if s.get("sid") in sids:
                    sols[i] = {**s, "atendentes": [novo_responsavel],
                               "atribuido_para": novo_responsavel, "atualizado_em": agora}
                    qt += 1
            container["solicitacoes"] = sols
            container["atualizado_em"] = agora
            transaction.set(ref, container)
            return qt

        n += _tx(transaction)

    listar_tickets.clear()
    return n

def deadline_ativo(t) -> tuple:
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
    if t.get("status") not in STATUS_ABERTOS:
        return False
    _, _, venc = sla_restante(t)
    return venc

def sla_foi_perdido(t) -> bool:
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

def tem_interacao_nao_vista(t, user) -> bool:
    uname = user.get("usuario","")
    if uname not in t.get("atendentes", []):
        return False
    if t.get("ultima_interacao_autor") == uname:
        return False
    return bool(t.get("ultima_interacao_em"))

def cor_departamento(nome_dep: str) -> str:
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

def solicitacoes_abertas(t) -> list:
    sols = t.get("solicitacoes_setor", []) or []
    respondidos = {s.get("pedido_id") for s in sols if s.get("tipo") == "resposta"}
    return [s for s in sols if s.get("tipo") == "pedido" and s.get("id") not in respondidos]

def solicitacoes_abertas_para_setor(t, setor: str) -> list:
    return [s for s in solicitacoes_abertas(t) if s.get("setor_destino") == setor]

def ticket_tem_pendencia_para_setor(t, setor: str) -> bool:
    return bool(solicitacoes_abertas_para_setor(t, setor))

def registrar_solicitacao_setor(tid: str, t: dict, setor_destino: str, mensagem: str, user: dict):
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
    atualizar_ticket(tid, {}, interacao_de=user.get("usuario", ""),
                      apensar={"solicitacoes_setor": pedido})
    adicionar_comentario(
        tid, user.get("nome", ""), user.get("usuario", ""),
        f"📨 Solicitação para o setor **{setor_destino}**: {mensagem}"
    )

def responder_solicitacao_setor(tid: str, pedido: dict, resposta_texto: str, user: dict):
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
    atualizar_ticket(tid, {}, interacao_de=user.get("usuario", ""),
                      apensar={"solicitacoes_setor": resposta})
    adicionar_comentario(
        tid, user.get("nome", ""), user.get("usuario", ""),
        f"✅ Setor **{pedido.get('setor_destino')}** respondeu a solicitação "
        f"de **{pedido.get('setor_origem')}**: {resposta_texto}"
    )

def tickets_pendentes_do_setor(tickets: list, setor: str) -> list:
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

def _atribuido_a(t, user) -> bool:
    uname = user.get("usuario","")
    nome  = user.get("nome","")
    return (uname in t.get("atendentes", [])
            or t.get("atribuido_para") in (uname, nome))

JANELA_VALIDACAO_H = 24

def _horas_desde_atualizacao(t) -> float:
    try:
        dt = datetime.fromisoformat(str(t.get("atualizado_em","")).replace(" ","T")).replace(tzinfo=BRT)
        return (datetime.now(BRT) - dt).total_seconds() / 3600.0
    except Exception:
        return 0.0

def resolvido_em_validacao(t) -> bool:
    return t.get("status") == "resolvido" and _horas_desde_atualizacao(t) < JANELA_VALIDACAO_H

def classificar_fila(t, user) -> str:
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

def _usuario_atende(t, user) -> bool:
    uname = user.get("usuario","")
    nome  = user.get("nome","")
    if (uname in t.get("atendentes", [])
            or t.get("atribuido_para") in (uname, nome)
            or t.get("aberto_por") == uname):
        return True
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

def normalizar_codigo_cliente(cod) -> str:
    return str(cod or "").strip()

def tickets_do_cliente(cliente_codigo: str, excluir_id: str = None) -> list:
    cod = normalizar_codigo_cliente(cliente_codigo)
    if not cod:
        return []

    encontrados = {}
    cid = _normalizar_id_doc(cod)
    container = _carregar_container(cid)
    if container:
        for s in container.get("solicitacoes", []):
            flat = _achatar(cid, container, s)
            encontrados[flat["id"]] = flat

    for t in listar_tickets():
        if normalizar_codigo_cliente(t.get("cliente_codigo")) == cod:
            encontrados.setdefault(t.get("id"), t)

    if excluir_id:
        encontrados.pop(excluir_id, None)

    return sorted(encontrados.values(), key=lambda x: x.get("criado_em",""), reverse=True)

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

@st.cache_data(ttl=10, show_spinner=False)
def listar_tickets() -> list:
    docs = get_db().collection(COLECAO).stream()
    flat = []
    for d in docs:
        raw = d.to_dict()
        if not raw:
            continue
        container = _normalizar_container(raw)
        for s in container.get("solicitacoes", []):
            flat.append(_achatar(d.id, container, s))
    return sorted(flat, key=lambda x: x.get("criado_em",""), reverse=True)

def _criar_ou_anexar_solicitacao(dados: dict, bloquear_duplicado: bool = False):
    cod = normalizar_codigo_cliente(dados.get("cliente_codigo"))
    db  = get_db()

    if cod:
        container_id = _normalizar_id_doc(cod)
        ref = db.collection(COLECAO).document(container_id)
    else:
        ref = db.collection(COLECAO).document()
        container_id = ref.id

    transaction = db.transaction()

    @_fs.transactional
    def _tx(transaction):
        snap = ref.get(transaction=transaction)
        raw = snap.to_dict() if snap.exists else None
        container = _normalizar_container(raw) if raw else {"cliente_codigo": cod, "cliente_nome": "", "solicitacoes": []}

        if bloquear_duplicado and cod:
            motivo_novo = (dados.get("motivo_pai") or "").strip().lower()
            if motivo_novo:
                for s in container.get("solicitacoes", []):
                    if (s.get("motivo_pai") or "").strip().lower() == motivo_novo \
                            and s.get("status") not in STATUS_ENCERRADOS_DUPLICIDADE:
                        status_lbl = STATUS_CFG.get(s.get("status"), (s.get("status"),))[0]
                        return False, (
                            f"Este cliente já tem uma solicitação em aberto para o motivo "
                            f"\"{s.get('motivo_pai')}\" (status: {status_lbl}). Trate ou encerre "
                            f"essa solicitação antes de abrir outra com o mesmo motivo."
                        ), None

        agora = agora_brt()
        sid = _novo_id_curto()
        nova_sol = {
            "sid": sid, "criado_em": agora, "atualizado_em": agora, "origem": "interno",
            "comentarios": [], "historico_etapas": [], "solicitacoes_setor": [],
            "sla1_definido": False, "sla1_cumprido": None,
            "etapa_vermelha": False, "etapa_travada": False,
            "status": "aberto", "horas_sla": 24,
        }
        nova_sol.update(dados)
        nova_sol["sid"] = sid
        if cod:
            nova_sol["cliente_codigo"] = cod

        sols = list(container.get("solicitacoes", []))
        sols.append(nova_sol)
        container["solicitacoes"] = sols
        container["cliente_codigo"] = cod
        if dados.get("cliente_nome"):
            container["cliente_nome"] = dados["cliente_nome"]
        container.setdefault("criado_em", agora)
        container["atualizado_em"] = agora

        transaction.set(ref, container)
        return True, "", _compor_id(container_id, sid)

    ok, msg, tid = _tx(transaction)
    listar_tickets.clear()
    return ok, msg, tid

def criar_ticket(dados: dict) -> str:
    _, _, tid = _criar_ou_anexar_solicitacao(dados, bloquear_duplicado=False)
    return tid

def abrir_solicitacao_cliente(dados: dict) -> tuple:
    return _criar_ou_anexar_solicitacao(dados, bloquear_duplicado=True)

def atualizar_ticket(tid: str, dados: dict, interacao_de: str = None, apensar: dict = None):
    cid, sid = _decompor_id(tid)
    db = get_db()
    ref = db.collection(COLECAO).document(cid)
    transaction = db.transaction()

    @_fs.transactional
    def _tx(transaction):
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            return
        container = _normalizar_container(snap.to_dict())
        sols = list(container.get("solicitacoes", []))
        idx = next((i for i, s in enumerate(sols) if s.get("sid") == sid), None)
        if idx is None:
            return
        sol = dict(sols[idx])
        sol.update(dados)
        agora = agora_brt()
        sol["atualizado_em"] = agora
        if interacao_de:
            sol["ultima_interacao_em"] = agora
            sol["ultima_interacao_autor"] = interacao_de
        if apensar:
            for campo, item in apensar.items():
                lst = list(sol.get(campo, []))
                lst.append(item)
                sol[campo] = lst
        sols[idx] = sol
        container["solicitacoes"] = sols
        container["atualizado_em"] = agora
        transaction.set(ref, container)

    _tx(transaction)
    listar_tickets.clear()

def adicionar_comentario(tid: str, autor_nome: str, autor_usuario: str, texto: str):
    atualizar_ticket(
        tid, {}, interacao_de=autor_usuario,
        apensar={"comentarios": {"autor": autor_nome, "texto": texto, "data": agora_brt()}},
    )

def vincular_ticket_relacionado(tid: str, novo_id: str):
    pass

def normalizar_telefone(numero: str) -> str:
    numero = (numero or "").strip()
    digitos = "".join(c for c in numero if c.isdigit())
    if not digitos:
        return ""
    if len(digitos) in (10, 11) and not numero.strip().startswith("+"):
        digitos = "55" + digitos
    return "+" + digitos

def _whatsapp_ref(telefone_norm: str):
    return get_db().collection(WHATSAPP_COLECAO).document(telefone_norm.lstrip("+"))

def listar_mensagens_whatsapp(telefone: str) -> list:
    tel = normalizar_telefone(telefone)
    if not tel:
        return []
    doc = _whatsapp_ref(tel).get()
    if not doc.exists:
        return []
    data = doc.to_dict() or {}
    return sorted(data.get("mensagens", []), key=lambda m: m.get("criado_em", ""))

def minutos_desde_ultima_mensagem_cliente(telefone: str):
    msgs = listar_mensagens_whatsapp(telefone)
    recebidas = [m for m in msgs if m.get("direcao") == "in"]
    if not recebidas:
        return None
    ultima = recebidas[-1]
    try:
        dt = datetime.fromisoformat(str(ultima.get("criado_em","")).replace(" ","T")).replace(tzinfo=BRT)
        return (datetime.now(BRT) - dt).total_seconds() / 60.0
    except Exception:
        return None

def whatsapp_configurado() -> bool:
    return bool(
        st.secrets.get("twilio_account_sid")
        and st.secrets.get("twilio_auth_token")
        and st.secrets.get("twilio_whatsapp_from")
    )

def _twilio_client():
    sid = st.secrets.get("twilio_account_sid")
    token = st.secrets.get("twilio_auth_token")
    if not sid or not token:
        return None
    from twilio.rest import Client
    return Client(sid, token)

def enviar_whatsapp(telefone: str, texto: str, autor_nome: str) -> tuple:
    tel = normalizar_telefone(telefone)
    if not tel:
        return False, "Telefone do cliente não informado ou inválido."

    cliente = _twilio_client()
    if not cliente:
        return False, ("WhatsApp não configurado — faltam `twilio_account_sid` / "
                        "`twilio_auth_token` em Secrets.")

    remetente = st.secrets.get("twilio_whatsapp_from", "")
    if not remetente:
        return False, "Falta `twilio_whatsapp_from` em Secrets (seu número aprovado ou o do sandbox)."
    if not remetente.startswith("whatsapp:"):
        remetente = f"whatsapp:{remetente}"

    try:
        msg = cliente.messages.create(from_=remetente, to=f"whatsapp:{tel}", body=texto)
    except Exception as e:
        return False, f"Erro ao enviar pela Twilio: {e}"

    ref = _whatsapp_ref(tel)
    doc = ref.get()
    data = doc.to_dict() if doc.exists else {"telefone": tel, "mensagens": []}
    mensagens = list(data.get("mensagens", []))
    mensagens.append({
        "direcao": "out", "texto": texto, "autor": autor_nome,
        "message_sid": msg.sid, "status": msg.status, "criado_em": agora_brt(),
    })
    data["mensagens"] = mensagens
    data["telefone"] = tel
    data["atualizado_em"] = agora_brt()
    ref.set(data)
    return True, "Mensagem enviada!"

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
