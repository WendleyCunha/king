"""
KingStar — Módulo de Tickets — strip.py
─────────────────────────────────────────────────────────────────────────────
TIRINHA HORIZONTAL — padrão ÚNICO de card de ticket, usado em TODO lugar do
sistema que mostra um ticket (Filas de Trabalho, abas por Departamento em
Pendências, Visão Geral por Atendente, SLA vencidos).

O clique é um BOTÃO DE VERDADE (visível), formando a "linha de cima" do card
— ícone + ID + título — e o restante das informações (badges, cliente, SLA)
fica colado visualmente embaixo dele. O clique define qual ticket está
"aberto" no estado da sessão (tk_ticket_aberto), e a coluna de Detalhe
(terceira coluna, à direita, ver mod_tickets.py) aparece/atualiza sozinha.
"""
import streamlit as st

from .common import (
    STATUS_CFG, PRIO_CFG, GOLD_VENC, GOLD_WARN, GREEN_OK,
    sla_estado, sla_restante, sla_label, cor_departamento,
    esc, pill, _html, resolvido_em_validacao, tem_interacao_nao_vista,
    solicitacoes_abertas, _caminho_motivo,
)


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
    sistema, com TODAS as informações e cores já existentes: ícone de
    origem, ID, título, departamento, motivo (pai › filho › etapa), cliente,
    nº de comentários, data de criação, pill de status, pill de prioridade,
    badges (vencido / aviso <30min / validação pendente / nova interação /
    pendências de setor) e a barra + texto do SLA/prazo ativo.

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
    classe_aberto = "aberto-agora" if ticket_aberto_agora else ""
    badges   = (extra_badge_html or "") + _badges_ticket(t, user)
    meta_com = f" &nbsp;·&nbsp; 💬 {num_com}" if num_com else ""
    meta_mot = f" &nbsp;·&nbsp; 📂 {esc(caminho_mot)}" if caminho_mot else ""

    # o `estado` entra na key do container pra o CSS conseguir mirar o
    # botão (venc/warn) e dar o mesmo destaque piscante que a borda tinha
    with st.container(key=f"tkwrap_{estado}_{key_ctx}"):
        if st.button(f"{icon}  #{idv} — {titulo}", key=f"tkbtn_{key_ctx}", use_container_width=True):
            st.session_state.tk_ticket_aberto = tid
            st.rerun()

        st.markdown(_html(f"""
        <div class="tk-stripbody {classe_aberto}" style="border-left-color:{borda};">
            <div class="tk-strip-pills">{pill(sv_label,sbg,sc)} {pill(pv_label,pbg,pc)}</div>
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
