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

def calcular_stats_motorista(df_rota):
    total = len(df_rota)
    if total == 0:
        return {"total": 0, "sucesso": 0, "falhou": 0, "pendente": 0,
                "notificados": 0, "pct_sucesso": 0, "pct_falha": 0}
    status     = get_series(df_rota, "_status_visual", "⏳ Pendente")
    sucesso    = int((status == "✅ Sucesso").sum())
    falhou     = int((status == "❌ Falhou").sum())
    pendente   = total - sucesso - falhou
    notificados = (int(get_series(df_rota, "_notificado", False).sum())
                   if "_notificado" in df_rota.columns else 0)
    return {
        "total": total, "sucesso": sucesso, "falhou": falhou, "pendente": pendente,
        "notificados": notificados,
        "pct_sucesso": round(sucesso / total * 100, 1) if total > 0 else 0,
        "pct_falha":   round(falhou  / total * 100, 1) if total > 0 else 0,
    }

# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Monitoramento · KingStar", layout="wide", page_icon="🚚")

# --- LOGIN E SESSÃO ---
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        logo_b64 = carregar_logo_base64("logo.png")
        if logo_b64:
            st.markdown(
                f'<div style="text-align:center;"><img src="data:image/png;base64,{logo_b64}" '
                f'style="height:80px;margin-bottom:20px;"></div>',
                unsafe_allow_html=True
            )
        st.markdown("<h2 style='text-align:center;color:#2c3e50;'>🔐 Acesso Restrito</h2>",
                    unsafe_allow_html=True)
        usuario = st.text_input("Usuário")
        senha   = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary", use_container_width=True):
            user = verificar_login(usuario, senha)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Credenciais inválidas. Verifique usuário e senha.")
    st.stop()

# --- ÁREA LOGADA ---
user  = st.session_state.user
papel = user['role']

