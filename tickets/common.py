"""
KingStar — Módulo de Tickets — common.py
─────────────────────────────────────────────────────────────────────────────
Camada compartilhada (sem UI própria, exceto _render_bloco_historico_cliente
que é um bloquinho reaproveitado em vários lugares): constantes, helpers de
formatação, lógica de SLA em cascata, pendências entre setores, classificação
de filas, visibilidade por papel, histórico por cliente e todo o CRUD do
Firestore (tickets, comentários, sync Zendesk, exclusão total).

Todo o resto do pacote `tickets/` importa deste arquivo.

[v5 — TICKET CONTÊINER POR CLIENTE] Mudança de modelo de dados, a pedido:
  1) `cliente_codigo` normalizado passou a ser a CHAVE do documento do
     Firestore (um único documento por cliente — "ticket contêiner").
  2) Abrir um chamado com o MESMO Motivo Pai de uma solicitação ainda não
     encerrada (status fora de finalizado/cancelado) do MESMO cliente é
     BLOQUEADO (ver `abrir_solicitacao_cliente`).
  3) Motivos diferentes (ou o mesmo motivo já encerrado antes) são sempre
     aceitos como NOVA "solicitação" dentro do MESMO documento contêiner.
  4) O documento contêiner guarda um array `solicitacoes` — cada elemento é
     uma solicitação completa (mesmos campos que um "ticket" tinha antes:
     assunto, motivo, status, SLA, atendentes, comentários...). O histórico
     de TODAS as solicitações do cliente vive sempre no mesmo documento.
  5) Cada solicitação tem seu próprio `status` — encerrar uma não afeta as
     outras do mesmo contêiner.

  Para não obrigar a reescrever todo o resto do sistema (strip.py, filas.py,
  geral.py, detalhe.py), o container nunca é exposto diretamente: toda
  leitura passa por `_achatar(...)`, que transforma cada solicitação num
  dict "achatado" com EXATAMENTE os mesmos campos que um ticket antigo
  tinha (inclusive um "id" — agora um ID COMPOSTO "container#sid"). Todo o
  código que já existia (SLA, status, badges, listagem, exportação) continua
  funcionando sem nenhuma alteração, porque só enxerga esse dict achatado.

  Documentos ANTIGOS (formato "achatado" direto na raiz, sem o array
  `solicitacoes` — inclusive os importados do Zendesk) continuam sendo lidos
  normalmente: são envolvidos em memória por `_normalizar_container` como um
  contêiner de uma única solicitação. Na primeira vez que forem atualizados
  (`atualizar_ticket`), já são regravados no formato novo automaticamente —
  não é necessário rodar nenhuma migração manual.

  `criar_ticket(dados)` continua existindo com o MESMO contrato de antes
  (recebe dict, devolve uma string de ID) para não quebrar nenhum outro
  módulo do sistema que já a chame diretamente (ex.: possivelmente
  mod_home.py) — mas ela NÃO aplica o bloqueio de motivo duplicado (regra 2
  é uma regra da TELA de abertura de chamado, não do primitivo de gravação).
  Quem precisa do bloqueio é `abrir_solicitacao_cliente`, usada por
  `tickets/novo.py`.

[v6 — WHATSAPP DE VERDADE (Twilio)] Novidade: envio e leitura de mensagens
  reais de WhatsApp, ligadas ao TELEFONE do cliente (campo novo
  `cliente_telefone` na solicitação — preenchido na abertura do chamado ou
  editável depois no painel de detalhe).

  Arquitetura (ver changelog completo no topo de `tickets/detalhe.py` e no
  arquivo separado `webhook_whatsapp/main.py`):
    • As mensagens NÃO ficam dentro do documento do ticket (cliente_codigo).
      Ficam numa coleção PRÓPRIA, `whatsapp_conversas`, com um documento por
      TELEFONE normalizado — porque é assim que a Twilio te avisa de uma
      mensagem nova (só manda o número de telefone, não sabe nada sobre
      "ticket" ou "cliente_codigo"). O painel de detalhe lê essa coleção
      pelo telefone salvo na solicitação.
    • ENVIAR (agente → cliente): função `enviar_whatsapp` abaixo, chama a
      API da Twilio direto daqui de dentro do Streamlit. Funciona sem
      nenhuma peça extra, desde que `twilio_account_sid`,
      `twilio_auth_token` e `twilio_whatsapp_from` estejam em `st.secrets`.
    • RECEBER (cliente → agente): a Twilio manda um webhook HTTP — e o
      Streamlit Cloud NÃO expõe esse tipo de endpoint. Por isso existe o
      arquivo separado `webhook_whatsapp/main.py` (uma Cloud Function do
      Google, publicada por fora deste app) que recebe o aviso da Twilio e
      grava a mensagem na MESMA coleção `whatsapp_conversas` — dali, o
      Streamlit só precisa LER (função `listar_mensagens_whatsapp`).
    • A regra das 24h da Twilio (fora da janela da última mensagem do
      cliente, só dá pra mandar mensagem usando um "template" aprovado pelo
      Meta) é checada em `minutos_desde_ultima_mensagem_cliente` e usada
      pela UI pra avisar/desabilitar o envio livre — nunca é ignorada.
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

# Coleção do histórico de WhatsApp — 1 documento por TELEFONE normalizado
# (não por ticket/cliente_codigo — ver changelog [v6] acima).
WHATSAPP_COLECAO = "whatsapp_conversas"
JANELA_WHATSAPP_H = 24  # janela de envio livre da Twilio (fora dela, precisa de template)

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

# Status que contam como "encerrado" para fins do bloqueio de motivo
# duplicado (regra 2) — "resolvido" ainda NÃO conta como encerrado aqui de
# propósito: um chamado "resolvido" mas ainda na janela de validação (24h,
# ver JANELA_VALIDACAO_H mais abaixo) pode ser reaberto, então uma segunda
# solicitação do MESMO motivo ainda deve ser bloqueada nesse meio-tempo.
STATUS_ENCERRADOS_DUPLICIDADE = ("finalizado", "cancelado")

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

# ═══════════════════════════════════════════════════════════════════
# TICKET CONTÊINER POR CLIENTE — helpers internos de (de)serialização
# ═══════════════════════════════════════════════════════════════════
def _normalizar_id_doc(cod: str) -> str:
    """
    Sanitiza um código de cliente para uso como ID de documento do
    Firestore: não pode conter '/', não pode ser vazio, nem ser '.' ou '..'.
    Também remove '#', que é o separador usado no ID COMPOSTO de solicitação
    (ver _compor_id/_decompor_id) — assim o código do cliente nunca conflita
    com esse separador, não importa o que o atendente digite.
    """
    cod = (cod or "").strip().replace("/", "_").replace("#", "_")
    return cod[:200] or ("cliente_" + _novo_id_curto())

def _compor_id(container_id: str, sid: str) -> str:
    return f"{container_id}#{sid}"

def _decompor_id(tid: str):
    """Separa um ID composto em (container_id, sid). Usa rsplit (a partir do
    FIM) de propósito: o sid nunca contém '#', mas o container_id (código do
    cliente já sanitizado) também não deveria — ainda assim, rsplit garante
    a separação correta mesmo num cenário legado/inesperado."""
    tid = str(tid or "")
    if "#" not in tid:
        return tid, "legacy"
    cid, sid = tid.rsplit("#", 1)
    return cid, sid

def _normalizar_container(raw: dict) -> dict:
    """
    Aceita tanto o formato NOVO (dict com uma lista em 'solicitacoes')
    quanto um documento ANTIGO (formato achatado, sem essa lista — inclusive
    os importados do Zendesk) e sempre devolve o formato novo em memória,
    envolvendo o documento antigo como uma única solicitação ('sid':
    'legacy'). Nunca escreve nada no Firestore sozinha — a gravação no
    formato novo só acontece na próxima vez que a solicitação for
    atualizada de verdade (migração preguiçosa, sem downtime).
    """
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
    """Achata uma solicitação em um dict com a MESMA forma que um ticket
    antigo tinha — é isso que permite todo o resto do sistema (SLA, status,
    badges, tirinha, exportação) continuar funcionando sem nenhuma
    alteração, mesmo com o novo modelo de contêiner por cliente."""
    flat = dict(sol)
    flat["id"] = _compor_id(container_id, sol.get("sid", "legacy"))
    flat.setdefault("cliente_codigo", container.get("cliente_codigo", ""))
    flat.setdefault("cliente_nome", container.get("cliente_nome", ""))
    return flat

def _carregar_container(container_id: str):
    """Leitura FRESCA (sem cache) de um contêiner pelo ID do documento."""
    doc = get_db().collection(COLECAO).document(container_id).get()
    if not doc.exists:
        return None
    return _normalizar_container(doc.to_dict())

def buscar_ticket_por_id(tid: str):
    """Busca uma solicitação específica pelo ID composto (container#sid),
    sempre com leitura FRESCA do Firestore — usado pelo painel de detalhe,
    que precisa refletir a mudança mais recente imediatamente após
    qualquer ação (mesmo comportamento que a leitura direta antiga tinha)."""
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
    """Reatribui uma lista de tickets (IDs compostos) para um novo
    responsável. Agrupa por contêiner (cliente) e aplica cada mudança numa
    transação Firestore própria por contêiner, pra não perder alterações
    concorrentes de outras solicitações do mesmo cliente."""
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
    """Cria uma pendência para outro setor DENTRO da MESMA solicitação (não
    cria ticket novo — preserva o histórico único por cliente)."""
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
    # também entra no chat unificado do ticket, pra quem só olha comentários
    adicionar_comentario(
        tid, user.get("nome", ""), user.get("usuario", ""),
        f"📨 Solicitação para o setor **{setor_destino}**: {mensagem}"
    )

def responder_solicitacao_setor(tid: str, pedido: dict, resposta_texto: str, user: dict):
    """Fecha uma pendência de setor, registrando a resposta (sem apagar o
    pedido original — o histórico completo fica sempre visível)."""
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

# ── Histórico por CLIENTE ───────────────────────────────────────────
def normalizar_codigo_cliente(cod) -> str:
    return str(cod or "").strip()

def tickets_do_cliente(cliente_codigo: str, excluir_id: str = None) -> list:
    """
    Todas as OUTRAS solicitações do mesmo cliente. Desde a Regra 1
    (cliente_codigo como chave do contêiner), a via rápida é ler
    DIRETAMENTE o documento cujo ID é o código normalizado do cliente — 1
    única leitura, sem varrer a coleção inteira.

    Também faz uma varredura de segurança em `listar_tickets()` (cacheada,
    portanto barata) para pegar tickets ANTIGOS/legados que porventura
    tenham o mesmo cliente_codigo mas vivam sob um ID de documento
    diferente (ex.: criados antes desta mudança de modelo, ou importados
    do Zendesk) — assim nenhum histórico antigo fica de fora.
    """
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

# ── CRUD Firestore ─────────────────────────────────────────────────
@st.cache_data(ttl=10, show_spinner=False)
def listar_tickets() -> list:
    """Lê TODOS os contêineres (um por cliente, mais os legados/Zendesk que
    ainda vivem sob ID próprio) e devolve a lista ACHATADA de solicitações
    — cada uma com a mesma forma que um ticket antigo tinha. É essa lista
    achatada que o resto do sistema (SLA, filas, badges, exportação)
    consome, sem precisar saber nada sobre o modelo de contêiner."""
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
    """
    Núcleo comum de criação: garante que TODA solicitação de um mesmo
    cliente (mesmo `cliente_codigo`) vive dentro do MESMO documento
    contêiner (Regra 1), e — quando `bloquear_duplicado=True` — impede
    abrir uma nova solicitação com o MESMO Motivo Pai de outra que ainda
    não esteja encerrada (Regra 2). Roda dentro de uma transação Firestore
    pra não haver corrida entre duas aberturas simultâneas do mesmo cliente
    (a checagem de duplicidade só é confiável se leitura+escrita forem
    atômicas).

    Sem `cliente_codigo` (uso interno/legado, sem tela de abertura própria
    de cliente), cria um contêiner novo com ID aleatório — mesmo
    comportamento que o sistema já tinha antes desta mudança.

    Retorna (ok: bool, mensagem_de_erro: str, tid_composto: str | None).
    """
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
    """
    [Compatibilidade] Cria/anexa uma solicitação SEM checar duplicidade de
    motivo — mantém o MESMO contrato de antes (recebe dict, devolve string
    de ID) para não quebrar nenhum outro módulo do sistema que já chame
    esta função diretamente. Ainda assim, se `dados` tiver `cliente_codigo`,
    a solicitação passa a viver no contêiner daquele cliente (Regra 1) —
    essa parte do novo modelo é sempre aplicada, incondicionalmente.

    Para a regra de bloqueio de motivo duplicado (Regra 2), usada pela tela
    de abertura de chamado, veja `abrir_solicitacao_cliente`.
    """
    _, _, tid = _criar_ou_anexar_solicitacao(dados, bloquear_duplicado=False)
    return tid

def abrir_solicitacao_cliente(dados: dict) -> tuple:
    """
    Abre uma nova solicitação de atendimento para um cliente, aplicando as
    regras completas do novo modelo:
      • Regra 1: `cliente_codigo` é a CHAVE do ticket contêiner.
      • Regra 2: bloqueia se já existir uma solicitação NÃO
        finalizada/cancelada com o MESMO Motivo Pai para este cliente.
      • Regras 3/4: motivos diferentes (ou o mesmo motivo já encerrado) são
        sempre aceitos como NOVA solicitação dentro do MESMO documento —
        nunca cria um segundo ticket pro mesmo cliente.
    Usada pela tela de abertura de chamado (`tickets/novo.py`).

    Retorna (ok: bool, mensagem_de_erro: str, tid_composto: str | None).
    """
    return _criar_ou_anexar_solicitacao(dados, bloquear_duplicado=True)

def atualizar_ticket(tid: str, dados: dict, interacao_de: str = None, apensar: dict = None):
    """
    Atualiza campos de UMA solicitação específica (identificada pelo ID
    composto `container#sid`), sem afetar as outras solicitações do mesmo
    cliente. Roda em uma transação Firestore (lê o contêiner inteiro,
    modifica só o elemento certo do array, regrava o documento inteiro) —
    isso evita perder alterações concorrentes de OUTRA solicitação do
    mesmo cliente sendo editada ao mesmo tempo por outra pessoa.

    `apensar`: dict opcional {campo: item} para ADICIONAR um item a um
    campo de lista da solicitação (ex.: {"historico_etapas": {...}}) na
    MESMA escrita — substitui o uso antigo de `ArrayUnion` do Firestore,
    que só funciona em updates diretos de campo, não em listas aninhadas
    dentro de um array maior como agora é o caso.
    """
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
    """
    [Compatibilidade — agora um no-op] Antes, cada abertura de chamado
    criava um documento novo e esta função só registrava uma referência
    cruzada entre "irmãos" do mesmo cliente. Desde a Regra 1 (cliente_codigo
    como chave do ticket contêiner), TODAS as solicitações de um mesmo
    cliente já vivem DENTRO do mesmo documento — não existe mais "ticket
    separado" para vincular. Mantida apenas para não quebrar chamadas
    antigas que ainda a invoquem.
    """
    pass

# ═══════════════════════════════════════════════════════════════════
# WHATSAPP DE VERDADE (Twilio) — ver changelog [v6] no topo do arquivo
# ═══════════════════════════════════════════════════════════════════
def normalizar_telefone(numero: str) -> str:
    """
    Normaliza um telefone para o formato E.164 (+55DDDNUMERO), aceitando
    qualquer formatação de entrada (com/sem parênteses, espaço, traço,
    DDI). Números de 10 ou 11 dígitos SEM '+' são tratados como Brasil
    (DDD + número) e recebem o DDI 55 automaticamente. Retorna "" se não
    houver nenhum dígito.
    """
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
    """Histórico completo (enviadas + recebidas) de WhatsApp com este
    telefone, mais antigas primeiro. Leitura FRESCA (sem cache) — o webhook
    de recebimento (Cloud Function externa) grava direto no Firestore, sem
    passar pelo cache do Streamlit, então uma leitura cacheada poderia
    esconder uma mensagem nova do cliente por até alguns segundos."""
    tel = normalizar_telefone(telefone)
    if not tel:
        return []
    doc = _whatsapp_ref(tel).get()
    if not doc.exists:
        return []
    data = doc.to_dict() or {}
    return sorted(data.get("mensagens", []), key=lambda m: m.get("criado_em", ""))

def minutos_desde_ultima_mensagem_cliente(telefone: str):
    """Minutos desde a última mensagem RECEBIDA do cliente (direção 'in'),
    ou None se ele nunca escreveu. Usado pra saber se o envio livre
    (free-form) ainda está dentro da janela de 24h da Twilio — fora dela,
    só um template aprovado pelo Meta funciona (ver skill de referência:
    twilio-whatsapp-send-message)."""
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
    """True se as 3 chaves da Twilio estiverem em st.secrets. Usada pela UI
    pra mostrar um aviso amigável em vez de deixar o envio quebrar."""
    return bool(
        st.secrets.get("twilio_account_sid")
        and st.secrets.get("twilio_auth_token")
        and st.secrets.get("twilio_whatsapp_from")
    )

def _twilio_client():
    """Import local de propósito (mesmo padrão de `import requests as req`
    já usado em sync_zendesk) — assim o módulo `twilio` só precisa estar
    instalado se essa função for de fato chamada, sem virar uma dependência
    obrigatória pro resto do sistema."""
    sid = st.secrets.get("twilio_account_sid")
    token = st.secrets.get("twilio_auth_token")
    if not sid or not token:
        return None
    from twilio.rest import Client
    return Client(sid, token)

def enviar_whatsapp(telefone: str, texto: str, autor_nome: str) -> tuple:
    """
    Envia uma mensagem de WhatsApp de verdade via Twilio (modo 'free-form'
    — só é aceito pela Twilio dentro da janela de 24h da última mensagem
    RECEBIDA do cliente; fora dela, a Twilio recusa o envio. A UI que chama
    esta função deve checar `minutos_desde_ultima_mensagem_cliente` ANTES
    de oferecer o botão de enviar, pra não deixar o atendente tentar um
    envio que vai falhar).

    Grava tanto o envio bem-sucedido quanto a tentativa na coleção
    `whatsapp_conversas` (mesma que o webhook de recebimento usa), pra o
    histórico ficar completo e em ordem cronológica única.

    Retorna (ok: bool, mensagem_ou_erro: str).
    """
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

# ── Sync Zendesk ───────────────────────────────────────────────────
def sync_zendesk() -> tuple:
    """
    [Legado, formato inalterado] Os tickets importados do Zendesk não têm
    `cliente_codigo` (a API do Zendesk usada aqui não devolve esse dado),
    então continuam sendo gravados no formato "achatado" direto, um
    documento por ticket (`zendesk_{id}`) — não fazem parte do modelo de
    contêiner por cliente. Continuam sendo lidos normalmente por
    `listar_tickets()`/`_normalizar_container`, que envolve qualquer
    documento nesse formato antigo como um contêiner de uma solicitação só.
    """
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
