import streamlit as st
import pandas as pd
from erp.services import encomenda_service as svc


def render():
    st.header("🧾 Encomendar (planejamento de compras)")
    st.caption(
        "Nasce automaticamente sempre que uma venda é feita sem estoque disponível. "
        "Some daqui quando a mercadoria chega (ABA PRODUTO → Entrada) ou quando o "
        "pedido de origem é eliminado pela ABA DIRETORIA."
    )
    fila = svc.listar_fila_compras()
    if not fila:
        st.info("Nenhuma encomenda pendente. 🎉")
        return
    df = pd.DataFrame([{
        "SKU": item["sku"], "Produto": item["produto_nome"], "Qtd. a comprar": item["quantidade"],
        "Pedidos que aguardam": ", ".join(item["pedidos"]),
    } for item in fila])
    st.dataframe(df, use_container_width=True, hide_index=True)
