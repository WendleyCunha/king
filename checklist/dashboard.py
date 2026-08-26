"""
checklist/dashboard.py
Aba "Dashboard" — indicadores consolidados (conformidade, não conformidades
recorrentes, planos de ação atrasados) e exportação em CSV, espelhando os
KPIs citados no levantamento de requisitos (ICO, taxa de resolução, itens
reincidentes).
"""
import datetime as _dt
import streamlit as st
from . import api_client as api


def renderizar_dashboard():
    col_ini, col_fim, col_unid = st.columns(3)
    usar_periodo = col_ini.checkbox("Filtrar por período")
    data_inicio = data_fim = None
    if usar_periodo:
        data_inicio = col_ini.date_input("De", value=_dt.date.today() - _dt.timedelta(days=30))
        data_fim = col_fim.date_input("Até", value=_dt.date.today())

    unidades = api.get("/api/v1/unidades", mostrar_erro=False) or []
    mapa_unidades = {u["nome"]: u["id"] for u in unidades}
    unidade_nome = col_unid.selectbox("Unidade", ["Todas"] + list(mapa_unidades.keys()))

    params = {}
    if usar_periodo and data_inicio and data_fim:
        params["data_inicio"] = data_inicio.isoformat()
        params["data_fim"] = data_fim.isoformat()
    if unidade_nome != "Todas":
        params["unidade_id"] = mapa_unidades[unidade_nome]

    st.markdown("---")
    c1, c2, c3 = st.columns(3)

    resumo_apl = api.get("/api/v1/dashboards/aplicacoes", params=params, mostrar_erro=False)
    if resumo_apl:
        c1.metric("Aplicações", resumo_apl["total"])
        pct = resumo_apl.get("percentual_conformidade_medio")
        c1.caption(f"Conformidade média: {pct:.1f}%" if pct is not None else "Sem dado de conformidade ainda.")
        if resumo_apl.get("por_status"):
            c1.caption(" · ".join(f"{k}: {v}" for k, v in resumo_apl["por_status"].items()))

    params_nc = {"unidade_id": params["unidade_id"]} if "unidade_id" in params else {}
    resumo_nc = api.get("/api/v1/dashboards/nao-conformidades", params=params_nc, mostrar_erro=False)
    if resumo_nc:
        c2.metric("Não Conformidades", resumo_nc["total"])
        if resumo_nc.get("por_prioridade"):
            c2.caption(" · ".join(f"{k}: {v}" for k, v in resumo_nc["por_prioridade"].items()))

    resumo_pa = api.get("/api/v1/dashboards/planos-acao", mostrar_erro=False)
    if resumo_pa:
        c3.metric("Planos de Ação", resumo_pa["total"], delta=f"-{resumo_pa['atrasados']} atrasados"
                  if resumo_pa["atrasados"] else None, delta_color="inverse")
        if resumo_pa.get("por_status"):
            c3.caption(" · ".join(f"{k}: {v}" for k, v in resumo_pa["por_status"].items()))

    if resumo_nc and resumo_nc.get("itens_reincidentes"):
        st.markdown("### 🔁 Itens mais reincidentes")
        for item in resumo_nc["itens_reincidentes"]:
            st.markdown(f"- **{item['titulo_item']}** · {item['ocorrencias']} ocorrência(s)")

    st.markdown("---")
    st.markdown("### 📥 Exportar")
    if st.button("Gerar relatório de aplicações (CSV)"):
        resp = api.chamar_api("get", "/api/v1/relatorios/aplicacoes.csv", params=params)
        if resp is not None and resp.status_code == 200:
            st.download_button(
                "⬇️ Baixar CSV", data=resp.content,
                file_name=f"aplicacoes_{_dt.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )
        elif resp is not None:
            st.error(f"Não foi possível gerar o relatório (HTTP {resp.status_code}).")
