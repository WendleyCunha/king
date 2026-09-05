import streamlit as st
import pandas as pd
from services import financeiro_service as svc


def render():
    st.header("💰 Financeiro")

    col1, col2 = st.columns(2)
    data_inicio = col1.date_input("De", value=None)
    data_fim = col2.date_input("Até", value=None)
    filtros = {}
    if data_inicio:
        filtros["data_inicio"] = data_inicio
    if data_fim:
        filtros["data_fim"] = data_fim

    lancamentos = svc.listar_lancamentos(**filtros)
    if not lancamentos:
        st.info("Nenhum lançamento no período.")
        return

    df = pd.DataFrame([{
        "Data": l["criado_em"], "Valor": l["valor"],
        "Forma de pagamento": l["forma_pagamento"], "Vendedor": l.get("vendedor_codigo") or "-",
    } for l in lancamentos])
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.metric("Total no período", f"R$ {sum(l['valor'] for l in lancamentos):,.2f}")

    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Por forma de pagamento")
        st.bar_chart(svc.total_por_forma_pagamento(**filtros))
    with col4:
        st.subheader("Por vendedor")
        st.bar_chart(svc.total_por_vendedor(**filtros))
