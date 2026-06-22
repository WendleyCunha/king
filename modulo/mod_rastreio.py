import streamlit as st
import pandas as pd
import sys
import os

# Adiciona o diretório pai (raiz) ao caminho de busca do Python
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import (obter_nome_banco_ou_limpo, formatar_data, get_series, 
                      salvar_vinculo_db, deletar_rota_db)

def renderizar_rastreio(data_consulta, papel, df):
    """Renderiza a aba de rastreio de forma isolada."""
    
    if df.empty:
        st.info("⏳ Nenhuma rota ou motorista ativo nesta data.")
        return

    rotas_unicas = sorted(df["route"].unique()) if "route" in df.columns else []
    
    if rotas_unicas:
        opcoes_radio, mapeamento_reverso = [], {}
        for r_orig in rotas_unicas:
            lbl = f"📍 {obter_nome_banco_ou_limpo(r_orig)}"
            opcoes_radio.append(lbl)
            mapeamento_reverso[lbl] = r_orig

        col_m1, col_m2 = st.columns([1.5, 3])
        with col_m1:
            lbl_sel = st.radio("Rotas do Dia", options=opcoes_radio, label_visibility="collapsed")
            mot_ativo = mapeamento_reverso[lbl_sel]
            
            if papel in ["supervisor", "adm"]:
                st.markdown("---")
                novo_nome = st.text_input("Alterar nome do condutor:", value=obter_nome_banco_ou_limpo(mot_ativo))
                if st.button("💾 Salvar Condutor"):
                    salvar_vinculo_db(mot_ativo.split(" - ", 1)[-1] if " - " in mot_ativo else mot_ativo, novo_nome.strip())
                    st.rerun()

            if papel == "adm":
                st.markdown("---")
                st.error("🚨 Zona de Exclusão")
                if st.button("🗑️ Excluir Carga"):
                    deletar_rota_db(mot_ativo, data_consulta)
                    st.rerun()

        with col_m2:
            df_rota = df[df["route"] == mot_ativo]
            st.dataframe(pd.DataFrame({
                "Cliente": get_series(df_rota, "title"), 
                "Status": get_series(df_rota, "_status_visual"),
                "Observação": get_series(df_rota, "checkout_observation")
            }), use_container_width=True, hide_index=True)
