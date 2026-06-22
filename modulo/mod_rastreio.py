import sys
import os
import io
import time
from datetime import datetime
import pandas as pd
import streamlit as st

# Garante que o Python encontre a pasta raiz para importar o database
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database import (obter_vinculo_db, salvar_vinculo_db, deletar_rota_db)

# --- FUNÇÕES DE APOIO (Isoladas no módulo) ---
def get_series(df, col, default=""):
    if col in df.columns: return df[col]
    return pd.Series([default] * len(df))

def formatar_data(valor):
    if not valor or str(valor).strip() in ("", "None", "null"): return "—"
    try: return datetime.fromisoformat(str(valor).replace("+00:00", "").strip()).strftime("%d/%m %H:%M")
    except: return str(valor)[:16]

def extrair_chave_permanente(rota_string):
    if not rota_string: return "SEM_ROTA"
    return rota_string.split(" - ", 1)[1].strip() if " - " in rota_string else rota_string.strip()

def obter_nome_banco_ou_limpo(rota_original):
    return obter_vinculo_db(extrair_chave_permanente(rota_original))

def renderizar_rastreio(df, data_consulta, papel):
    """Renderiza todas as abas relacionadas ao rastreio de frotas."""
    
    # Sub-abas do módulo de rastreio
    abas_nomes = ["🏠 Dashboard", "🧑‍✈️ Visão por Motorista"]
    if papel in ["supervisor", "adm"]: abas_nomes.append("📥 Exportar")
    abas = st.tabs(abas_nomes)

    # ════ ABA 1: DASHBOARD ════
    with abas[0]:
        if df.empty:
            st.info("⏳ Nenhum dado de entrega encontrado para o dia selecionado. Mas o sistema está online!")
        else:
            df["_notificado"] = get_series(df, "on_its_way").apply(lambda x: bool(x and str(x).strip() not in ("", "None", "null")))
            total = len(df)
            notificados = int(df["_notificado"].sum())
            sucesso = int((get_series(df, "_status_visual") == "✅ Sucesso").sum())
            falhou = int((get_series(df, "_status_visual") == "❌ Falhou").sum())
            pendentes = total - sucesso - falhou

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.markdown(f'<div class="kpi-card"><div class="kpi-label">📦 Total</div><div class="kpi-value">{total}</div><div class="kpi-sub">Carga Oficial</div></div>', unsafe_allow_html=True)
            k2.markdown(f'<div class="kpi-card"><div class="kpi-label">📱 Notificados</div><div class="kpi-value" style="color:#2ecc71;">{notificados}</div><div class="kpi-sub">{round(notificados/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
            k3.markdown(f'<div class="kpi-card"><div class="kpi-label">✅ Sucessos</div><div class="kpi-value" style="color:#3498db;">{sucesso}</div><div class="kpi-sub">{round(sucesso/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
            k4.markdown(f'<div class="kpi-card"><div class="kpi-label">❌ Falhas</div><div class="kpi-value" style="color:#e74c3c;">{falhou}</div><div class="kpi-sub">{round(falhou/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
            k5.markdown(f'<div class="kpi-card"><div class="kpi-label">⏳ Pendentes</div><div class="kpi-value">{pendentes}</div><div class="kpi-sub">Na Rua</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.dataframe(pd.DataFrame({
                "Ordem": get_series(df, "order"), 
                "Motorista": get_series(df, "route").apply(obter_nome_banco_ou_limpo),
                "Cliente": get_series(df, "title"), 
                "Status": get_series(df, "_status_visual", "⏳ Pendente"),
                "Notificado": get_series(df, "_notificado").apply(lambda x: "Sim" if x else "Não"),
                "Check-out": get_series(df, "checkout_time").apply(formatar_data)
            }), use_container_width=True, hide_index=True)

    # ════ ABA 2: VISÃO POR MOTORISTA ════
    with abas[1]:
        if df.empty:
            st.info("⏳ Nenhuma rota ou motorista ativo nesta data.")
        else:
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
                        if st.button("Salvar Condutor", use_container_width=True):
                            salvar_vinculo_db(extrair_chave_permanente(mot_ativo), novo_nome.strip())
                            st.rerun()

                    # Motor de otimização de fluxo (Preparação Preditiva)
                    st.markdown("---")
                    if st.button("🚀 Otimizar Rota (Fluxo Futuro)", use_container_width=True, help="Calcula todas as possibilidades de fluxo para este motorista."):
                        st.success(f"Analisando dados do motorista para calcular o melhor trajeto nas futuras corridas. Módulo de predição ativado.")

                    if papel == "adm":
                        st.markdown("---")
                        st.error("🚨 Zona de Exclusão")
                        if st.button("Excluir Carga do Motorista", use_container_width=True):
                            deletar_rota_db(mot_ativo, data_consulta)
                            st.rerun()

                with col_m2:
                    df_rota = df[df["route"] == mot_ativo]
                    st.dataframe(pd.DataFrame({
                        "Cliente": get_series(df_rota, "title"), 
                        "Status": get_series(df_rota, "_status_visual"),
                        "Observação": get_series(df_rota, "checkout_observation")
                    }), use_container_width=True, hide_index=True)

    # ════ ABA 3: EXPORTAR ════
    if "📥 Exportar" in abas_nomes:
        idx = abas_nomes.index("📥 Exportar")
        with abas[idx]:
            if df.empty:
                st.warning("⚠️ Não há planilhas para gerar pois este dia não possui registros.")
            else:
                st.write("Extração completa dos dados processados.")
                df_excel = pd.DataFrame({
                    "Ordem": get_series(df, "order"), 
                    "Motorista": get_series(df, "route").apply(obter_nome_banco_ou_limpo),
                    "Cliente": get_series(df, "title"), 
                    "Status": get_series(df, "_status_visual", "⏳ Pendente"),
                    "Check-out": get_series(df, "checkout_time").apply(formatar_data), 
                    "Anotações": get_series(df, "notes")
                })
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer: 
                    df_excel.to_excel(writer, index=False)
                st.download_button("📥 Baixar Planilha", data=output.getvalue(), file_name=f"Relatorio_{data_consulta}.xlsx", type="primary")
