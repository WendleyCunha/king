import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import os
import io
import time
import base64
from database import (verificar_login, criar_usuario, listar_usuarios, deletar_usuario,
                      obter_tickets_db, obter_datas_disponiveis_db, 
                      obter_vinculo_db, salvar_vinculo_db, deletar_rota_db)

# --- FUNÇÕES DE APOIO ---
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

def carregar_logo_base64(caminho_img):
    if os.path.exists(caminho_img):
        with open(caminho_img, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode()
    return None

st.set_page_config(page_title="Monitoramento · KingStar", layout="wide", page_icon="🚚")

# --- LOGIN E SESSÃO ---
if "user" not in st.session_state: st.session_state.user = None

if not st.session_state.user:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        logo_b64 = carregar_logo_base64("logo.png")
        if logo_b64:
            st.markdown(f'<div style="text-align: center;"><img src="data:image/png;base64,{logo_b64}" style="height: 80px; margin-bottom: 20px;"></div>', unsafe_allow_html=True)
        
        st.markdown("<h2 style='text-align: center; color: #2c3e50;'>🔐 Acesso Restrito</h2>", unsafe_allow_html=True)
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary", use_container_width=True):
            user = verificar_login(usuario, senha)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Credenciais inválidas. Verifique usuário e senha.")
    st.stop()

# --- ÁREA LOGADA ---
user = st.session_state.user
papel = user['role']

# Restauração do CSS Original
st.markdown("""
<style>
    .header-container { background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%); border-left: 6px solid #C9A84C; border-radius: 12px; padding: 20px 24px; margin-bottom: 28px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); display: flex; align-items: center; }
    .kpi-card { background: #ffffff; border-radius: 12px; padding: 20px 16px; text-align: center; border-top: 4px solid #C9A84C; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05); height: 100%; }
    .kpi-label { color: #64778d; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; }
    .kpi-value { color: #2c3e50; font-size: 2.2rem; font-weight: 800; }
    .kpi-sub { color: #C9A84C; font-size: 0.85rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.success(f"👤 {user['nome']}\n\nNível: **{papel.upper()}**")
    if st.button("Sair"):
        st.session_state.user = None
        st.rerun()
    st.markdown("---")
    st.markdown("### 📅 Período de Consulta")
    
    datas_db = obter_datas_disponiveis_db()
    hoje, ontem = date.today().isoformat(), (date.today() - timedelta(days=1)).isoformat()
    datas_disp = [d["data"] for d in datas_db]
    opcoes_datas = []
    
    if hoje in datas_disp or not datas_disp: opcoes_datas.append(f"Hoje ({hoje})")
    if ontem in datas_disp: opcoes_datas.append(f"Ontem ({ontem})")
    for item in datas_db:
        if item["data"] not in (hoje, ontem): opcoes_datas.append(f"{datetime.strptime(item['data'], '%Y-%m-%d').strftime('%d/%m/%Y')} — {item['total']} entregas")

    data_sel = st.selectbox("📆 Escolha o Dia:", opcoes_datas)
    data_consulta = hoje if "Hoje" in data_sel else ontem if "Ontem" in data_sel else datetime.strptime(data_sel.split("—")[0].strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    is_hoje = (data_consulta == hoje)
    auto_refresh = st.checkbox("🔄 Atualização em Tempo Real", value=is_hoje)

# Header com Logo
logo_b64 = carregar_logo_base64("logo.png")
html_logo = f'<img src="data:image/png;base64,{logo_b64}" style="height: 55px; margin-right: 20px;">' if logo_b64 else ''
st.markdown(f"""
<div class="header-container">
    {html_logo}
    <div>
        <h1 style="color:#2c3e50; margin:0; font-size:1.8rem; font-weight:800;">Painel de Entregas · KingStar</h1>
        <p style="color:#64778d; margin:4px 0 0; font-size:1rem; font-weight:500;">Eco 360º · SimpliRoute · <span style="color:#C9A84C;">{"🕐 Tempo Real" if is_hoje else data_consulta}</span></p>
    </div>
</div>
""", unsafe_allow_html=True)

# Coleta de Dados (Se não houver dados, o DataFrame apenas virará uma estrutura vazia sem travar o app)
tickets_raw = obter_tickets_db(data_consulta)
df = pd.DataFrame(tickets_raw)

# Configuração Dinâmica de Abas (Sempre geradas com base nas permissões)
abas_nomes = ["🏠 Dashboard", "🧑‍✈️ Visão por Motorista"]
if papel in ["supervisor", "adm"]: abas_nomes.append("📥 Exportar")
if papel == "adm": abas_nomes.append("⚙️ Configurações")

abas = st.tabs(abas_nomes)

# ABA 1: DASHBOARD
with abas[0]:
    if df.empty:
        st.info("⏳ Nenhum dado de entrega encontrado para o dia selecionado. Mas o sistema está online! Acesse as outras abas no topo normalmente.")
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
            "Ordem": get_series(df, "order"), "Motorista": get_series(df, "route").apply(obter_nome_banco_ou_limpo),
            "Cliente": get_series(df, "title"), "Status": get_series(df, "_status_visual", "⏳ Pendente"),
            "Notificado": get_series(df, "_notificado").apply(lambda x: "Sim" if x else "Não"),
            "Check-out": get_series(df, "checkout_time").apply(formatar_data)
        }), use_container_width=True, hide_index=True)

# ABA 2: MOTORISTAS
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
                    if st.button("Salvar Condutor"):
                        salvar_vinculo_db(extrair_chave_permanente(mot_ativo), novo_nome.strip())
                        st.rerun()

                if papel == "adm":
                    st.markdown("---")
                    st.error("🚨 Zona de Exclusão")
                    if st.button("Excluir Carga do Motorista"):
                        deletar_rota_db(mot_ativo, data_consulta)
                        st.rerun()

            with col_m2:
                df_rota = df[df["route"] == mot_ativo]
                st.dataframe(pd.DataFrame({
                    "Cliente": get_series(df_rota, "title"), "Status": get_series(df_rota, "_status_visual"),
                    "Observação": get_series(df_rota, "checkout_observation")
                }), use_container_width=True, hide_index=True)

# ABA 3: EXPORTAR (Se disponível para o nível)
if "📥 Exportar" in abas_nomes:
    idx = abas_nomes.index("📥 Exportar")
    with abas[idx]:
        if df.empty:
            st.warning("⚠️ Não há planilhas para gerar pois este dia não possui registros.")
        else:
            st.write("Extração completa dos dados processados.")
            df_excel = pd.DataFrame({
                "Ordem": get_series(df, "order"), "Motorista": get_series(df, "route").apply(obter_nome_banco_ou_limpo),
                "Cliente": get_series(df, "title"), "Status": get_series(df, "_status_visual", "⏳ Pendente"),
                "Check-out": get_series(df, "checkout_time").apply(formatar_data), "Anotações": get_series(df, "notes")
            })
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer: df_excel.to_excel(writer, index=False)
            st.download_button("📥 Baixar Planilha", data=output.getvalue(), file_name=f"Relatorio_{data_consulta}.xlsx", type="primary")

# ABA 4: CONFIGURAÇÕES (ADM - Sempre ativa e funcional!)
if "⚙️ Configurações" in abas_nomes:
    idx = abas_nomes.index("⚙️ Configurações")
    with abas[idx]:
        st.subheader("👥 Gestão de Acessos")
        
        with st.expander("➕ Cadastrar Novo Usuário", expanded=True):
            with st.form("form_novo_user"):
                c1, c2 = st.columns(2)
                novo_nome = c1.text_input("Nome Completo")
                novo_user = c2.text_input("Usuário (Login)")
                nova_senha = c1.text_input("Senha", type="password")
                novo_nivel = c2.selectbox("Nível de Acesso", ["operacional", "supervisor", "adm"])
                if st.form_submit_button("Criar Acesso"):
                    if novo_nome and novo_user and nova_senha:
                        criar_usuario(novo_nome, novo_user, nova_senha, novo_nivel)
                        st.success(f"Usuário {novo_user} criado com sucesso!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("Por favor, preencha todos os campos.")

        st.markdown("---")
        st.write("**Usuários Ativos no Sistema**")
        lista_users = listar_usuarios()
        if lista_users:
            for u in lista_users:
                col_u1, col_u2, col_u3, col_u4 = st.columns([2, 2, 2, 1])
                col_u1.write(f"**{u.get('nome')}**")
                col_u2.write(f"Login: `{u.get('usuario')}`")
                col_u3.write(f"Nível: {u.get('role').upper()}")
                if col_u4.button("🗑️", key=f"del_{u.get('usuario')}"):
                    if u.get('usuario') != "admin": # Proteção para não deletar o master temporário
                        deletar_usuario(u.get('usuario'))
                        st.rerun()

if auto_refresh and is_hoje and not df.empty:
    time.sleep(15)
    st.rerun()
