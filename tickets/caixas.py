"""
KingStar — Módulo de Tickets — caixas.py  [NOVO — v22]
─────────────────────────────────────────────────────────────────────────────
"Caixas por Motivo" — navegação por Motivo Pai (Pedido, Compras, Logística,
Cliente...), com sub-filtro por Motivo Filho dentro de cada caixa, ordenação
(Urgência / Mais antigo / Mais recente) e seleção em lote pra transferir
vários tickets de uma vez.

Por que este arquivo existe separado de `tickets/filas.py`: ainda não recebi
o conteúdo real de `filas.py`/`strip.py`, então em vez de arriscar adivinhar
como a tirinha de ticket funciona por lá, este arquivo é AUTOSSUFICIENTE —
usa só funções que eu já vi de verdade em `tickets/common.py`. Quando
`filas.py` for entregue, dá pra decidir se este arquivo continua separado ou
se vira parte dele.

Navegação (só sessão local a este arquivo, não conflita com o resto):
  tk_caixa_motivo   → qual Motivo Pai está selecionado (None = tela dos 4
                       cartões, "Voltar às filas rápidas").
  tk_caixa_filho    → sub-filtro por Motivo Filho dentro do Motivo Pai
                       selecionado ("" = Todos).
  tk_caixa_ordem    → "urgencia" | "antigo" | "recente".

Contagem: só entram tickets com Motivo Pai definido E status em aberto
(STATUS_ABERTOS) — é a mesma régua usada no resto do sistema pra "quanto
está pendente". Tickets finalizados/cancelados/resolvidos não aparecem
aqui (métrica de trabalho pendente, não de histórico).
"""
import time
import streamlit as st

from .common import (
    STATUS_ABERTOS, STATUS_CFG, PRIO_CFG, esc, _html,
    sla_restante, sla_foi_perdido, ticket_vencido_pendente,
    _caminho_motivo, transferir_tickets, listar_usuarios,
)


def _tickets_pendentes_com_motivo(todos_geral: list) -> list:
    return [t for t in todos_geral if t.get("motivo_pai") and t.get("status") in STATUS_ABERTOS]


def _contagem_por_motivo_pai(tickets_pendentes: list) -> dict:
    cont = {}
    for t in tickets_pendentes:
        nome = t.get("motivo_pai")
        cont[nome] = cont.get(nome, 0) + 1
    return cont


def _contagem_por_motivo_filho(tickets_do_pai: list) -> dict:
    cont = {}
    for t in tickets_do_pai:
        nome = t.get("motivo_filho") or "Sem Motivo Filho"
        cont[nome] = cont.get(nome, 0) + 1
    return cont


def _ordenar(tickets: list, ordem: str) -> list:
    if ordem == "antigo":
        return sorted(tickets, key=lambda t: t.get("criado_em", ""))
    if ordem == "recente":
        return sorted(tickets, key=lambda t: t.get("criado_em", ""), reverse=True)
    # "urgencia" (padrão): vencidos primeiro, depois urgentes, depois o resto
    # (mais antigo primeiro dentro de cada grupo — quem espera há mais tempo
    # aparece antes).
    def chave(t):
        venc = 0 if ticket_vencido_pendente(t) else 1
        urg  = 0 if t.get("prioridade") == "urgente" else 1
        return (venc, urg, t.get("criado_em", ""))
    return sorted(tickets, key=chave)


def _render_card_ticket_caixa(t, box_label: str, key_sufixo: str, marcavel: bool):
    """Card autossuficiente de um ticket dentro da Caixa por Motivo — não
    depende de `tickets/strip.py`. Clicar no ID/assunto grava
    `tk_ticket_aberto`, exatamente como a tirinha faria, e o orquestrador
    (mod_tickets.py) cuida de transformar isso numa aba."""
    tid = t.get("id")
    sv, sbg, sc, _ = STATUS_CFG.get(t.get("status","aberto"), ("—","#fff","#000","#000"))
    caminho = _caminho_motivo(t) or t.get("motivo_pai") or "—"
    cli_cod = t.get("cliente_codigo") or "—"
    dep = (t.get("departamento") or t.get("categoria") or "—")
    criado = str(t.get("criado_em",""))[:16]
    atend = t.get("atendentes", [])
    quem_abriu = t.get("aberto_por") or "—"
    com_atend = f" · com {', '.join(atend)}" if atend else ""

    marcado = False
    col_chk, col_corpo = (st.columns([0.06, 0.94]) if marcavel else (None, st))
    if marcavel:
        with col_chk:
            marcado = st.checkbox("", key=f"caixa_sel_{key_sufixo}_{tid}", label_visibility="collapsed")

    with col_corpo:
        if st.button(f"#{esc(t.get('id_zendesk', str(tid)[:8]))} · {esc(t.get('assunto','—'))}",
                     key=f"caixa_abrir_{key_sufixo}_{tid}", use_container_width=True):
            st.session_state.tk_ticket_aberto = tid
            st.rerun()
        st.markdown(_html(f"""
        <div style="font-size:0.78rem;color:#64778d;margin:-4px 0 2px;">
            {esc(quem_abriu)} · cód. {esc(cli_cod)} · {esc(dep.lower())} · {esc(criado)}{esc(com_atend)}
        </div>
        <div style="font-size:0.78rem;color:#7a5f1a;margin-bottom:6px;">
            classificado {esc(caminho)} · vive em <b>{esc(box_label)}</b>
        </div>
        <div style="margin-bottom:10px;">
            <span style="background:{sbg};color:{sc};padding:2px 10px;border-radius:12px;
                        font-size:0.72rem;font-weight:700;">{esc(sv)}</span>
        </div>
        """), unsafe_allow_html=True)

    return marcado


