import streamlit as st
import pandas as pd
from services import fiscal_service as svc


def render():
    st.header("🧾 Fiscal — Notas Emitidas")

    data_filtro = st.date_input("Filtrar por dia", value=None)
    notas = svc.listar_notas_por_dia(data_filtro if data_filtro else None)

    if not notas:
        st.info("Nenhuma nota fiscal emitida para esse filtro.")
        return

    df = pd.DataFrame([{
        "Número": n["numero"], "Pedido": n["pedido_numero"], "Valor": n["valor"],
        "Emitida em": n["emitida_em"],
    } for n in notas])
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.metric("Total faturado no período", f"R$ {sum(n['valor'] for n in notas):,.2f}")

    for n in notas:
        if n.get("pdf_path"):
            with open(n["pdf_path"], "rb") as f:
                st.download_button(f"Baixar PDF {n['numero']}", f, file_name=f"{n['numero']}.pdf", key=f"pdf_{n['numero']}")
