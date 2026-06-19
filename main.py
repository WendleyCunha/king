import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import os
import io
import time
import base64
from database import (verificar_login, obter_tickets_db, obter_datas_disponiveis_db, 
                      obter_vinculo_db, salvar_vinculo_db, deletar_rota_db)

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Monitoramento · KingStar", layout="wide", page_icon="🚚")

# --- SESSÃO E LOGIN ---
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.title("🔐 Login KingStar")
        st.markdown("Acesso ao Eco 360º")
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary", use_container_width=True):
            user = verificar_login(usuario, senha)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Credenciais inválidas")
    st.stop() # Interrompe a renderização para quem não está logado

# --- ÁREA LOGADA (SEU PAINEL ORIGINAL ADAPTADO) ---
user = st.session_state.user

def get_series(df, col, default=""):
    if col in df.columns: return df[col]
    return pd.Series([default] * len(df))

def formatar_data(valor):
    if not valor or str(valor).strip() in ("", "None", "null"): return "—"
    try: return datetime.fromisoformat(str(valor).replace("+00:00", "").strip()).strftime("%d/%m %H:%M")
    except: return str(valor)[:16]

def extrair_chave_permanente(rota_string: str) -> str:
    if not rota_string: return "SEM_ROTA"
    if " - " in rota_string: return rota_string.split(" - ", 1)[1].strip()
    return rota_string.strip()

def obter_nome_banco_ou_limpo(rota_original: str) -> str:
    chave = extrair_chave_permanente(rota_original)
    return obter_vinculo_db(chave)

