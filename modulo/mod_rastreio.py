import streamlit as st
import pandas as pd
import io
from database import (obter_nome_banco_ou_limpo, calcular_stats_motorista, 
                      formatar_data, get_series, salvar_vinculo_db, deletar_rota_db)

def renderizar_rastreio(df, data_consulta, papel):
    """Renderiza a lógica do Rastreio."""
    
    if df.empty:
        st.info("⏳ Nenhum dado de entrega disponível.")
        return

    # Garante a coluna de notificação
    df["_notificado"] = get_series(df, "on_its_way").apply(
        lambda x: bool(x and str(x).strip() not in ("", "None", "null"))
    )

    abas = st.tabs(["🏠 Dashboard", "🧑‍✈️ Visão por Motorista", "📥 Exportar"])

    # --- ABA 1: DASHBOARD ---
    with abas[0]:
        total = len(df)
        notificados = int(df["_notificado"].sum())
        sucesso = int((get_series(df, "_status_visual") == "✅ Sucesso").sum())
        falhou = int((get_series(df, "_status_visual") == "❌ Falhou").sum())
        pendentes = total - sucesso - falhou

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total", total)
        k2.metric("Notificados", notificados)
        k3.metric("Sucesso", sucesso)
        k4.metric("Falhas", falhou)
        k5.metric("Pendentes", pendentes)

        st.dataframe(pd.DataFrame({
            "Ordem": get_series(df, "order"),
            "Motorista": get_series(df, "route").apply(obter_nome_banco_ou_limpo),
            "Cliente": get_series(df, "title"),
            "Status": get_series(df, "_status_visual", "⏳ Pendente"),
            "Check-out": get_series(df, "checkout_time").apply(formatar_data),
        }), use_container_width=True)

    # --- ABA 2: VISÃO POR MOTORISTA ---
    with abas[1]:
        rotas_unicas = sorted(df["route"].unique())
        # (Aqui você insere a lógica de Grid, paginação e cards de motorista que você já possuía)
        st.write(f"Gerenciando {len(rotas_unicas)} rotas...")
        # ... (seu código de grid aqui)

    # --- ABA 3: EXPORTAR ---
    with abas[2]:
        if papel in ["supervisor", "adm"]:
            df_excel = df.copy() # Simplificado para export
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_excel.to_excel(writer, index=False)
            st.download_button("📥 Baixar Planilha", data=output.getvalue(), 
                               file_name=f"Relatorio_{data_consulta}.xlsx")
        else:
            st.warning("Acesso restrito à exportação.")
