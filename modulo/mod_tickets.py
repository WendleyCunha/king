"""
KingStar — Módulo de Tickets  (v4 — Motivos Pai/Filho/Etapa + SLA em cascata)
─────────────────────────────────────────────────────────────────────────────
Novidades desta versão (mantém tudo da v3 + patch de performance):

  [10] CLASSIFICAÇÃO EM ÁRVORE (Motivo Pai → Motivo Filho → Etapa):
       - Abertura do chamado escolhe Departamento + MOTIVO PAI (que carrega
         o SLA de triagem, ex.: 5 dias) — isso é o SLA1.
       - O atendente, ao tratar o ticket, define o MOTIVO FILHO e a ETAPA.
         Esse é o momento em que o SLA1 é congelado (cumprido/perdido) —
         serve pra saber se ele chegou a tempo de pelo menos analisar e
         direcionar o caso.
       - Etapa PRETA: não exige nada além disso; o prazo continua sendo o
         do Motivo Pai (SLA1), mesmo depois de classificada.
       - Etapa VERMELHA: exige que o atendente informe uma DATA FUTURA
         (SLA2). Ao confirmar, a trilha (Motivo Filho + Etapa + Data) fica
         TRAVADA PARA SEMPRE — evita "disfarçar" atraso mudando a etapa
         depois. A partir daí, o prazo mostrado no ticket passa a ser essa
         data (substitui o SLA do Pai enquanto essa etapa estiver vigente).
       - Etapas podem "reaproveitar" a árvore de outro Motivo Filho (ex.:
         "Bloqueio de estoque" dentro de "Troca Adaptação" reaproveita a
         árvore cadastrada em "Compras"), evitando recadastro duplicado.
       - Etapas podem vincular atendentes específicos; ao serem escolhidas,
         o ticket é reatribuído automaticamente a eles.

  [11] ALERTA DE INTERAÇÃO (🔵 piscante azul-claro):
       Toda vez que alguém interage num ticket (comenta, muda status,
       classifica a etapa, ou registra um contato/observação avulsa), o
       sistema grava quem foi e quando. Se essa interação NÃO foi do(s)
       atendente(s) responsável(is) pelo ticket, um badge azul piscante
       aparece pra eles — tanto na lista quanto no detalhe — até que ELES
       PRÓPRIOS interajam com o ticket (não basta abrir/visualizar).
       Isso cobre o caso de alguém da operação ter tido contato com o
       cliente sem o "dono" do ticket saber.

  [12] REGISTRO DE CONTATO/OBSERVAÇÃO: qualquer pessoa com visibilidade do
       ticket (mesmo não sendo o atendente responsável) pode registrar uma
       observação avulsa, que dispara o alerta de interação acima para o
       responsável.

  [13] PENDÊNCIAS ENTRE SETORES (v4.1):
       - Nasce AUTOMATICAMENTE: um Motivo Pai (na abertura) ou um Motivo Filho/
         Etapa (na classificação) pode ter um "Departamento vinculado" (campo
         cadastrado em Configurações → Motivos). Se esse setor for diferente
         do setor dono do ticket, o sistema cria a pendência sozinho — o
         atendente não precisa lembrar de solicitar nada.
       - Também dá pra registrar manualmente ("📨 Solicitar retorno de um
         setor") pra casos avulsos que não têm um Motivo/Etapa pré-cadastrado.
       - Isso NÃO cria um ticket novo — fica tudo dentro do MESMO ticket,
         preservando um único histórico por código de cliente.
       - Cada setor tem uma COR própria (cadastrada em Departamentos ou
         gerada automaticamente), usada nos badges/bordas pra facilitar
         achar visualmente "de quem é a bola" no histórico do ticket.
       - Aba extra por Departamento em "Filas de Trabalho": mostra, pra
         QUALQUER atendente (não só do setor), quais tickets aquele setor
         precisa responder — visão de transparência entre equipes.

  Tudo o mais (roteamento por departamento, tabulações legadas em tickets
  antigos/Zendesk, visibilidade por papel, ticket finalizado = somente
  leitura, histórico por cliente, performance com cache, Sync Zendesk,
  exclusão total, Visão Geral da Operação) permanece como na v3.

  [14] TIRINHA HORIZONTAL (padrão único de card de ticket):
       Todo lugar do sistema que mostra um ticket (Filas de Trabalho, abas
       por Departamento em Pendências, Visão Geral por Atendente, SLA
       vencidos) usa agora o MESMO componente visual: `_render_ticket_strip`.
       É uma única tirinha horizontal (um só bloco de HTML, sem "costura"
       entre botão e conteúdo), com TODAS as cores/badges/informações que
       já existiam, e o card inteiro é clicável (botão invisível por cima).

  [15] PAINÉIS REDIMENSIONÁVEIS + DETALHE LATERAL (v4.2):
       - O popup (st.dialog) de detalhe do ticket foi REMOVIDO. Clicar num
         ticket agora abre o detalhe numa TERCEIRA coluna, à direita —
         igual um cliente de e-mail (lista no meio, leitura à direita).
       - As duas divisas entre colunas (Filas↔Lista e Lista↔Detalhe) são
         arrastáveis com o mouse (mesmo padrão de painéis redimensionáveis
         de e-mail), substituindo o antigo slider "Ajustar largura dos
         painéis". A largura escolhida fica salva no sessionStorage do
         navegador (por aba) e é reaplicada a cada rerun, mas reseta num F5
         (é um ajuste 100% client-side, não fica no Firestore).
       - Isso depende de atributos internos do Streamlit
         (data-testid="stColumn"/"stHorizontalBlock") que não são API
         pública — funciona nas versões atuais, mas pode parar de arrastar
         (sem quebrar nada, só volta pras proporções padrão) se uma futura
         atualização do Streamlit renomear esses atributos.
"""
import streamlit as st
import pandas as pd
import time
import sys
import os
import uuid
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
from .mod_motivos import (
    listar_motivos_pai, motivos_pai_do_departamento,
    listar_motivos_filho, listar_motivos_filho_de,
    listar_etapas, listar_etapas_de, resolver_etapa_final,
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

# ═══════════════════════════════════════════════════════════════════
# PAINÉIS REDIMENSIONÁVEIS (Filas ↔ Lista ↔ Detalhe) — arrasto client-side
# ═══════════════════════════════════════════════════════════════════
def _render_estilo_paineis_redimensionaveis():
    """CSS + JS que transforma a divisa entre as colunas de 'Filas' / 'Lista'
    / 'Detalhe do ticket' em barras arrastáveis (mesmo padrão de painéis
    redimensionáveis de clientes de e-mail tipo Outlook/Gmail, e do mesmo
    jeito que a barra lateral NATIVA do Streamlit já se comporta). Puramente
    client-side: a largura escolhida fica salva no sessionStorage do
    navegador (por aba) e é reaplicada a cada rerun do Streamlit, então o
    ajuste "sobrevive" a cliques/reruns normais (mas não a um F5).

    IMPORTANTE: o CSS é injetado via st.markdown normalmente (funciona sem
    problema, `<style>` inserido via innerHTML é aplicado pelo navegador).
    Mas o <script> NÃO pode ir por st.markdown: por especificação do HTML,
    tags <script> inseridas via innerHTML (que é como o Streamlit renderiza
    st.markdown) simplesmente NUNCA executam — não é bug do Streamlit, é
    proteção do próprio navegador. Por isso o script roda dentro de um
    componente de verdade (`st.components.v1.html`, que cria um iframe onde
    scripts executam normalmente) e, de dentro dele, usa
    `window.parent.document` para enxergar e arrastar os elementos da
    página principal (funciona porque o iframe é same-origin).

    Depende de atributos internos do Streamlit (data-testid="stColumn" /
    "stHorizontalBlock") que não são API pública — se uma futura versão do
    Streamlit renomear esses atributos, o arrasto simplesmente para de
    funcionar (sem quebrar a tela, só volta pras proporções padrão).
    """
    st.markdown(_html("""
    <style>
    div[class*="st-key-tk_paineis"] div[data-testid="stHorizontalBlock"] {
        position: relative;
        align-items: stretch;
    }
    .tk-resizer {
        position: absolute; top: 0; bottom: 0; width: 10px; margin-left: -5px;
        cursor: col-resize; z-index: 999;
        display: flex; align-items: center; justify-content: center;
    }
    .tk-resizer::after {
        content: ""; width: 4px; height: 42px; border-radius: 3px;
        background: #D8CBA0; transition: background .15s, height .15s;
    }
    .tk-resizer:hover::after, .tk-resizer.tk-ativo::after {
        background: #C9A84C; height: 70px;
    }
    </style>
    """), unsafe_allow_html=True)

    import streamlit.components.v1 as components
    components.html("""
    <script>
    (function() {
        const doc = window.parent.document;

        function montarResizers() {
            const wrap = doc.querySelector('div[class*="st-key-tk_paineis"]');
            if (!wrap) return false;
            const row = wrap.querySelector('div[data-testid="stHorizontalBlock"]');
            if (!row) return false;
            const cols = Array.from(row.querySelectorAll(':scope > div[data-testid="stColumn"]'));
            if (cols.length < 2) return false;

            row.querySelectorAll('.tk-resizer').forEach(function(el) { el.remove(); });

            function aplicarLarguraSalva(chave, col) {
                const salva = sessionStorage.getItem(chave);
                if (salva) {
                    col.style.flex = '0 0 ' + salva + 'px';
                    col.style.width = salva + 'px';
                }
            }
            aplicarLarguraSalva('tk_larg_filas', cols[0]);
            cols[1].style.flex = '1 1 0';
            cols[1].style.minWidth = '0';
            if (cols.length >= 3) aplicarLarguraSalva('tk_larg_detalhe', cols[2]);

            function criarResizer(colAlvo, chave, cresceParaDireita, referencia, min, max) {
                const barra = doc.createElement('div');
                barra.className = 'tk-resizer';
                function posicionar() {
                    barra.style.left = (referencia.getBoundingClientRect().right
                                         - row.getBoundingClientRect().left) + 'px';
                }
                posicionar();
                row.appendChild(barra);

                barra.addEventListener('mousedown', function(e) {
                    e.preventDefault();
                    barra.classList.add('tk-ativo');
                    const larguraInicial = colAlvo.getBoundingClientRect().width;
                    const xInicial = e.clientX;
                    function mover(ev) {
                        const delta = cresceParaDireita ? (ev.clientX - xInicial) : -(ev.clientX - xInicial);
                        const nova = Math.max(min, Math.min(max, larguraInicial + delta));
                        colAlvo.style.flex = '0 0 ' + nova + 'px';
                        colAlvo.style.width = nova + 'px';
                        posicionar();
                    }
                    function soltar() {
                        barra.classList.remove('tk-ativo');
                        sessionStorage.setItem(chave, Math.round(colAlvo.getBoundingClientRect().width));
                        doc.removeEventListener('mousemove', mover);
                        doc.removeEventListener('mouseup', soltar);
                    }
                    doc.addEventListener('mousemove', mover);
                    doc.addEventListener('mouseup', soltar);
                });
            }

            // resizer 1: entre "Filas" (cols[0]) e "Lista" (cols[1])
            criarResizer(cols[0], 'tk_larg_filas', true, cols[0], 160, 420);
            // resizer 2 (só existe quando o Detalhe está aberto): entre
            // "Lista" (cols[1]) e "Detalhe" (cols[2])
            if (cols.length >= 3) {
                criarResizer(cols[2], 'tk_larg_detalhe', false, cols[1], 320, 900);
            }
            return true;
        }

        const tentativa = setInterval(function() {
            if (montarResizers()) clearInterval(tentativa);
        }, 120);
        setTimeout(function() { clearInterval(tentativa); }, 6000);
    })();
    </script>
    """, height=0, width=0)


# ═══════════════════════════════════════════════════════════════════
# RENDERIZAÇÃO
# ═══════════════════════════════════════════════════════════════════
def renderizar_tickets(papel: str, user: dict = None):
    if user is None:
        user = {"role": papel, "nome": "Usuário", "usuario": "user", "departamento": ""}

    todos_geral = listar_tickets()
    todos = [t for t in todos_geral if ticket_visivel(t, user, papel)]

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

    _render_estilo_paineis_redimensionaveis()

    st.markdown(_html("""
    <style>
    .tk-badge { background:#e2e8f0; color:#475569; padding:2px 8px;
        border-radius:10px; font-size:0.72rem; font-weight:700; }
    .tk-badge-red { background:#FBF3D9; color:#8A6D1F; }
    .tk-banner { animation: tkpiscar 1.2s infinite;
        background:#FBF3D9; color:#7A5C12; border:2px solid #8A6D1F;
        border-radius:10px; padding:12px 16px; margin-bottom:14px;
        font-weight:800; font-size:0.95rem; }
    @keyframes tkpiscar { 0%,100%{opacity:1;} 50%{opacity:.30;} }
    .tk-blink { animation: tkpiscar 1s infinite;
        background:#8A6D1F; color:#fff; padding:2px 10px; border-radius:12px;
        font-size:0.72rem; font-weight:800; display:inline-block; }
    .tk-equipe-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:14px 16px; margin-bottom:8px; border-top:4px solid #C9A84C; }
    .tk-blink-venc { animation:tkpiscar 1s infinite; background:#8A6D1F; color:#fff;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:800; }
    .tk-blink-warn { animation:tkpiscar 1.6s infinite; background:#FBF3D9; color:#7A5C12;
        border:1px solid #D4A12C; padding:1px 8px; border-radius:10px;
        font-size:0.7rem; font-weight:700; }
    .tk-blink-info { animation:tkpiscar 1.3s infinite; background:#DBEAFE; color:#1D4ED8;
        border:1px solid #60A5FA; padding:1px 8px; border-radius:10px;
        font-size:0.7rem; font-weight:800; }
    .tk-badge-val { background:#F3ECD9; color:#6B5A2A; border:1px solid #A98C3D;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:700; }
    .tk-badge-sla1-ok { background:#DCFCE7; color:#15803D; border:1px solid #16A34A;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:700; }
    .tk-badge-sla1-perd { background:#F3ECD9; color:#8A6D1F; border:1px solid #A98C3D;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:700; }
    .tk-setor-pill { padding:1px 9px; border-radius:10px; font-size:0.7rem;
        font-weight:800; color:#fff; display:inline-block; }
    .tk-setor-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:12px 14px; margin-bottom:10px; }

    /* ═══════════════════════════════════════════════════════════
       TIRINHA HORIZONTAL — padrão ÚNICO de card de ticket, usado em
       TODO lugar do sistema que mostra um ticket (Filas de Trabalho,
       abas por Departamento, Visão Geral por Atendente, SLA vencidos).
       Um único bloco de HTML (sem "costura" entre botão e conteúdo).
       ═══════════════════════════════════════════════════════════ */
    .tk-strip {
        background:#fff; border:1px solid #e2e8f0; border-left:5px solid #C9A84C;
        border-radius:10px; padding:10px 16px 8px; transition:box-shadow .15s;
    }
    .tk-strip-top { display:flex; align-items:center; gap:10px; flex-wrap:wrap;
        justify-content:space-between; }
    .tk-strip-id { font-weight:800; color:#2c3e50; font-size:0.85rem; white-space:nowrap; }
    .tk-strip-title { font-weight:700; color:#2c3e50; font-size:0.92rem; flex:1; min-width:180px; }
    .tk-strip-pills { white-space:nowrap; }
    .tk-strip-meta { font-size:0.76rem; color:#64778d; margin-top:5px; line-height:1.6; }
    .tk-strip-bottom { display:flex; align-items:center; gap:10px; margin-top:7px; }
    .tk-strip-slabar { flex:1; background:#e8ecf0; border-radius:4px; height:5px; }
    .tk-strip-slafill { height:5px; border-radius:4px; }
    .tk-strip-slatext { font-size:0.72rem; color:#64778d; white-space:nowrap; }

    /* Container que "embrulha" cada tirinha: recebe o botão invisível que
       cobre 100% da área, tornando o card inteiro clicável sem precisar de
       um botão visualmente separado do conteúdo (o que causava o efeito de
       "3 caixinhas soltas" na versão anterior). */
    div[class*="st-key-tkwrap_"] {
        position: relative;
        margin-bottom: 10px;
    }
    div[class*="st-key-tkwrap_"] div[data-testid="stButton"] {
        margin: 0 !important;
        height: 0 !important;
        min-height: 0 !important;
        overflow: visible !important;
    }
    div[class*="st-key-tkwrap_"] button {
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        height: 100% !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        opacity: 0;
        z-index: 5;
        cursor: pointer;
        padding: 0 !important;
    }
    div[class*="st-key-tkwrap_"]:hover .tk-strip {
        box-shadow: 0 2px 10px rgba(0,0,0,0.10);
    }

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
    [data-testid="stFormSubmitButton"] button {
        background-color:#C9A84C !important; border-color:#C9A84C !important; color:#fff !important; }
    [data-testid="stFormSubmitButton"] button:hover {
        background-color:#b8973f !important; border-color:#b8973f !important; color:#fff !important; }
    .stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
        border-color:#C9A84C !important; box-shadow:0 0 0 1px #C9A84C !important; }
    div[data-baseweb="select"] > div:focus-within,
    div[data-baseweb="select"] > div[aria-expanded="true"],
    div[data-baseweb="input"]:focus-within {
        border-color:#C9A84C !important; box-shadow:0 0 0 1px #C9A84C !important; }
    div[data-baseweb="base-input"] input { caret-color:#C9A84C !important; }
    </style>
    """), unsafe_allow_html=True)

    if "tk_fila"          not in st.session_state: st.session_state.tk_fila          = "meus"
    if "tk_ticket_aberto" not in st.session_state: st.session_state.tk_ticket_aberto  = None
    if "tk_modo"          not in st.session_state: st.session_state.tk_modo          = "lista"

    uname = user.get("usuario","")

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
    f_global  = todos_geral

    modo = st.session_state.tk_modo
    mostra_detalhe = bool(st.session_state.tk_ticket_aberto) and modo in ("lista", None)

    with st.container(key="tk_paineis"):
        if mostra_detalhe:
            col_filas, col_main, col_detalhe = st.columns([1, 2, 1.4])
        else:
            col_filas, col_main = st.columns([1, 3])
            col_detalhe = None

        with col_filas:
            st.markdown("**Ações**")
            if st.button("➕ Novo Ticket", use_container_width=True, type="primary"):
                st.session_state.tk_modo = "novo"; st.session_state.tk_ticket_aberto = None; st.rerun()

            if papel in ("supervisor", "adm"):
                if st.button("📊 Visão Geral da Operação", use_container_width=True,
                             type="primary" if st.session_state.tk_modo == "equipe" else "secondary"):
                    st.session_state.tk_modo = "equipe"; st.session_state.tk_ticket_aberto = None; st.rerun()

            if papel == "adm":
                if st.button("🔄 Sync Zendesk", use_container_width=True):
                    st.session_state.tk_modo = "sync"; st.session_state.tk_ticket_aberto = None; st.rerun()

            st.markdown('<div style="border-top:1px dashed #cbd5e1;margin:14px 0 6px;"></div>',
                        unsafe_allow_html=True)
            if st.button("📋 Ver Filas de Trabalho", use_container_width=True,
                         type="primary" if st.session_state.tk_modo in ("lista", None) else "secondary"):
                st.session_state.tk_modo = "lista"; st.rerun()

        with col_main:
            if f_venc:
                st.markdown(_html(
                    f'<div class="tk-banner">⏳ {len(f_venc)} ticket(s) com prazo ESTOURADO '
                    f'aguardando tratativa! Verifique a aba "SLA vencidos".</div>'
                ), unsafe_allow_html=True)

            if modo in ("lista", None):
                _render_filas_em_abas(user, papel, meus, f_abertos, f_andam, f_urg, f_venc, f_global)
            elif modo == "novo":
                _render_novo(user)
            elif modo == "equipe":
                if papel not in ("supervisor", "adm"):
                    st.warning("🔒 Acesso restrito a Supervisores e Administradores.")
                    st.session_state.tk_modo = "lista"
                else:
                    _render_visao_geral_operacao(user, papel, todos_geral)
            elif modo == "sync":
                _render_sync()

        if col_detalhe is not None:
            with col_detalhe:
                _render_painel_lateral_detalhe(user, papel)


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


# ───────────────────────────────────────────────────────────────────
# FILAS DE TRABALHO EM ABAS (queues próprias + abas de pendência por setor)
# ───────────────────────────────────────────────────────────────────
def _render_filas_em_abas(user, papel, meus, f_abertos, f_andam, f_urg, f_venc, f_global):
    busca = st.text_input("", placeholder="Busca global: ID, assunto, cliente, código, descrição, comentário...",
                          label_visibility="collapsed", key="tk_busca")
    b = busca.strip().lower() if busca else ""

    def _filtra(lista):
        return [t for t in lista if b in texto_busca(t)] if b else lista

    tab_defs = [
        ("meus",         "📌 Meus tickets", meus),
        ("aberto",       "Abertos",         f_abertos),
        ("em_andamento", "Em andamento",    f_andam),
        ("urgente",      "Urgentes",        f_urg),
        ("vencidos",     "SLA vencidos",    f_venc),
        ("global",       "🌐 Todos",        f_global),
    ]

    # Abas extras: uma por Departamento cadastrado. Mostra os tickets que
    # aquele setor precisa tratar: os abertos DIRETO pra ele (o caso comum)
    # + os que outro setor pediu pendência (transparência entre equipes).
    # Visível a QUALQUER atendente, não só de quem é dono do ticket.
    deps_cadastrados = [d.get("nome") for d in listar_departamentos() if d.get("nome")]
    dept_tab_defs = []
    for nome_dep in deps_cadastrados:
        pend_lista = tickets_pendentes_do_setor(f_global, nome_dep)
        qtd = len(pend_lista)
        label = f"{_swatch_dept(nome_dep)} {nome_dep} ({qtd})"
        dept_tab_defs.append((f"setor::{nome_dep}", label, pend_lista, nome_dep))

    labels = [lbl for _, lbl, _ in tab_defs] + [lbl for _, lbl, _, _ in dept_tab_defs]
    tabs = st.tabs(labels)

    for (chave, _lbl, lista), tab in zip(tab_defs, tabs[:len(tab_defs)]):
        with tab:
            filtrados = _filtra(lista)
            st.markdown(f"**{len(filtrados)} ticket(s)**")
            if not filtrados:
                st.info("Nenhum ticket nesta fila.")
            else:
                _render_lista_em_grid(filtrados, user, papel, chave)

    for (chave, _lbl, lista, nome_dep), tab in zip(dept_tab_defs, tabs[len(tab_defs):]):
        with tab:
            filtrados = _filtra(lista)
            cor = cor_departamento(nome_dep)
            st.markdown(_html(f"""
            <div style="font-size:0.82rem;color:#64778d;margin-bottom:8px;">
                Tickets que o setor <span class="tk-setor-pill" style="background:{cor};">{esc(nome_dep)}</span>
                precisa tratar: os abertos diretamente para ele + os que outro setor pediu
                retorno. Qualquer atendente pode ver esta fila — é uma visão de
                transparência entre equipes, o ticket continua único.
            </div>"""), unsafe_allow_html=True)
            st.markdown(f"**{len(filtrados)} ticket(s) pendente(s) com {nome_dep}**")
            if not filtrados:
                st.info(f"Nenhuma pendência aberta para {nome_dep} no momento.")
            else:
                _render_lista_pendencias_setor(filtrados, nome_dep, user, papel, chave)


def _render_lista_pendencias_setor(lista, nome_dep, user, papel, chave):
    pagina_itens, pag_atual, total_paginas, pag_key, total = _paginar(lista, f"pend_{chave}")
    for t in pagina_itens:
        tid = t.get("id","")
        dep_origem = t.get("departamento") or t.get("categoria") or "—"
        eh_dono = dep_origem == nome_dep
        pedidos_abertos = solicitacoes_abertas_para_setor(t, nome_dep)

        # Tag de origem — mesma tirinha padrão do resto do sistema, só que
        # com esta tag extra pra deixar claro se o chamado nasceu neste
        # setor ou veio pedido de outro.
        cor = cor_departamento(nome_dep)
        if eh_dono:
            tag_origem = f'<span class="tk-setor-pill" style="background:{cor};">🏠 aberto aqui</span> '
        else:
            cor_o = cor_departamento(dep_origem)
            tag_origem = (f'<span class="tk-setor-pill" style="background:{cor_o};">'
                          f'↩ vindo de {esc(dep_origem)}</span> ')

        _render_ticket_strip(t, user, papel, key_ctx=f"setor_{chave}_{tid}",
                             extra_badge_html=tag_origem)

        if eh_dono and not pedidos_abertos:
            st.caption("🏠 Chamado aberto diretamente neste setor — aguardando tratativa/classificação.")

        for pedido in pedidos_abertos:
            st.markdown(_html(f"""
            <div style="border-left:3px solid {cor};background:#fafafa;border-radius:6px;
                        padding:8px 10px;margin:6px 0;">
                <span class="tk-setor-pill" style="background:{cor_departamento(pedido.get('setor_origem',''))};">
                    {esc(pedido.get('setor_origem',''))}
                </span>
                <span style="font-size:0.78rem;color:#64778d;"> pediu em
                {esc(str(pedido.get('solicitado_em',''))[:16])} ({esc(pedido.get('solicitado_por_nome',''))}):</span>
                <div style="font-size:0.85rem;color:#2c3e50;margin-top:2px;">{esc(pedido.get('mensagem',''))}</div>
            </div>"""), unsafe_allow_html=True)

            dep_user = user.get("departamento")
            pode_responder = (papel in ("supervisor", "adm")) or (dep_user == nome_dep)
            if pode_responder:
                with st.form(f"form_resp_{chave}_{tid}_{pedido.get('id')}", clear_on_submit=True):
                    resp_txt = st.text_area("Resposta", height=70, key=f"resp_txt_{tid}_{pedido.get('id')}",
                                            placeholder="Escreva a resposta pro setor solicitante...")
                    if st.form_submit_button(f"✅ Responder e concluir pendência ({nome_dep})",
                                             type="primary", use_container_width=True):
                        if resp_txt.strip():
                            responder_solicitacao_setor(tid, pedido, resp_txt.strip(), user)
                            st.success("Pendência respondida!"); time.sleep(.6); st.rerun()
                        else:
                            st.warning("Escreva uma resposta antes de concluir.")
    _nav_paginas(pag_atual, total_paginas, pag_key, total)


# ───────────────────────────────────────────────────────────────────
# TIRINHA HORIZONTAL — componente ÚNICO de card de ticket
# ───────────────────────────────────────────────────────────────────
def _badges_ticket(t, user) -> str:
    """Badges/alertas coloridos do ticket — usados em QUALQUER lugar do
    sistema que mostre a tirinha do ticket: vencido, aviso de <30min,
    validação pendente, nova interação não vista e pendências abertas com
    outros setores."""
    estado = sla_estado(t)
    badge = ""
    if estado == "venc":
        badge += '<span class="tk-blink-venc">⛔ PRAZO VENCIDO</span> '
    elif estado == "warn":
        badge += '<span class="tk-blink-warn">⏰ Faltam &lt; 30min</span> '
    if t.get("status") == "resolvido" and t.get("aberto_por") == user.get("usuario") \
            and resolvido_em_validacao(t):
        badge += '<span class="tk-badge-val">✔ valide este chamado</span> '
    if tem_interacao_nao_vista(t, user):
        badge += '<span class="tk-blink-info">🔵 Nova interação</span> '
    for pend in solicitacoes_abertas(t):
        cor_pend = cor_departamento(pend.get("setor_destino",""))
        badge += (f'<span class="tk-setor-pill" style="background:{cor_pend};">'
                  f'📨 aguarda {esc(pend.get("setor_destino",""))}</span> ')
    return badge


def _render_ticket_strip(t, user, papel, key_ctx, extra_badge_html=""):
    """
    TIRINHA HORIZONTAL — padrão ÚNICO de card de ticket usado em TODO o
    sistema (Filas de Trabalho, abas por Departamento, Visão Geral por
    Atendente, SLA vencidos). Um único bloco de HTML (sem "costura" visual
    entre botão e conteúdo) com TODAS as informações e cores já existentes:
    ícone de origem, ID, título, departamento, motivo (pai › filho › etapa),
    cliente, nº de comentários, data de criação, pill de status, pill de
    prioridade, badges (vencido / aviso <30min / validação pendente / nova
    interação / pendências de setor) e a barra + texto do SLA/prazo ativo.

    O card inteiro é clicável — um botão invisível cobre toda a tirinha via
    CSS (ver `st-key-tkwrap_` no bloco de estilos). O clique NÃO abre mais
    popup: apenas define qual ticket está "aberto" no estado da sessão, e a
    coluna de Detalhe (terceira coluna, à direita) aparece/atualiza sozinha.

    extra_badge_html: badge(s) adicional(is) específico(s) do contexto (ex.:
    a tag "🏠 aberto aqui" / "↩ vindo de X" usada na aba de um Departamento).
    """
    tid    = t.get("id","")
    estado = sla_estado(t)
    sl, spct, svenc = sla_restante(t)
    sv_label, sbg, sc, _ = STATUS_CFG.get(t.get("status","aberto"), ("—","#fff","#000","#000"))
    pv_label, pbg, pc    = PRIO_CFG.get(t.get("prioridade","normal"), ("—","#fff","#000"))
    icon    = "🔗" if "zendesk" in t.get("origem","") else "🏠"
    idv     = t.get("id_zendesk", tid[:8])
    titulo  = str(t.get("assunto","Sem título"))[:75]
    dep     = t.get("departamento") or t.get("categoria") or "—"
    caminho_mot = _caminho_motivo(t)
    cliente = t.get("cliente_nome") or t.get("solicitante_nome") or "—"
    cli_cod = t.get("cliente_codigo")
    cliente_txt = cliente + (f" ({cli_cod})" if cli_cod else "")
    num_com = len(t.get("comentarios", []))
    criado  = str(t.get("criado_em",""))[:16]

    ticket_aberto_agora = (tid == st.session_state.get("tk_ticket_aberto"))

    if   estado == "venc": barra = GOLD_VENC
    elif estado == "warn": barra = GOLD_WARN
    elif spct > 70:        barra = "#CA8A04"
    else:                  barra = "#16A34A"

    borda = GOLD_VENC if estado == "venc" else ("#D4A12C" if estado == "warn" else "#C9A84C")
    sombra_extra = "box-shadow:0 0 0 2px #2563EB inset;" if ticket_aberto_agora else ""
    badges   = (extra_badge_html or "") + _badges_ticket(t, user)
    meta_com = f" &nbsp;·&nbsp; 💬 {num_com}" if num_com else ""
    meta_mot = f" &nbsp;·&nbsp; 📂 {esc(caminho_mot)}" if caminho_mot else ""

    with st.container(key=f"tkwrap_{key_ctx}"):
        st.markdown(_html(f"""
        <div class="tk-strip" style="border-left-color:{borda};{sombra_extra}">
            <div class="tk-strip-top">
                <span class="tk-strip-id">{icon} #{esc(idv)}</span>
                <span class="tk-strip-title">{esc(titulo)}</span>
                <span class="tk-strip-pills">{pill(sv_label,sbg,sc)} {pill(pv_label,pbg,pc)}</span>
            </div>
            <div class="tk-strip-meta">
                🏢 {esc(dep)} &nbsp;·&nbsp; 🧾 {esc(cliente_txt)}{meta_com}{meta_mot}
                &nbsp;·&nbsp; 🕐 {esc(criado)} &nbsp; {badges}
            </div>
            <div class="tk-strip-bottom">
                <div class="tk-strip-slabar">
                    <div class="tk-strip-slafill" style="width:{spct:.0f}%;background:{barra};"></div>
                </div>
                <div class="tk-strip-slatext">{esc(sla_label(t))}: <b style="color:{barra};">{esc(sl)}</b></div>
            </div>
        </div>
        """), unsafe_allow_html=True)
        if st.button("", key=f"tkbtn_{key_ctx}", use_container_width=True):
            st.session_state.tk_ticket_aberto = tid
            st.rerun()


# ───────────────────────────────────────────────────────────────────
# COMPONENTES
# ───────────────────────────────────────────────────────────────────
def _render_lista_em_grid(filtrados, user, papel, fila):
    modo_agrupar = st.selectbox(
        "🗂️ Organizar por",
        ["Motivo Pai", "Departamento", "Sem agrupamento"],
        index=0, key=f"tk_agrupar_{fila}"
    )

    from collections import defaultdict
    grupos = defaultdict(list)
    if modo_agrupar == "Departamento":
        for t in filtrados:
            grupos[t.get("departamento") or t.get("categoria") or "—"].append(t)
    elif modo_agrupar == "Motivo Pai":
        for t in filtrados:
            grupos[t.get("motivo_pai") or t.get("tabulacao") or "Sem motivo"].append(t)
    else:
        grupos["__todos__"] = filtrados

    for chave in sorted(grupos.keys()):
        lst = grupos[chave]
        n_venc = sum(1 for t in lst if ticket_vencido_pendente(t))
        n_pend_setor = sum(1 for t in lst if solicitacoes_abertas(t))
        extra = (f' · <span style="color:#8A6D1F;font-weight:700;">⏳ {n_venc} com prazo '
                 f'estourado</span>') if n_venc else ""
        extra += (f' · <span style="color:#2563EB;font-weight:700;">📨 {n_pend_setor} com '
                  f'pendência de setor</span>') if n_pend_setor else ""

        if modo_agrupar != "Sem agrupamento":
            icone = "📋" if modo_agrupar == "Motivo Pai" else "🏢"
            st.markdown(_html(
                f'<div style="margin:14px 0 6px;font-weight:700;color:#2c3e50;">'
                f'{icone} {esc(chave)} <span style="color:#64778d;font-weight:500;">— '
                f'{len(lst)} ticket(s)</span>{extra}</div>'), unsafe_allow_html=True)

        pagina_itens, pag_atual, total_paginas, pag_key, total = _paginar(
            lst, f"lista_{fila}_{chave}"
        )
        for t in pagina_itens:
            _render_ticket_strip(t, user, papel, key_ctx=f"{fila}_{chave}_{t.get('id','')}")
        _nav_paginas(pag_atual, total_paginas, pag_key, total)


def _caminho_motivo(t) -> str:
    partes = [p for p in [t.get("motivo_pai"), t.get("motivo_filho"), t.get("etapa_atual")] if p]
    return " › ".join(partes) if partes else ""


def _carregar_e_render_detalhe(tid, user, papel, modal=False):
    if not tid:
        return
    doc = get_db().collection(COLECAO).document(tid).get()
    if not doc.exists:
        st.error("Ticket não encontrado.")
        return
    _detalhe_corpo(doc.to_dict(), tid, user, papel)


def _render_painel_lateral_detalhe(user, papel):
    """Coluna da direita (3ª coluna) com o detalhe do ticket clicado — em
    vez do antigo popup/st.dialog. Só é chamada quando há um ticket aberto
    no estado da sessão (tk_ticket_aberto)."""
    tid = st.session_state.get("tk_ticket_aberto")
    if not tid:
        return
    c_tit, c_fechar = st.columns([5, 1])
    with c_tit:
        st.markdown("### 📄 Detalhe do Ticket")
    with c_fechar:
        if st.button("✕", key="tk_fechar_detalhe", help="Fechar", use_container_width=True):
            st.session_state.tk_ticket_aberto = None
            st.rerun()
    _carregar_e_render_detalhe(tid, user, papel, modal=True)


# ── Classificação Motivo Filho / Etapa (SLA1 + SLA2) ───────────────
def _bloco_classificacao(t, tid, user, papel, pode_agir):
    motivo_pai_nome = t.get("motivo_pai")
    if not motivo_pai_nome:
        return  # ticket antigo/legado (sem árvore de motivos) — não se aplica

    st.markdown("---")
    st.markdown("#### 🗂️ Classificação (Motivo Filho / Etapa)")

    if t.get("etapa_travada"):
        st.markdown(_html(f"""
        <div style="background:#F3ECD9;border:1px solid #A98C3D;border-radius:10px;
                    padding:10px 14px;color:#6B5A2A;">
            🔒 <b>{esc(motivo_pai_nome)} › {esc(t.get('motivo_filho',''))} › {esc(t.get('etapa_atual',''))}</b><br>
            <span style="font-size:0.8rem;">Prazo desta etapa: <b>{esc(str(t.get('etapa_data_prevista','—')))}</b>
            &nbsp;·&nbsp; Definido em {esc(str(t.get('etapa_definida_em',''))[:16])} por
            {esc(t.get('etapa_definida_por',''))}. Esta trilha não pode mais ser alterada.</span>
        </div>"""), unsafe_allow_html=True)
        return

    if not pode_agir:
        if t.get("motivo_filho"):
            st.caption(f"📂 {esc(motivo_pai_nome)} › {esc(t.get('motivo_filho'))} › {esc(t.get('etapa_atual',''))}")
        else:
            st.caption(f"📂 {esc(motivo_pai_nome)} — aguardando classificação do atendente.")
        return

    filhos = listar_motivos_filho_de(t.get("motivo_pai_id",""))
    if not filhos:
        st.caption("Nenhum Motivo Filho cadastrado para este Motivo Pai ainda "
                   "(cadastre em Configurações → Motivos).")
        return

    filho_nomes = [f["nome"] for f in filhos]
    idx_f = filho_nomes.index(t["motivo_filho"]) if t.get("motivo_filho") in filho_nomes else 0
    filho_sel_nome = st.selectbox("Motivo Filho", filho_nomes, index=idx_f, key=f"mf_{tid}")
    filho_obj = next(f for f in filhos if f["nome"] == filho_sel_nome)

    caminho_salvo = t.get("etapa_atual","").split(" › ") if t.get("etapa_atual") else []
    caminho = []
    filho_atual = filho_obj
    etapa_final = None
    nivel = 0
    while True:
        etapas = listar_etapas_de(filho_atual["id"])
        if not etapas:
            break
        etapa_nomes = [e["nome"] for e in etapas]
        prev_nome = caminho_salvo[nivel] if nivel < len(caminho_salvo) else None
        idx_e = etapa_nomes.index(prev_nome) if prev_nome in etapa_nomes else 0
        label = "Etapa" if nivel == 0 else f"Etapa (nível {nivel+1})"
        etapa_sel_nome = st.selectbox(label, etapa_nomes, index=idx_e, key=f"et_{tid}_{nivel}")
        etapa_obj = next(e for e in etapas if e["nome"] == etapa_sel_nome)
        caminho.append(etapa_obj["nome"])
        if etapa_obj.get("reaproveita_motivo_filho_id"):
            alvo = next((f for f in listar_motivos_filho() if f["id"] == etapa_obj["reaproveita_motivo_filho_id"]), None)
            if not alvo:
                etapa_final = etapa_obj
                break
            filho_atual = alvo
            nivel += 1
            continue
        etapa_final = etapa_obj
        break

    if etapa_final is None:
        st.caption("Este Motivo Filho ainda não tem Etapas cadastradas.")
        return

    dep_proprio = t.get("departamento") or t.get("categoria") or ""
    dep_vinc_classificacao = etapa_final.get("departamento_vinculado") or filho_obj.get("departamento_vinculado")
    if dep_vinc_classificacao and dep_vinc_classificacao != dep_proprio \
            and not ticket_tem_pendencia_para_setor(t, dep_vinc_classificacao):
        st.markdown(_html(f"""
        <div class="tk-banner" style="animation:none;background:#EFF6FF;color:#1D4ED8;border-color:#60A5FA;">
            📨 Esta classificação é vinculada ao setor <b>{esc(dep_vinc_classificacao)}</b> —
            ao confirmar, uma pendência será criada automaticamente para eles.
        </div>"""), unsafe_allow_html=True)

    vermelha = bool(etapa_final.get("requer_data"))
    data_prevista = None
    if vermelha:
        st.markdown('<span class="tk-blink-warn">🔴 Esta etapa exige um prazo (2º SLA)</span>',
                    unsafe_allow_html=True)
        data_prevista = st.date_input(
            "Data prevista (obrigatória, futura) *",
            min_value=datetime.now(BRT).date() + timedelta(days=1),
            key=f"dt_{tid}"
        )
        st.caption("⚠️ Após confirmar, esta trilha (Motivo Filho + Etapa + Data) fica "
                   "TRAVADA — não será mais possível alterar. Só confirme se realmente "
                   "precisa desse prazo; caso contrário, resolva o ticket normalmente.")

    label_confirmar = "🔒 Confirmar etapa e travar prazo" if vermelha else "✅ Definir etapa"
    if st.button(label_confirmar, key=f"confirmar_etapa_{tid}", type="primary"):
        agora = agora_brt()
        updates = {
            "motivo_filho": filho_obj["nome"],
            "etapa_atual": " › ".join(caminho),
            "etapa_vermelha": vermelha,
        }
        if not t.get("sla1_definido"):
            limite_pai, _ = deadline_ativo({**t, "etapa_vermelha": False, "etapa_data_prevista": None})
            cumprido = (datetime.now(BRT) <= limite_pai) if limite_pai else True
            updates["sla1_definido"]    = True
            updates["sla1_cumprido"]    = cumprido
            updates["sla1_definido_em"] = agora
        if vermelha:
            updates["etapa_data_prevista"] = data_prevista.isoformat()
            updates["etapa_definida_em"]   = agora
            updates["etapa_definida_por"]  = user.get("nome","")
            updates["etapa_travada"]       = True
        if etapa_final.get("atendentes_vinculados"):
            updates["atendentes"]     = etapa_final["atendentes_vinculados"]
            updates["atribuido_para"] = etapa_final["atendentes_vinculados"][0]

        from google.cloud.firestore import ArrayUnion
        updates["historico_etapas"] = ArrayUnion([{
            "etapa": " › ".join(caminho), "quando": agora,
            "por": user.get("nome",""), "vermelha": vermelha,
            "data_prevista": data_prevista.isoformat() if vermelha else None,
        }])
        atualizar_ticket(tid, updates, interacao_de=user.get("usuario",""))

        msg_extra = ""
        if dep_vinc_classificacao and dep_vinc_classificacao != dep_proprio \
                and not ticket_tem_pendencia_para_setor(t, dep_vinc_classificacao):
            registrar_solicitacao_setor(
                tid, t, dep_vinc_classificacao,
                f"Pendência automática: a classificação '{' › '.join(caminho)}' exige "
                f"retorno do setor {dep_vinc_classificacao} para este chamado ser concluído.",
                user,
            )
            msg_extra = f" 📨 Pendência automática registrada para o setor **{dep_vinc_classificacao}**."

        st.success("Classificação registrada!" + (" Prazo travado." if vermelha else "") + msg_extra)
        time.sleep(.6); st.rerun()


# ── Pendências entre Setores (dentro do ticket) ────────────────────
def _bloco_pendencias_setor(t, tid, user, papel):
    st.markdown("---")
    st.markdown("#### 📨 Pendências entre Setores")
    st.caption("Peça pra outro setor resolver algo sem abrir um chamado novo — fica "
               "tudo registrado aqui, dentro deste mesmo ticket.")

    todas = t.get("solicitacoes_setor", []) or []
    pedidos = {s["id"]: s for s in todas if s.get("tipo") == "pedido"}
    respostas_por_pedido = {}
    for s in todas:
        if s.get("tipo") == "resposta":
            respostas_por_pedido.setdefault(s.get("pedido_id"), []).append(s)

    if pedidos:
        for pid, pedido in sorted(pedidos.items(), key=lambda kv: kv[1].get("solicitado_em","")):
            cor_o = cor_departamento(pedido.get("setor_origem",""))
            cor_d = cor_departamento(pedido.get("setor_destino",""))
            aberto = pid not in respostas_por_pedido
            st.markdown(_html(f"""
            <div class="tk-setor-card" style="border-left:4px solid {cor_d};">
                <span class="tk-setor-pill" style="background:{cor_o};">{esc(pedido.get('setor_origem',''))}</span>
                ➜
                <span class="tk-setor-pill" style="background:{cor_d};">{esc(pedido.get('setor_destino',''))}</span>
                {"<span class='tk-blink-warn' style='margin-left:6px;'>⏳ aguardando resposta</span>" if aberto else ""}
                <div style="font-size:0.78rem;color:#64778d;margin-top:6px;">
                    Solicitado por {esc(pedido.get('solicitado_por_nome',''))} em
                    {esc(str(pedido.get('solicitado_em',''))[:16])}
                </div>
                <div style="font-size:0.88rem;color:#2c3e50;margin-top:4px;">{esc(pedido.get('mensagem',''))}</div>
            </div>"""), unsafe_allow_html=True)

            for resp in respostas_por_pedido.get(pid, []):
                cor_r = cor_departamento(resp.get("setor_origem",""))
                st.markdown(_html(f"""
                <div class="tk-setor-card" style="border-left:4px solid {cor_r};margin-left:22px;background:#fafafa;">
                    <span class="tk-setor-pill" style="background:{cor_r};">✅ {esc(resp.get('setor_origem',''))} respondeu</span>
                    <div style="font-size:0.78rem;color:#64778d;margin-top:6px;">
                        Por {esc(resp.get('respondido_por_nome',''))} em {esc(str(resp.get('respondido_em',''))[:16])}
                    </div>
                    <div style="font-size:0.88rem;color:#2c3e50;margin-top:4px;">{esc(resp.get('resposta',''))}</div>
                </div>"""), unsafe_allow_html=True)

            dep_user = user.get("departamento")
            pode_responder = aberto and ((papel in ("supervisor", "adm")) or (dep_user == pedido.get("setor_destino")))
            if pode_responder:
                with st.form(f"form_resp_det_{tid}_{pid}", clear_on_submit=True):
                    resp_txt = st.text_area("Responder esta pendência", height=70, key=f"respdet_{tid}_{pid}")
                    if st.form_submit_button(f"✅ Responder ({pedido.get('setor_destino')})",
                                             type="primary", use_container_width=True):
                        if resp_txt.strip():
                            responder_solicitacao_setor(tid, pedido, resp_txt.strip(), user)
                            st.success("Pendência respondida!"); time.sleep(.6); st.rerun()
                        else:
                            st.warning("Escreva uma resposta antes de concluir.")
    else:
        st.caption("Nenhuma pendência de setor registrada neste ticket ainda.")

    with st.expander("📨 Solicitar retorno de um setor"):
        deps_nomes = [d.get("nome") for d in listar_departamentos() if d.get("nome")]
        dep_proprio = t.get("departamento") or t.get("categoria") or ""
        opcoes = [d for d in deps_nomes if d != dep_proprio] or deps_nomes
        if not opcoes:
            st.caption("Cadastre Departamentos em Configurações para poder solicitar.")
        else:
            with st.form(f"form_solic_{tid}", clear_on_submit=True):
                setor_dest = st.selectbox("Setor que precisa responder", opcoes, key=f"setordest_{tid}")
                msg = st.text_area("O que você precisa deste setor?", height=80, key=f"msgsolic_{tid}")
                if st.form_submit_button("📨 Enviar solicitação", type="primary", use_container_width=True):
                    if msg.strip():
                        registrar_solicitacao_setor(tid, t, setor_dest, msg.strip(), user)
                        st.success(f"Solicitação enviada para {setor_dest}!"); time.sleep(.6); st.rerun()
                    else:
                        st.warning("Escreva o que você precisa antes de enviar.")


def _detalhe_corpo(t, tid, user, papel):
    sl, spct, svenc = sla_restante(t)
    sv, sbg, sc, _  = STATUS_CFG.get(t.get("status","aberto"),("—","#fff","#000","#000"))
    pv, pbg, pc     = PRIO_CFG.get(t.get("prioridade","normal"),("—","#fff","#000"))
    sla_cor = GOLD_VENC if svenc else ("#CA8A04" if spct>70 else GREEN_OK)
    pendente_vencido = ticket_vencido_pendente(t)

    if pendente_vencido:
        st.markdown(_html('<div class="tk-banner">⚠️ Este ticket está com o prazo VENCIDO!</div>'),
                    unsafe_allow_html=True)

    if tem_interacao_nao_vista(t, user):
        st.markdown(
            '<span class="tk-blink-info">🔵 Houve uma nova interação neste ticket que você '
            'ainda não respondeu</span>', unsafe_allow_html=True
        )

    id_vis = esc(t.get("id_zendesk", tid[:8]))
    titulo = esc(t.get("assunto","—"))
    dep    = esc(t.get("departamento") or t.get("categoria") or "—")
    caminho_mot = esc(_caminho_motivo(t)) or esc(t.get("motivo_pai") or "—")
    criado = esc(t.get("criado_em","")[:16])
    atend  = t.get("atendentes", [])
    atend_str = esc(", ".join(atend)) if atend else "🌐 Todo o departamento"
    cli_cod  = esc(t.get("cliente_codigo") or "—")
    cli_nome = esc(t.get("cliente_nome") or "—")
    solicit  = esc(t.get("solicitante_nome") or "—")

    sla1_badge = ""
    if t.get("sla1_definido"):
        if t.get("sla1_cumprido"):
            sla1_badge = '<span class="tk-badge-sla1-ok">🎯 Triagem: dentro do prazo</span>'
        else:
            sla1_badge = '<span class="tk-badge-sla1-perd">🎯 Triagem: prazo perdido</span>'

    pendencias_badges = ""
    for pend in solicitacoes_abertas(t):
        cor_pend = cor_departamento(pend.get("setor_destino",""))
        pendencias_badges += (f' <span class="tk-setor-pill" style="background:{cor_pend};">'
                              f'📨 aguarda {esc(pend.get("setor_destino",""))}</span>')

    st.markdown(_html(f"""
    <div style="background:#fff;border:1px solid #e2e8f0;border-left:6px solid {sla_cor if pendente_vencido else '#C9A84C'};
                border-radius:12px;padding:18px 20px;margin-bottom:16px;">
        <h3 style="margin:0 0 6px;color:#2c3e50;">#{id_vis} — {titulo}</h3>
        <div style="margin-bottom:10px;">
            {pill(sv,sbg,sc)} {pill(pv,pbg,pc)} {sla1_badge}{pendencias_badges}
            <span style="font-size:0.78rem;color:#64778d;margin-left:8px;">
                🏢 {dep} &nbsp;·&nbsp; 📂 {caminho_mot} &nbsp;·&nbsp; {criado}
            </span>
        </div>
        <div style="font-size:0.8rem;color:#2c3e50;margin-bottom:6px;">
            🧾 Cliente: <b>{cli_nome}</b> &nbsp;·&nbsp; Código: <b>{cli_cod}</b>
        </div>
        <div style="font-size:0.78rem;color:#64778d;margin-bottom:8px;">
            🙋 Solicitante: {solicit} &nbsp;·&nbsp; 👥 Atendentes: {atend_str}
            &nbsp;·&nbsp; ⏱ {esc(sla_label(t))}: <b style="color:{sla_cor};">{esc(sl)}</b>
        </div>
    </div>"""), unsafe_allow_html=True)

    relacionados = tickets_do_cliente(t.get("cliente_codigo"), excluir_id=tid)
    if relacionados:
        abertos_rel = sum(1 for x in relacionados if x.get("status") in STATUS_ABERTOS)
        with st.expander(
            f"🗂 Histórico do cliente — {len(relacionados)} outro(s) chamado(s)"
            + (f" ({abertos_rel} em aberto)" if abertos_rel else ""),
            expanded=False
        ):
            _render_bloco_historico_cliente(relacionados)

    st.markdown("**📝 Descrição**")
    st.text_area("Descrição", value=str(t.get("descricao") or t.get("assunto","—")),
                 height=140, disabled=True, label_visibility="collapsed",
                 key=f"desc_{tid}")

    status_atual = t.get("status", "aberto")
    terminal     = status_atual in ("finalizado", "cancelado")
    finalizado   = status_atual == "finalizado"
    pode_agir    = (papel in ("supervisor", "adm")) or _atribuido_a(t, user)
    status_edit  = pode_agir and not terminal
    STATUS_OPC   = [k for k in STATUS_CFG.keys() if k != "finalizado"]

    # ── Classificação Motivo Filho / Etapa (SLA1 congelado / SLA2 travado) ──
    _bloco_classificacao(t, tid, user, papel, pode_agir and not terminal)

    # ── Pendências entre Setores (não cria ticket novo, mesmo histórico) ──
    if not terminal:
        _bloco_pendencias_setor(t, tid, user, papel)

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
                st.markdown(pill(pv, pbg, pc), unsafe_allow_html=True)

            novo_com = st.text_area("Escrever resposta / comentário", height=90,
                                    placeholder="Digite a tratativa...", key=f"com_{tid}")
            enviar = st.form_submit_button("Enviar", type="primary", use_container_width=True)

            if enviar:
                updates = {}
                if status_edit and novo_status != status_atual:
                    updates["status"] = novo_status
                tem_com = bool(novo_com and novo_com.strip())
                if tem_com:
                    adicionar_comentario(tid, user.get("nome",""), user.get("usuario",""),
                                          novo_com.strip())
                if updates:
                    atualizar_ticket(tid, updates, interacao_de=user.get("usuario",""))
                if tem_com or updates:
                    msg = "Enviado!"
                    if updates.get("status") == "resolvido":
                        msg = ("✅ Ticket marcado como Resolvido! Saiu das suas tratativas e "
                               "permanece em 'Todos os tickets'.")
                    st.success(msg); time.sleep(.5)
                    if updates.get("status") in ("resolvido", "cancelado"):
                        st.session_state.tk_ticket_aberto = None
                    st.rerun()
                else:
                    st.warning("Escreva uma resposta ou altere o status antes de enviar.")

    # ── Registro de contato/observação avulsa (qualquer pessoa com acesso) ──
    if not finalizado:
        with st.expander("💬 Registrar um contato/observação (visível ao responsável)"):
            st.caption("Use isto se você teve contato com o cliente sobre este caso mas "
                       "não é o responsável formal pela tratativa. O responsável vai ver "
                       "um alerta 🔵 de nova interação até responder.")
            nota = st.text_area("O que você conversou ou observou?", key=f"nota_{tid}")
            if st.button("Registrar observação", key=f"btnnota_{tid}"):
                if nota.strip():
                    adicionar_comentario(tid, user.get("nome",""), user.get("usuario",""),
                                          f"📎 {nota.strip()}")
                    st.success("Registrado!"); time.sleep(.5); st.rerun()
                else:
                    st.warning("Escreva algo antes de registrar.")

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

    if t.get("historico_etapas"):
        with st.expander("🗂️ Histórico de classificação (Motivo Filho / Etapa)"):
            for h in t["historico_etapas"]:
                marca = "🔴" if h.get("vermelha") else "⚫"
                prazo = f" · prazo: {h.get('data_prevista')}" if h.get("vermelha") else ""
                st.caption(f"{marca} {h.get('etapa','')} — por {h.get('por','')} "
                           f"em {str(h.get('quando',''))[:16]}{prazo}")

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
            atualizar_ticket(tid, {"status": "finalizado"}, interacao_de=user.get("usuario",""))
            st.success("Chamado encerrado!"); time.sleep(.5)
            st.session_state.tk_ticket_aberto = None; st.rerun()
        if cvb.button("↩️ Reabrir chamado", key=f"reab_{tid}", use_container_width=True):
            atualizar_ticket(tid, {"status": "em_andamento"}, interacao_de=user.get("usuario",""))
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

    dep_sel = st.selectbox("Departamento *", dep_nomes, key="novo_dep")

    pais_dep = motivos_pai_do_departamento(dep_sel)
    if not pais_dep:
        st.info("Este departamento ainda não tem Motivos cadastrados. Peça ao administrador "
                "para cadastrar em Configurações → Motivos. Será usado um SLA padrão de 5 dias.")
        motivo_obj = None
        sla_dias = 5
    else:
        pai_nomes = [m["nome"] for m in pais_dep]
        pai_sel = st.selectbox("Motivo *", pai_nomes, key="novo_motivo_pai")
        motivo_obj = next(m for m in pais_dep if m["nome"] == pai_sel)
        sla_dias = int(motivo_obj.get("sla_dias", 5))

    st.caption(f"⏱ Prazo para triagem (1º SLA): **{sla_dias} dia(s)**. O atendente que "
               f"receber o chamado tem esse prazo para analisar e classificar a Etapa correta.")

    dep_vinculado_pai = motivo_obj.get("departamento_vinculado") if motivo_obj else None
    if dep_vinculado_pai and dep_vinculado_pai != dep_sel:
        st.markdown(_html(f"""
        <div class="tk-banner" style="animation:none;background:#EFF6FF;color:#1D4ED8;border-color:#60A5FA;">
            📨 Este motivo é vinculado ao setor <b>{esc(dep_vinculado_pai)}</b> — uma pendência
            será criada automaticamente para eles assim que o chamado for aberto (sem precisar
            solicitar manualmente).
        </div>"""), unsafe_allow_html=True)

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

        st.caption(f"🙋 Solicitante (automático): **{user.get('nome','—')}**")

        if st.form_submit_button("🚀 Abrir Chamado", type="primary", use_container_width=True):
            if not assunto.strip() or not descricao.strip():
                st.error("Preencha Assunto e Descrição.")
            elif not cod_norm or not cli_nome.strip():
                st.error("Informe o Código e o Nome do cliente.")
            else:
                novo_id = criar_ticket({
                    "assunto": assunto.strip(), "descricao": descricao.strip(),
                    "departamento": dep_sel,
                    "categoria": dep_sel,
                    "motivo_pai": motivo_obj["nome"] if motivo_obj else "",
                    "motivo_pai_id": motivo_obj["id"] if motivo_obj else "",
                    "sla1_prazo_dias": sla_dias,
                    "prioridade": (motivo_obj.get("prioridade", "normal") if motivo_obj else "normal"),
                    "atendentes": [],
                    "cliente_codigo": cod_norm,
                    "cliente_nome": cli_nome.strip(),
                    "solicitante_nome": user.get("nome",""),
                    "aberto_por": user.get("usuario",""),
                    "tickets_relacionados": [x.get("id") for x in tickets_cliente],
                })
                for tc in tickets_cliente:
                    if tc.get("id"):
                        vincular_ticket_relacionado(tc["id"], novo_id)

                aviso_pend = ""
                dep_vinc = motivo_obj.get("departamento_vinculado") if motivo_obj else None
                if dep_vinc and dep_vinc != dep_sel:
                    registrar_solicitacao_setor(
                        novo_id, {"departamento": dep_sel}, dep_vinc,
                        f"Pendência automática: o motivo '{motivo_obj['nome']}' exige retorno "
                        f"do setor {dep_vinc} para este chamado ser concluído.",
                        user,
                    )
                    aviso_pend = f" 📨 Pendência automática registrada para o setor **{dep_vinc}**."

                aviso_hist = (f" 🗂 Amarrado ao histórico de {len(tickets_cliente)} "
                              f"chamado(s) anterior(es) deste cliente."
                              if tickets_cliente else "")
                st.success(f"✅ Chamado **#{novo_id[:8]}** aberto em **{dep_sel}**! "
                           f"Aguardando triagem.{aviso_hist}{aviso_pend}")
                st.balloons(); time.sleep(1.5)
                st.session_state.tk_modo = "lista"; st.rerun()


# ═══════════════════════════════════════════════════════════════════
# VISÃO GERAL DA OPERAÇÃO — bloco exclusivo de Supervisor/ADM.
# ═══════════════════════════════════════════════════════════════════

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


def _gerar_excel_relatorio(tickets: list, nomes_users: dict) -> bytes:
    import pandas as pd
    from io import BytesIO
    from collections import defaultdict

    linhas = []
    for t in tickets:
        ats = t.get("atendentes") or ([t.get("atribuido_para")] if t.get("atribuido_para") else [])
        atend_nomes = ", ".join(nomes_users.get(a, a) for a in ats) if ats else "— ninguém —"
        hist_txt = " | ".join(
            f"{h.get('etapa','')} ({str(h.get('quando',''))[:16]} por {h.get('por','')})"
            for h in t.get("historico_etapas", [])
        )
        sla1_txt = ("Cumprido" if t.get("sla1_cumprido") else "Perdido") \
            if t.get("sla1_definido") else "Não classificado"
        pend_setor_txt = " | ".join(
            f"{s.get('setor_origem','')}→{s.get('setor_destino','')}: {s.get('mensagem','')}"
            for s in t.get("solicitacoes_setor", []) if s.get("tipo") == "pedido"
        )
        linhas.append({
            "ID":                  t.get("id_zendesk", str(t.get("id",""))[:8]),
            "Assunto":             t.get("assunto",""),
            "Departamento":        t.get("departamento",""),
            "Motivo Pai":          t.get("motivo_pai",""),
            "Motivo Filho":        t.get("motivo_filho",""),
            "Etapa Atual":         t.get("etapa_atual",""),
            "Status":              STATUS_CFG.get(t.get("status",""), (t.get("status",""),))[0],
            "Prioridade":          PRIO_CFG.get(t.get("prioridade",""), (t.get("prioridade",""),))[0],
            "Atendente(s)":        atend_nomes,
            "Aberto por":          t.get("aberto_por",""),
            "Cliente":             t.get("cliente_nome",""),
            "Criado em":           t.get("criado_em",""),
            "Atualizado em":       t.get("atualizado_em",""),
            "SLA1 (Triagem)":      sla1_txt,
            "Prazo Etapa (SLA2)":  t.get("etapa_data_prevista","") or "—",
            "SLA Perdido (geral)": "Sim" if sla_foi_perdido(t) else "Não",
            "Pendências de Setor": pend_setor_txt or "—",
            "Histórico de Etapas": hist_txt,
        })
    df_detalhe = pd.DataFrame(linhas)

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

    resumo_mot = defaultdict(lambda: {"total":0, "pendentes":0, "sla_perdido":0})
    for t in tickets:
        mot = t.get("motivo_pai") or t.get("tabulacao") or "Sem motivo"
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

    st.markdown("---")
    fc1, fc2, fc3 = st.columns([1, 1, 1.2])
    with fc1:
        op_sel = st.multiselect(
            "👤 Filtrar por atendente",
            options=sorted(nomes_users.values()),
            key="vg_filtro_operador",
        )
    motivos_disponiveis = sorted({(t.get("motivo_pai") or "Sem motivo") for t in tickets_dep})
    with fc2:
        mot_sel = st.multiselect(
            "📋 Filtrar por motivo",
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
        if mot_sel and (t.get("motivo_pai") or "Sem motivo") not in mot_sel:
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


def _aba_dashboard(tickets: list, usuarios_dep: list, nomes_users: dict):
    from collections import Counter

    total      = len(tickets)
    pendentes  = sum(1 for t in tickets if t.get("status") in STATUS_ABERTOS)
    sla_perd   = sum(1 for t in tickets if sla_foi_perdido(t))
    pct_cumprido = ((total - sla_perd) / total * 100) if total else 100.0
    com_sla1   = [t for t in tickets if t.get("sla1_definido")]
    sla1_ok    = sum(1 for t in com_sla1 if t.get("sla1_cumprido"))
    pct_sla1   = (sla1_ok / len(com_sla1) * 100) if com_sla1 else None

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(f'<div class="kpi-card gold"><div class="kpi-label">Total de Tickets</div>'
                f'<div class="kpi-value">{total}</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card blue"><div class="kpi-label">Pendentes</div>'
                f'<div class="kpi-value">{pendentes}</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card red"><div class="kpi-label">SLA Perdido</div>'
                f'<div class="kpi-value">{sla_perd}</div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="kpi-card green"><div class="kpi-label">SLA Cumprido</div>'
                f'<div class="kpi-value">{pct_cumprido:.0f}%</div></div>', unsafe_allow_html=True)

    if pct_sla1 is not None:
        st.markdown(f'<div class="kpi-card gold" style="margin-top:8px;">'
                    f'<div class="kpi-label">🎯 Triagem no prazo (SLA1)</div>'
                    f'<div class="kpi-value">{pct_sla1:.0f}%</div>'
                    f'<div class="kpi-sub">{sla1_ok} de {len(com_sla1)} classificados</div></div>',
                    unsafe_allow_html=True)

    st.markdown("")

    cont_at = Counter()
    for t in tickets:
        ats = t.get("atendentes") or ([t.get("atribuido_para")] if t.get("atribuido_para") else [])
        if not ats: ats = ["— ninguém —"]
        for a in ats:
            cont_at[nomes_users.get(a, a)] += 1

    cont_mot = Counter(t.get("motivo_pai") or "Sem motivo" for t in tickets)

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
                pagina_itens, pag_atual, total_paginas, pag_key, total = _paginar(
                    meus, f"eq_{uname}"
                )
                for t in pagina_itens:
                    _render_ticket_strip(t, user, papel, key_ctx=f"eq_{uname}_{t.get('id','')}")
                _nav_paginas(pag_atual, total_paginas, pag_key, total)


def _aba_por_motivo(tickets: list, dep_alvo: str, nomes_users: dict):
    pais_dep = motivos_pai_do_departamento(dep_alvo)

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

    if not pais_dep:
        st.caption("Nenhum Motivo cadastrado para este departamento.")
    else:
        for mp in pais_dep:
            nome_mot = mp.get("nome", "—")
            tks_mot  = [t for t in tickets if t.get("motivo_pai") == nome_mot]
            n_total  = len(tks_mot)
            n_pend   = sum(1 for t in tks_mot if t.get("status") in STATUS_ABERTOS)
            n_perd   = sum(1 for t in tks_mot if sla_foi_perdido(t))
            cont_at  = _resumo_quem(tks_mot)
            quem_str = ", ".join(f"{nome} ({qtd})" for nome, qtd in cont_at.most_common()) or "—"
            alerta   = f' <span class="tk-blink">⏳ {n_perd} c/ SLA perdido</span>' if n_perd else ""

            st.markdown(_html(
                f'<div class="tk-equipe-card">'
                f'<b style="color:#2c3e50;">📋 {esc(nome_mot)}</b>{alerta}<br>'
                f'<span style="font-size:0.8rem;color:#64778d;">'
                f'Total: {n_total} &nbsp;·&nbsp; Pendentes: {n_pend} &nbsp;·&nbsp; '
                f'SLA perdido: {n_perd}</span><br>'
                f'<span style="font-size:0.78rem;color:#64778d;">'
                f'👥 Com quem está: {esc(quem_str)}</span>'
                f'</div>'), unsafe_allow_html=True)

        sem_mot = [t for t in tickets if not t.get("motivo_pai")]
        if sem_mot:
            cont_at  = _resumo_quem(sem_mot)
            quem_str = ", ".join(f"{nome} ({qtd})" for nome, qtd in cont_at.most_common()) or "—"
            st.markdown(_html(
                f'<div class="tk-equipe-card">'
                f'<b style="color:#64778d;">📋 Sem motivo (tickets legados/Zendesk)</b><br>'
                f'<span style="font-size:0.8rem;color:#64778d;">Total: {len(sem_mot)}</span><br>'
                f'<span style="font-size:0.78rem;color:#64778d;">'
                f'👥 Com quem está: {esc(quem_str)}</span>'
                f'</div>'), unsafe_allow_html=True)


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
            "Motivo": _caminho_motivo(t) or "Sem motivo",
            "Status": STATUS_CFG.get(t.get("status",""), (t.get("status",""),))[0],
            "Atendente(s)": atend_nomes,
            "Criado em": t.get("criado_em",""),
        })
    df_det = pd.DataFrame(linhas)
    st.dataframe(df_det, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.caption("Clique em qualquer ticket abaixo para abrir o detalhe:")
    for t in perdidos:
        _render_ticket_strip(t, user, papel, key_ctx=f"slaopen_{t.get('id','')}")


def _aba_exportar(tickets: list, nomes_users: dict, dep_alvo: str, data_ini=None, data_fim=None):
    st.markdown("##### 📥 Relatório Completo")
    st.caption(
        "Gera uma planilha .xlsx com 3 abas: **Por Atendente** (produtividade e SLA perdido), "
        "**Por Motivo** (volume por Motivo Pai) e **Detalhe Completo** (todos os tickets do "
        "recorte filtrado acima, com Motivo Pai/Filho/Etapa, SLA1, SLA2, pendências entre "
        "setores e histórico completo de classificação, ticket a ticket)."
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

    st.markdown("---")
    st.markdown("#### Tickets no Firestore por origem")
    todos2 = listar_tickets()
    from collections import Counter
    df_orig = pd.DataFrame(
        Counter(t.get("origem","interno") for t in todos2).items(),
        columns=["Origem","Qtd"]
    )
    st.dataframe(df_orig, use_container_width=True, hide_index=True)

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