# CSS Original
st.markdown("""
<style>
    .header-container { background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%); border-left: 6px solid #C9A84C; border-radius: 12px; padding: 20px 24px; margin-bottom: 28px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
    .kpi-card { background: #ffffff; border-radius: 12px; padding: 20px 16px; text-align: center; border-top: 4px solid #C9A84C; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05); height: 100%; }
    .kpi-label { color: #64778d; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; }
    .kpi-value { color: #2c3e50; font-size: 2.2rem; font-weight: 800; }
    .kpi-sub { color: #C9A84C; font-size: 0.85rem; font-weight: 600; }
    .tag { display: inline-block; padding: 5px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 700; margin-right: 4px; margin-top: 4px; }
    .tag-gold { background: rgba(201, 168, 76, 0.15); color: #b0913b; }
    .tag-green { background: rgba(46, 204, 113, 0.12); color: #27ae60; }
    .tag-blue { background: rgba(52, 152, 219, 0.12); color: #2980b9; }
    .tag-red { background: rgba(231, 76, 60, 0.12); color: #c0392b; }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.success(f"👤 {user['nome']}")
    if st.button("Sair"):
        st.session_state.user = None
        st.rerun()
    st.markdown("---")
    st.markdown("### 📅 Período de Consulta")
    
    datas_db = obter_datas_disponiveis_db()
    hoje = date.today().isoformat()
    ontem = (date.today() - timedelta(days=1)).isoformat()
    opcoes_datas = []
    
    datas_disponiveis = [d["data"] for d in datas_db]
    if hoje in datas_disponiveis or not datas_disponiveis: opcoes_datas.append(f"Hoje ({hoje})")
    if ontem in datas_disponiveis: opcoes_datas.append(f"Ontem ({ontem})")
    for item in datas_db:
        if item["data"] not in (hoje, ontem): opcoes_datas.append(f"{datetime.strptime(item['data'], '%Y-%m-%d').strftime('%d/%m/%Y')} — {item['total']} entregas")

    data_sel = st.selectbox("📆 Escolha o Dia:", opcoes_datas)
    data_consulta = hoje if "Hoje" in data_sel else ontem if "Ontem" in data_sel else datetime.strptime(data_sel.split("—")[0].strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    is_hoje = (data_consulta == hoje)
    auto_refresh = st.checkbox("🔄 Atualização em Tempo Real", value=is_hoje)

st.markdown(f"""
<div class="header-container">
    <h1 style="color:#2c3e50; margin:0; font-size:1.8rem; font-weight:800;">Painel de Entregas · KingStar</h1>
    <p style="color:#64778d; margin:4px 0 0; font-size:1rem; font-weight:500;">Eco 360º · SimpliRoute · <span style="color:#C9A84C;">{"🕐 Tempo Real" if is_hoje else data_consulta}</span></p>
</div>
""", unsafe_allow_html=True)

# Processamento de Dados do Firestore
tickets_raw = obter_tickets_db(data_consulta)
if not tickets_raw:
    st.info("⏳ Aguardando envio de rotas ou dados operacionais para o dia selecionado.")
    st.stop()

df = pd.DataFrame(tickets_raw)
df["_notificado"] = get_series(df, "on_its_way").apply(lambda x: bool(x and str(x).strip() not in ("", "None", "null")))

total = len(df)
notificados = int(df["_notificado"].sum())
sucesso = int((get_series(df, "_status_visual") == "✅ Sucesso").sum())
falhou = int((get_series(df, "_status_visual") == "❌ Falhou").sum())
em_rota = int((get_series(df, "_status_visual") == "🚚 Em rota").sum())
pendentes = int((get_series(df, "_status_visual") == "⏳ Pendente").sum())

tab_home, tab_motorista, tab_export = st.tabs(["🏠 HOME - Visão Geral", "🧑‍✈️ Visão por Motorista", "📥 Exportar Dados"])

with tab_home:
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(f'<div class="kpi-card"><div class="kpi-label">📦 Total Geral</div><div class="kpi-value">{total}</div><div class="kpi-sub">Carga Oficial</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card"><div class="kpi-label">📱 Notificados</div><div class="kpi-value" style="color:#2ecc71;">{notificados}</div><div class="kpi-sub">{round(notificados/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card"><div class="kpi-label">✅ Sucessos</div><div class="kpi-value" style="color:#3498db;">{sucesso}</div><div class="kpi-sub">{round(sucesso/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="kpi-card"><div class="kpi-label">❌ Falhas</div><div class="kpi-value" style="color:#e74c3c;">{falhou}</div><div class="kpi-sub">{round(falhou/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
    k5.markdown(f'<div class="kpi-card"><div class="kpi-label">⏳ Pendentes</div><div class="kpi-value">{pendentes + em_rota}</div><div class="kpi-sub">Na Rua</div></div>', unsafe_allow_html=True)

with tab_motorista:
    rotas_unicas = sorted(df["route"].unique()) if "route" in df.columns else []
    if rotas_unicas:
        opcoes_radio, mapeamento_reverso = [], {}
        for r_orig in rotas_unicas:
            tot_n = int(df[df["route"] == r_orig]["_notificado"].sum())
            nome_display = obter_nome_banco_ou_limpo(r_orig)
            label = f"📍 {nome_display} (📱 {tot_n} Notif.)"
            opcoes_radio.append(label)
            mapeamento_reverso[label] = r_orig

        col_menu, col_conteudo = st.columns([1.3, 3.2], gap="large")
        with col_menu:
            lbl_sel = st.radio("Selecione a Rota", options=opcoes_radio, label_visibility="collapsed")
            mot_ativo = mapeamento_reverso[lbl_sel]
            
            if user['role'] in ['adm', 'supervisor']:
                st.markdown("---")
                st.markdown("✍️ **Gravação Definitiva**")
                novo_nome = st.text_input("Nome do Condutor:", value=obter_nome_banco_ou_limpo(mot_ativo), key=f"v_def_{mot_ativo}")
                if st.button("💾 Gravar no Banco", type="primary"):
                    salvar_vinculo_db(extrair_chave_permanente(mot_ativo), novo_nome.strip())
                    st.success("Salvo!")
                    time.sleep(0.8)
                    st.rerun()

            if user['role'] == 'adm':
                st.markdown("---")
                st.markdown("🚨 **Zona de Perigo**")
                if st.checkbox("Liberar exclusão de dados"):
                    if st.button("🗑️ Deletar Rota e Entregas"):
                        deletar_rota_db(mot_ativo, data_consulta)
                        st.success("Apagado do banco!")
                        time.sleep(1)
                        st.rerun()

        with col_conteudo:
            df_rota = df[df["route"] == mot_ativo].copy()
            st.markdown(f"### 🧑‍✈️ Motorista Ativo: {obter_nome_banco_ou_limpo(mot_ativo)}")
            st.dataframe(pd.DataFrame({
                "Nº Ordem": get_series(df_rota, "order"),
                "Cliente": get_series(df_rota, "title"),
                "Status Atual": get_series(df_rota, "_status_visual", "⏳ Pendente"),
                "Notificado?": get_series(df_rota, "_notificado").apply(lambda x: "Sim" if x else "Não"),
                "Check-out": get_series(df_rota, "checkout_time").apply(formatar_data)
            }), use_container_width=True, hide_index=True)

with tab_export:
    st.markdown("### 💾 Exportação do Fluxo de Carga")
    if user['role'] in ['adm', 'supervisor']:
        df_excel = pd.DataFrame({
            "Nº Ordem": get_series(df, "order"), 
            "Motorista": get_series(df, "route").apply(obter_nome_banco_ou_limpo),
            "Cliente": get_series(df, "title"), 
            "Status": get_series(df, "_status_visual", "⏳ Pendente"),
        })
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df_excel.to_excel(writer, index=False)
        st.download_button(label="📥 Baixar Planilha Excel", data=output.getvalue(), file_name=f"Relatorio_KingStar_{data_consulta}.xlsx", type="primary")
    else:
        st.warning("Seu perfil (Operacional) não tem permissão para baixar relatórios.")

if auto_refresh and is_hoje:
    time.sleep(15)
    st.rerun()