# CSS GLOBAL
st.markdown("""
<style>
    /* KPIs Dashboard */
    .header-container {
        background: linear-gradient(135deg,#ffffff 0%,#f8f9fa 100%);
        border-left: 6px solid #C9A84C;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 28px;
        box-shadow: 0 4px 15px rgba(0,0,0,.05);
        display: flex;
        align-items: center;
    }
    .kpi-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 20px 16px;
        text-align: center;
        border-top: 4px solid #C9A84C;
        box-shadow: 0 4px 15px rgba(0,0,0,.05);
        height: 100%;
    }
    .kpi-label { color:#64778d; font-size:.8rem; font-weight:600; text-transform:uppercase; }
    .kpi-value { color:#2c3e50; font-size:2.2rem; font-weight:800; }
    .kpi-sub   { color:#C9A84C; font-size:.85rem; font-weight:600; }

    /* ── Cards de motorista ─────────────────── */
    .mot-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 14px 12px 10px;
        box-shadow: 0 3px 12px rgba(0,0,0,.07);
        border-top: 4px solid #C9A84C;
        position: relative;
        margin-bottom: 4px;
    }
    .mot-card.selected {
        border-top-color: #0D1F3C;
        box-shadow: 0 0 0 2px #0D1F3C, 0 6px 20px rgba(0,0,0,.12);
    }
    .mot-nome {
        font-size: .82rem;
        font-weight: 700;
        color: #0D1F3C;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-bottom: 8px;
    }
    .mot-bar-bg {
        height: 6px;
        border-radius: 3px;
        background: #e9ecef;
        margin-bottom: 8px;
        overflow: hidden;
    }
    .mot-bar-fill {
        height: 100%;
        border-radius: 3px;
        background: linear-gradient(90deg,#2ecc71,#27ae60);
    }
    .mot-stats {
        display: flex;
        justify-content: space-between;
        font-size: .71rem;
        font-weight: 600;
        color: #64778d;
        margin-bottom: 2px;
    }
    .mot-stat-ok  { color:#27ae60; }
    .mot-stat-err { color:#e74c3c; }
    .mot-stat-pen { color:#f39c12; }
    .mot-badge {
        position: absolute;
        top: 7px; right: 7px;
        background: #e8f5e9;
        color: #27ae60;
        font-size: .6rem;
        font-weight: 700;
        border-radius: 99px;
        padding: 1px 5px;
    }

    /* Detalhe motorista */
    .detalhe-header {
        background: #0D1F3C;
        color: #fff;
        border-radius: 10px 10px 0 0;
        padding: 14px 20px;
        margin-bottom: 0;
    }
    .detalhe-nome { font-size:1.1rem; font-weight:700; }
    .detalhe-sub  { font-size:.82rem; color:#C9A84C; font-weight:600; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.success(f"👤 {user['nome']}\n\nNível: **{papel.upper()}**")
    if st.button("Sair"):
        st.session_state.user = None
        st.rerun()
    st.markdown("---")
    st.markdown("### 📅 Período de Consulta")

    datas_db  = obter_datas_disponiveis_db()
    hoje      = date.today().isoformat()
    ontem     = (date.today() - timedelta(days=1)).isoformat()
    datas_disp  = [d["data"] for d in datas_db]
    opcoes_datas = []

    if hoje in datas_disp or not datas_disp:
        opcoes_datas.append(f"Hoje ({hoje})")
    if ontem in datas_disp:
        opcoes_datas.append(f"Ontem ({ontem})")
    for item in datas_db:
        if item["data"] not in (hoje, ontem):
            opcoes_datas.append(
                f"{datetime.strptime(item['data'],'%Y-%m-%d').strftime('%d/%m/%Y')} — {item['total']} entregas"
            )

    data_sel = st.selectbox("📆 Escolha o Dia:", opcoes_datas)
    data_consulta = (hoje      if "Hoje"  in data_sel else
                     ontem     if "Ontem" in data_sel else
                     datetime.strptime(data_sel.split("—")[0].strip(), "%d/%m/%Y").strftime("%Y-%m-%d"))
    is_hoje      = (data_consulta == hoje)
    auto_refresh = st.checkbox("🔄 Atualização em Tempo Real", value=is_hoje)

# ── Header ───────────────────────────────────────────────────────────────────
logo_b64 = carregar_logo_base64("logo.png")
html_logo = (f'<img src="data:image/png;base64,{logo_b64}" style="height:55px;margin-right:20px;">'
             if logo_b64 else '')
st.markdown(f"""
<div class="header-container">
    {html_logo}
    <div>
        <h1 style="color:#2c3e50;margin:0;font-size:1.8rem;font-weight:800;">
            Painel de Entregas · KingStar
        </h1>
        <p style="color:#64778d;margin:4px 0 0;font-size:1rem;font-weight:500;">
            Eco 360º · SimpliRoute ·
            <span style="color:#C9A84C;">{"🕐 Tempo Real" if is_hoje else data_consulta}</span>
        </p>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Dados ─────────────────────────────────────────────────────────────────────
tickets_raw = obter_tickets_db(data_consulta)
df          = pd.DataFrame(tickets_raw)

# ── Abas ──────────────────────────────────────────────────────────────────────
abas_nomes = ["🏠 Dashboard", "🧑‍✈️ Visão por Motorista"]
if papel in ["supervisor", "adm"]: abas_nomes.append("📥 Exportar")
if papel == "adm":                  abas_nomes.append("⚙️ Configurações")

abas = st.tabs(abas_nomes)

# ═════════════════════════════════════════════════════════════════════════════
# ABA 1 — DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
with abas[0]:
    if df.empty:
        st.info("⏳ Nenhum dado de entrega encontrado para o dia selecionado.")
    else:
        df["_notificado"] = get_series(df, "on_its_way").apply(
            lambda x: bool(x and str(x).strip() not in ("", "None", "null"))
        )
        total       = len(df)
        notificados = int(df["_notificado"].sum())
        sucesso     = int((get_series(df, "_status_visual") == "✅ Sucesso").sum())
        falhou      = int((get_series(df, "_status_visual") == "❌ Falhou").sum())
        pendentes   = total - sucesso - falhou

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-label">📦 Total</div><div class="kpi-value">{total}</div><div class="kpi-sub">Carga Oficial</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-label">📱 Notificados</div><div class="kpi-value" style="color:#2ecc71;">{notificados}</div><div class="kpi-sub">{round(notificados/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-label">✅ Sucessos</div><div class="kpi-value" style="color:#3498db;">{sucesso}</div><div class="kpi-sub">{round(sucesso/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-label">❌ Falhas</div><div class="kpi-value" style="color:#e74c3c;">{falhou}</div><div class="kpi-sub">{round(falhou/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
        k5.markdown(f'<div class="kpi-card"><div class="kpi-label">⏳ Pendentes</div><div class="kpi-value">{pendentes}</div><div class="kpi-sub">Na Rua</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({
            "Ordem":      get_series(df, "order"),
            "Motorista":  get_series(df, "route").apply(obter_nome_banco_ou_limpo),
            "Cliente":    get_series(df, "title"),
            "Status":     get_series(df, "_status_visual", "⏳ Pendente"),
            "Notificado": get_series(df, "_notificado").apply(lambda x: "Sim" if x else "Não"),
            "Check-out":  get_series(df, "checkout_time").apply(formatar_data),
        }), use_container_width=True, hide_index=True)

# ═════════════════════════════════════════════════════════════════════════════
# ABA 2 — VISÃO POR MOTORISTA  (grid 6 colunas + paginação)
# ═════════════════════════════════════════════════════════════════════════════
with abas[1]:
    if df.empty:
        st.info("⏳ Nenhuma rota ou motorista ativo nesta data.")
    else:
        # Garante _notificado
        if "_notificado" not in df.columns:
            df["_notificado"] = get_series(df, "on_its_way").apply(
                lambda x: bool(x and str(x).strip() not in ("", "None", "null"))
            )

        rotas_unicas = sorted(df["route"].unique()) if "route" in df.columns else []

        if not rotas_unicas:
            st.info("Nenhuma rota encontrada.")
        else:
            # ── Barra de controle ───────────────────────────────────────
            ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 5])

            with ctrl1:
                por_pagina = st.selectbox(
                    "Motoristas por página",
                    options=[12, 15, 30, 45],
                    index=0,
                    key="mot_por_pagina",
                )

            total_rotas = len(rotas_unicas)
            total_pags  = max(1, -(-total_rotas // por_pagina))   # ceil

            # Reseta page se ficou fora do range
            if "mot_pagina" not in st.session_state or st.session_state.mot_pagina > total_pags:
                st.session_state.mot_pagina = 1

            with ctrl2:
                pag_atual = st.number_input(
                    "Página",
                    min_value=1, max_value=total_pags,
                    value=st.session_state.mot_pagina,
                    step=1,
                    key="mot_pagina_input",
                )
                st.session_state.mot_pagina = int(pag_atual)

            with ctrl3:
                st.markdown(
                    f'<div style="padding-top:28px;color:#64778d;font-size:.85rem;font-weight:600;">'
                    f'Página {pag_atual} de {total_pags}&nbsp;·&nbsp;'
                    f'{total_rotas} motorista{"s" if total_rotas!=1 else ""} no total'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # Botões de navegação rápida
            n1, n2, n3, n4, *_ = st.columns([1, 1, 1, 1, 5])
            if n1.button("⏮", key="pag_ini", disabled=(pag_atual == 1), help="Início"):
                st.session_state.mot_pagina = 1; st.rerun()
            if n2.button("◀", key="pag_ant", disabled=(pag_atual == 1), help="Anterior"):
                st.session_state.mot_pagina = pag_atual - 1; st.rerun()
            if n3.button("▶", key="pag_prox", disabled=(pag_atual == total_pags), help="Próxima"):
                st.session_state.mot_pagina = pag_atual + 1; st.rerun()
            if n4.button("⏭", key="pag_fim", disabled=(pag_atual == total_pags), help="Fim"):
                st.session_state.mot_pagina = total_pags; st.rerun()

            st.markdown("---")

            # ── Fatia da página atual ────────────────────────────────────
            ini = (st.session_state.mot_pagina - 1) * por_pagina
            rotas_pagina = rotas_unicas[ini: ini + por_pagina]

            # Estado do motorista selecionado
            if "mot_selecionado" not in st.session_state:
                st.session_state.mot_selecionado = None

            # ── Grid 6 colunas ───────────────────────────────────────────
            N_COLS = 6
            linhas = [rotas_pagina[i:i+N_COLS] for i in range(0, len(rotas_pagina), N_COLS)]

            for linha in linhas:
                cols = st.columns(N_COLS)
                for col, rota in zip(cols, linha):
                    nome       = obter_nome_banco_ou_limpo(rota)
                    df_rota    = df[df["route"] == rota]
                    stats      = calcular_stats_motorista(df_rota)
                    selecionado = (st.session_state.mot_selecionado == rota)

                    with col:
                        # Card HTML
                        st.markdown(f"""
                        <div class="mot-card {'selected' if selecionado else ''}">
                            {"<div class='mot-badge'>📱 Notif.</div>" if stats['notificados'] > 0 else ""}
                            <div class="mot-nome" title="{nome}">{nome}</div>
                            <div class="mot-bar-bg">
                                <div class="mot-bar-fill" style="width:{stats['pct_sucesso']}%;"></div>
                            </div>
                            <div class="mot-stats">
                                <span class="mot-stat-ok">✅{stats['sucesso']}</span>
                                <span class="mot-stat-err">❌{stats['falhou']}</span>
                                <span class="mot-stat-pen">⏳{stats['pendente']}</span>
                                <span>/{stats['total']}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        # Botão de seleção abaixo do card
                        btn_label = "✔ Selecionado" if selecionado else "Ver detalhes"
                        if st.button(btn_label, key=f"btn_mot_{rota}",
                                     use_container_width=True,
                                     type="primary" if selecionado else "secondary"):
                            st.session_state.mot_selecionado = (None if selecionado else rota)
                            st.rerun()

            # ── Painel de detalhe ────────────────────────────────────────
            mot_ativo = st.session_state.mot_selecionado
            if mot_ativo and "route" in df.columns and mot_ativo in df["route"].values:
                nome_ativo = obter_nome_banco_ou_limpo(mot_ativo)
                df_rota    = df[df["route"] == mot_ativo]
                stats      = calcular_stats_motorista(df_rota)

                st.markdown("---")
                st.markdown(f"""
                <div class="detalhe-header">
                    <div class="detalhe-nome">🧑‍✈️ {nome_ativo}</div>
                    <div class="detalhe-sub">
                        {stats['total']} entregas &nbsp;·&nbsp;
                        {stats['pct_sucesso']}% concluídas &nbsp;·&nbsp;
                        {stats['notificados']} notificações enviadas
                    </div>
                </div>
                """, unsafe_allow_html=True)

                d1, d2, d3, d4 = st.columns(4)
                d1.markdown(f'<div class="kpi-card"><div class="kpi-label">📦 Total</div><div class="kpi-value">{stats["total"]}</div></div>', unsafe_allow_html=True)
                d2.markdown(f'<div class="kpi-card"><div class="kpi-label">✅ Sucesso</div><div class="kpi-value" style="color:#2ecc71;">{stats["sucesso"]}</div><div class="kpi-sub">{stats["pct_sucesso"]}%</div></div>', unsafe_allow_html=True)
                d3.markdown(f'<div class="kpi-card"><div class="kpi-label">❌ Falhou</div><div class="kpi-value" style="color:#e74c3c;">{stats["falhou"]}</div><div class="kpi-sub">{stats["pct_falha"]}%</div></div>', unsafe_allow_html=True)
                d4.markdown(f'<div class="kpi-card"><div class="kpi-label">⏳ Pendente</div><div class="kpi-value" style="color:#f39c12;">{stats["pendente"]}</div></div>', unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame({
                    "Cliente":    get_series(df_rota, "title"),
                    "Status":     get_series(df_rota, "_status_visual"),
                    "Notificado": get_series(df_rota, "_notificado").apply(lambda x: "Sim" if x else "Não"),
                    "Observação": get_series(df_rota, "checkout_observation"),
                    "Check-out":  get_series(df_rota, "checkout_time").apply(formatar_data),
                }), use_container_width=True, hide_index=True)

                # Ações supervisor/adm
                if papel in ["supervisor", "adm"]:
                    st.markdown("---")
                    novo_nome = st.text_input(
                        "Alterar nome do condutor:",
                        value=obter_nome_banco_ou_limpo(mot_ativo),
                        key="edit_nome_cond"
                    )
                    if st.button("💾 Salvar Condutor"):
                        salvar_vinculo_db(extrair_chave_permanente(mot_ativo), novo_nome.strip())
                        st.rerun()

                if papel == "adm":
                    st.markdown("---")
                    st.error("🚨 Zona de Exclusão")
                    if st.button("🗑️ Excluir Carga do Motorista"):
                        deletar_rota_db(mot_ativo, data_consulta)
                        st.session_state.mot_selecionado = None
                        st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# ABA 3 — EXPORTAR
# ═════════════════════════════════════════════════════════════════════════════
if "📥 Exportar" in abas_nomes:
    idx = abas_nomes.index("📥 Exportar")
    with abas[idx]:
        if df.empty:
            st.warning("⚠️ Não há planilhas para gerar pois este dia não possui registros.")
        else:
            st.write("Extração completa dos dados processados.")
            df_excel = pd.DataFrame({
                "Ordem":     get_series(df, "order"),
                "Motorista": get_series(df, "route").apply(obter_nome_banco_ou_limpo),
                "Cliente":   get_series(df, "title"),
                "Status":    get_series(df, "_status_visual", "⏳ Pendente"),
                "Check-out": get_series(df, "checkout_time").apply(formatar_data),
                "Anotações": get_series(df, "notes"),
            })
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_excel.to_excel(writer, index=False)
            st.download_button(
                "📥 Baixar Planilha",
                data=output.getvalue(),
                file_name=f"Relatorio_{data_consulta}.xlsx",
                type="primary",
            )

# ═════════════════════════════════════════════════════════════════════════════
# ABA 4 — CONFIGURAÇÕES (ADM)
# ═════════════════════════════════════════════════════════════════════════════
if "⚙️ Configurações" in abas_nomes:
    idx = abas_nomes.index("⚙️ Configurações")
    with abas[idx]:
        st.subheader("👥 Gestão de Acessos")

        with st.expander("➕ Cadastrar Novo Usuário", expanded=True):
            with st.form("form_novo_user"):
                c1, c2 = st.columns(2)
                novo_nome  = c1.text_input("Nome Completo")
                novo_user  = c2.text_input("Usuário (Login)")
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
            for i, u in enumerate(lista_users):
                username_limpo = u.get('usuario') or f"usuario_{i}"
                cu1, cu2, cu3, cu4 = st.columns([2, 2, 2, 1])
                cu1.write(f"**{u.get('nome', 'Sem Nome')}**")
                cu2.write(f"Login: `{username_limpo}`")
                cu3.write(f"Nível: {str(u.get('role', 'operacional')).upper()}")
                if cu4.button("🗑️", key=f"del_{username_limpo}_{i}"):
                    if username_limpo != "admin":
                        deletar_usuario(username_limpo)
                        st.rerun()

# Auto-refresh
if auto_refresh and is_hoje and not df.empty:
    time.sleep(15)
    st.rerun()
