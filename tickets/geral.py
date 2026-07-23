"""
KingStar — Módulo de Tickets — geral.py
─────────────────────────────────────────────────────────────────────────────
Bloco exclusivo de Supervisor/ADM: Visão Geral da Operação (dashboard,
ranking por atendente com transferência em massa, ranking por motivo, SLA
perdido, exportação em Excel com 3 abas) + a tela de Sync Zendesk / Zona de
Perigo (exclusão total de tickets).
"""
import time
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from collections import defaultdict, Counter

from modulo.mod_motivos import motivos_pai_do_departamento
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