def _render_barra_ordenar(chave_ordem_atual: str, url_ctx: str):
    st.markdown("**Ordenar**")
    o1, o2, o3, o4 = st.columns(4)
    opcoes = [(o1, "urgencia", "Urgência"), (o2, "todos", "Todos"),
              (o3, "antigo", "Mais antigo"), (o4, "recente", "Mais recente")]
    for col, valor, label in opcoes:
        with col:
            if st.button(label, key=f"caixa_ordem_{url_ctx}_{valor}", use_container_width=True,
                         type="primary" if chave_ordem_atual == valor else "secondary"):
                st.session_state.tk_caixa_ordem = valor
                st.rerun()


def _render_selecao_lote(tickets_pagina: list, ids_marcados: list):
    """Ação em lote — mesmo recurso já pedido antes pra Filas de Trabalho
    (bloqueado na época por falta de `filas.py`); aqui já sai pronto porque
    este arquivo renderiza os próprios cards."""
    if not ids_marcados:
        return
    st.markdown(_html(f"""
    <div class="tk-banner" style="animation:none;">
        ✅ {len(ids_marcados)} ticket(s) selecionado(s).
    </div>"""), unsafe_allow_html=True)
    usuarios = [u for u in listar_usuarios() if u.get("role") in ("operacional", "supervisor", "adm")]
    opcoes = {u.get("usuario",""): u.get("nome", u.get("usuario","")) for u in usuarios}
    if not opcoes:
        st.caption("Nenhum usuário disponível para transferência.")
        return
    dest = st.selectbox("Transferir selecionados para", list(opcoes.keys()),
                        format_func=lambda x: opcoes.get(x, x), key="caixa_lote_dest")
    if st.button(f"🔁 Transferir {len(ids_marcados)} ticket(s) → {opcoes.get(dest,'')}",
                 type="primary", key="caixa_lote_transferir"):
        qt = transferir_tickets(ids_marcados, dest)
        st.success(f"✅ {qt} ticket(s) transferido(s) para {opcoes.get(dest,'')}!")
        time.sleep(.8); st.rerun()


def _render_caixas_por_motivo(user, papel, todos_geral: list):
    st.markdown("### 🗂️ Caixas por Motivo")

    if "tk_caixa_motivo" not in st.session_state: st.session_state.tk_caixa_motivo = None
    if "tk_caixa_filho"  not in st.session_state: st.session_state.tk_caixa_filho  = ""
    if "tk_caixa_ordem"  not in st.session_state: st.session_state.tk_caixa_ordem  = "urgencia"

    pendentes = _tickets_pendentes_com_motivo(todos_geral)
    cont_pai = _contagem_por_motivo_pai(pendentes)

    motivo_sel = st.session_state.tk_caixa_motivo

    # ── Tela 1: os 4 (ou N) cartões de Motivo Pai ──
    if not motivo_sel:
        if not cont_pai:
            st.info("Nenhum ticket pendente com Motivo Pai classificado ainda.")
            return
        total_geral = sum(cont_pai.values())
        st.caption(f"**CAIXAS POR MOTIVO ({total_geral})**")
        cols = st.columns(min(len(cont_pai), 4) or 1)
        for i, (nome, qtd) in enumerate(sorted(cont_pai.items(), key=lambda kv: -kv[1])):
            with cols[i % len(cols)]:
                if st.button(f"{nome.upper()}\n{qtd}", key=f"caixa_pai_{nome}",
                             use_container_width=True):
                    st.session_state.tk_caixa_motivo = nome
                    st.session_state.tk_caixa_filho = ""
                    st.rerun()
        return

    # ── Tela 2: dentro de uma Caixa (Motivo Pai selecionado) ──
    if st.button("← voltar às filas rápidas", key="caixa_voltar"):
        st.session_state.tk_caixa_motivo = None
        st.rerun()

    tickets_do_pai = [t for t in pendentes if t.get("motivo_pai") == motivo_sel]
    st.markdown(f"#### CAIXA :: {motivo_sel.upper()}")

    cont_filho = _contagem_por_motivo_filho(tickets_do_pai)
    filho_sel = st.session_state.tk_caixa_filho

    chips = [("", f"Todos {len(tickets_do_pai)}")] + [
        (nome, f"{nome} {qtd}") for nome, qtd in sorted(cont_filho.items(), key=lambda kv: -kv[1])
    ]
    cols_chip = st.columns(len(chips))
    for col, (valor, label) in zip(cols_chip, chips):
        with col:
            if st.button(label, key=f"caixa_filho_{motivo_sel}_{valor or 'todos'}",
                         use_container_width=True,
                         type="primary" if filho_sel == valor else "secondary"):
                st.session_state.tk_caixa_filho = valor
                st.rerun()

    tickets_filtrados = tickets_do_pai
    if filho_sel:
        tickets_filtrados = [t for t in tickets_filtrados
                             if (t.get("motivo_filho") or "Sem Motivo Filho") == filho_sel]

    _render_barra_ordenar(st.session_state.tk_caixa_ordem, url_ctx=motivo_sel)
    tickets_ordenados = _ordenar(tickets_filtrados, st.session_state.tk_caixa_ordem)

    st.markdown(f"**Selecionar {min(50, len(tickets_ordenados))} atendimentos desta página**")
    pagina = tickets_ordenados[:50]

    box_label = f"CAIXA :: {motivo_sel.upper()}"
    marcados_ids = []
    for t in pagina:
        marcado = _render_card_ticket_caixa(t, box_label, key_sufixo=f"{motivo_sel}", marcavel=True)
        if marcado:
            marcados_ids.append(t.get("id"))

    _render_selecao_lote(pagina, marcados_ids)
