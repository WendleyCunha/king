"""
KingStar — Módulo de Tickets — geral.py
─────────────────────────────────────────────────────────────────────────────
Bloco exclusivo de Supervisor/ADM: Visão Geral da Operação (dashboard,
ranking por atendente com transferência em massa, ranking por motivo, SLA
perdido, exportação em Excel com 3 abas) + a tela de Sync Zendesk / Zona de
Perigo (exclusão total de tickets).

[Ajuste visual — v23] O dashboard mostrava "Quem mais atendeu" e "Motivo
mais acionado" como `st.dataframe` cru — uma tabela sem estilo nenhum,
destoando do resto do sistema (que usa cards com borda dourada em todo
lugar). Trocado por uma lista de cards no mesmo padrão visual já usado em
`tickets/detalhe.py` e `mod_motivos.py` — nenhuma lógica de contagem
mudou, só a forma de mostrar o resultado.
"""
import time
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from collections import defaultdict, Counter

from .common import (
    BRT, COLECAO, get_db, STATUS_CFG, PRIO_CFG, STATUS_ABERTOS,
    sla_foi_perdido, esc, _html, listar_departamentos, listar_usuarios,
    transferir_tickets, _paginar, _nav_paginas, sync_zendesk,
    deletar_todos_tickets, listar_tickets, _caminho_motivo,
    ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_TOKEN, ZENDESK_VIEW_ID,
)
from .strip import _render_ticket_strip


def _gerar_excel_relatorio(tickets: list, nomes_users: dict) -> bytes:
    from io import BytesIO

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


# ═══════════════════════════════════════════════════════════════════
# [v23] Card de ranking — mesmo padrão visual do resto do sistema
# (borda dourada à esquerda, badge de posição), em vez de st.dataframe.
# ═══════════════════════════════════════════════════════════════════
def _render_ranking_cards(itens: list, rotulo_singular: str, key_ctx: str, max_itens: int = 8):
    """`itens`: lista de (nome, qtd), já ordenada do maior pro menor."""
    if not itens:
        st.caption("Sem dados.")
        return
    medalhas = ["🥇", "🥈", "🥉"]
    for i, (nome, qtd) in enumerate(itens[:max_itens]):
        medalha = medalhas[i] if i < 3 else f"{i+1}º"
        destaque = "border-left-color:#C9A84C;" if i == 0 else ""
        st.markdown(_html(f"""
        <div class="tk-equipe-card" style="display:flex;justify-content:space-between;
                    align-items:center;{destaque}">
            <div>
                <span style="font-size:0.95rem;font-weight:700;color:#2c3e50;">
                    {medalha} {esc(nome)}
                </span>
            </div>
            <div>
                <span class="tk-badge-val">{qtd} {esc(rotulo_singular)}{'s' if qtd != 1 else ''}</span>
            </div>
        </div>"""), unsafe_allow_html=True)
    if len(itens) > max_itens:
        st.caption(f"+ {len(itens) - max_itens} outro(s), fora do top {max_itens}.")


def _render_visao_geral_operacao(user, papel, todos_geral):
    st.markdown("### 📊 Visão Geral da Operação")
    if st.button("← Voltar"):
        st.session_state.tk_modo = "lista"; st.rerun()

    # [v26 — REMOVIDO] O seletor "Departamento" (view/filtro "Por
    # Departamento"), os multiselects "Filtrar por atendente" e "Filtrar
    # por motivo" saíram por instrução explícita: a tela deixa de oferecer
    # visão analítica por Departamento/Atendente/Motivo. Para ADM, o
    # recorte agora é SEMPRE todos os departamentos juntos — sem seletor.
    if papel == "adm":
        tickets_dep = todos_geral
        usuarios_dep = listar_usuarios()
    else:
        dep_proprio = user.get("departamento", "") or "—"
        tickets_dep = [t for t in todos_geral if t.get("departamento") == dep_proprio]
        usuarios_dep = [u for u in listar_usuarios() if u.get("departamento") == dep_proprio]

    nomes_users = {u.get("usuario",""): u.get("nome", u.get("usuario","")) for u in usuarios_dep}

    if not usuarios_dep:
        st.info("Nenhum atendente vinculado.")
        return

    st.markdown("---")
    hoje = datetime.now(BRT).date()
    primeiro_dia_mes = hoje.replace(day=1)
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
        if data_ini and data_fim:
            d = _data_ticket(t)
            if d is None or not (data_ini <= d <= data_fim):
                return False
        return True

    tickets_filtrados = [t for t in tickets_dep if _passa_filtro(t)]
    if data_ini and data_fim:
        st.caption(f"🔎 Período {data_ini.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')} "
                   f"— exibindo {len(tickets_filtrados)} de {len(tickets_dep)} ticket(s).")

    # [v26 — REMOVIDO] As abas "Por Atendente" e "Por Motivo" saíram por
    # instrução explícita — só sobra o Dashboard geral, SLA Perdido e
    # Exportar (que continua útil pra fechamento mensal em planilha).
    aba_dash, aba_sla, aba_export = st.tabs(
        ["📊 Dashboard", "⏳ SLA Perdido", "📥 Exportar"]
    )

    with aba_dash:
        _aba_dashboard(tickets_filtrados, usuarios_dep, nomes_users)

    with aba_sla:
        _aba_sla_perdido(tickets_filtrados, nomes_users, user, papel)

    with aba_export:
        _aba_exportar(tickets_filtrados, nomes_users, "Todos" if papel == "adm" else user.get("departamento",""),
                     data_ini, data_fim)


def _aba_dashboard(tickets: list, usuarios_dep: list, nomes_users: dict):
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
    # [v26 — REMOVIDO] "Quem mais atendeu" / "Motivo mais acionado" saíram
    # daqui — eram visão por Atendente/Demanda, removida por instrução.
    # O Dashboard agora só mostra os KPIs gerais acima.




def _aba_sla_perdido(tickets: list, nomes_users: dict, user, papel):
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

    # [v23] Ranking em cards, não mais st.dataframe cru.
    st.markdown("**Ranking de responsáveis por SLA perdido**")
    _render_ranking_cards(cont_resp.most_common(), "SLA perdido", key_ctx="sla_resp")

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
