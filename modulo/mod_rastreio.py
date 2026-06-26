import sys, os, io, time
from datetime import datetime, timezone, timedelta
import pandas as pd
import streamlit as st

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database import (obter_vinculo_db, salvar_vinculo_db, deletar_rota_db,
                      pode_editar, pode_deletar, obter_tickets_db)

BRT           = timezone(timedelta(hours=-3))
TRACKING_BASE = "https://livetracking.simpliroute.com/widget/account/88033/tracking/"

def get_series(df, col, default=""):
    if col in df.columns: return df[col]
    return pd.Series([default]*len(df))

def formatar_data(v):
    if not v or str(v).strip() in ("","None","null"): return "—"
    try: return datetime.fromisoformat(str(v).strip().replace("+00:00","").replace("Z","")).strftime("%d/%m %H:%M")
    except: return str(v)[:16]

def extrair_chave(rota):
    if not rota: return "SEM_ROTA"
    return rota.split(" - ",1)[1].strip() if " - " in rota else rota.strip()

def nome_motorista(rota):
    return obter_vinculo_db(extrair_chave(rota))

def garantir_colunas(df):
    if "_notificado" not in df.columns:
        df["_notificado"] = get_series(df,"on_its_way").apply(
            lambda x: bool(x and str(x).strip().lower() not in ("","none","null","false")))
    else:
        df["_notificado"] = df["_notificado"].apply(
            lambda x: x if isinstance(x,bool) else str(x).lower() not in ("false","0","none","null",""))
    df["_status_visual"] = df["_status_visual"].fillna("⏳ Pendente") \
        if "_status_visual" in df.columns else pd.Series(["⏳ Pendente"]*len(df))
    for col, val in {
        "title":"—","address":"—","route":"Rota não identificada",
        "contact_name":"—","contact_phone":"—","contact_email":"—",
        "tracking_id":"—","on_its_way":None,"checkout_time":None,"checkin_time":None,
        "estimated_time_arrival":"—","checkout_observation":"—","checkout_comment":"—",
        "notes":"—","planned_date":"—","order":"—",
    }.items():
        if col not in df.columns: df[col] = val
    return df

def aplicar_busca(df, termo):
    if not termo.strip(): return df
    t = termo.strip().lower()
    mask = (
        get_series(df,"title").str.lower().str.contains(t,na=False) |
        get_series(df,"route").str.lower().str.contains(t,na=False) |
        get_series(df,"address").str.lower().str.contains(t,na=False) |
        get_series(df,"contact_name").str.lower().str.contains(t,na=False) |
        get_series(df,"contact_phone").str.lower().str.contains(t,na=False) |
        get_series(df,"tracking_id").str.lower().str.contains(t,na=False)
    )
    nome_mask = get_series(df,"route").apply(nome_motorista).str.lower().str.contains(t,na=False)
    return df[mask | nome_mask]

# ── FUNÇÃO PRINCIPAL ──────────────────────────────────────────────
# Assinatura nova: data_consulta resolvida AQUI dentro
def renderizar_rastreio(papel: str, user: dict = None,
                        datas_db: list = None, pode_exp: bool = False):
    if user is None: user = {"role": papel}
    if datas_db is None: datas_db = []

    hoje  = datetime.now(BRT).date().isoformat()
    ontem = (datetime.now(BRT).date() - __import__('datetime').timedelta(days=1)).isoformat()
    datas_disp = [d["data"] for d in datas_db]

    # ── Seletor de data + busca numa linha ───────────────────────
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 1.5, 1.5])
    with fc1:
        opcoes = []
        if hoje in datas_disp or not datas_disp: opcoes.append(f"Hoje ({hoje})")
        if ontem in datas_disp: opcoes.append(f"Ontem ({ontem})")
        for item in datas_db:
            if item["data"] not in (hoje, ontem):
                try:    opcoes.append(f"{datetime.strptime(item['data'],'%Y-%m-%d').strftime('%d/%m/%Y')} — {item['total']}")
                except: opcoes.append(item["data"])
        if not opcoes: opcoes = [f"Hoje ({hoje})"]
        data_sel = st.selectbox("📅 Período", opcoes, label_visibility="visible", key="data_sel_rastreio")

    with fc2:
        termo = st.text_input("🔍 Buscar", placeholder="Placa, motorista, cliente, telefone, tracking...",
                              label_visibility="visible", key="busca_rastreio")
    with fc3:
        f_st = st.selectbox("Status", ["Todos","✅ Sucesso","❌ Falhou","📱 Notificado","⏳ Pendente"],
                            label_visibility="visible", key="f_status")
    with fc4:
        f_nt = st.selectbox("Notificação", ["Todas","Sim","Não"],
                            label_visibility="visible", key="f_notif")

    # Resolve data
    if   "Hoje"  in data_sel: data_consulta = hoje
    elif "Ontem" in data_sel: data_consulta = ontem
    else:
        try:    data_consulta = datetime.strptime(data_sel.split("—")[0].strip(),"%d/%m/%Y").strftime("%Y-%m-%d")
        except: data_consulta = hoje
    is_hoje = (data_consulta == hoje)

    # Carrega dados
    tickets_raw = obter_tickets_db(data_consulta)
    df = pd.DataFrame(tickets_raw) if tickets_raw else pd.DataFrame()

    if df.empty:
        st.info("⏳ Nenhum dado de entrega para o dia selecionado.")
        if is_hoje: time.sleep(20); st.rerun()
        return

    df = garantir_colunas(df.copy())

    # Aplica filtros
    df_f = aplicar_busca(df, termo)
    if f_st != "Todos":  df_f = df_f[df_f["_status_visual"] == f_st]
    if f_nt == "Sim":    df_f = df_f[df_f["_notificado"] == True]
    elif f_nt == "Não":  df_f = df_f[df_f["_notificado"] == False]
    if termo and df_f.empty:
        st.warning(f"Nenhum resultado para **{termo}**."); return

    # ── Abas ──────────────────────────────────────────────────────
    abas_nomes = ["🏠 Dashboard", "🧑 Visão por Motorista"]
    if pode_exp: abas_nomes.append("📥 Exportar")
    abas = st.tabs(abas_nomes)

    # ══ DASHBOARD ════════════════════════════════════════════════
    with abas[0]:
        total    = len(df)
        notif    = int(df["_notificado"].sum())
        sucesso  = int((df["_status_visual"]=="✅ Sucesso").sum())
        falhou   = int((df["_status_visual"]=="❌ Falhou").sum())
        pendente = total - sucesso - falhou
        motores  = len([r for r in df["route"].unique()
                        if r and "não identificada" not in str(r).lower()])

        k1,k2,k3,k4,k5,k6 = st.columns(6)
        k1.markdown(f'<div class="kpi-card gold"><div class="kpi-label">📦 Total</div><div class="kpi-value">{total}</div><div class="kpi-sub">Carga do dia</div></div>',unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card green"><div class="kpi-label">📱 Notificados</div><div class="kpi-value">{notif}</div><div class="kpi-sub">{round(notif/total*100,1) if total else 0}%</div></div>',unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card blue"><div class="kpi-label">✅ Sucessos</div><div class="kpi-value">{sucesso}</div><div class="kpi-sub">{round(sucesso/total*100,1) if total else 0}%</div></div>',unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card red"><div class="kpi-label">❌ Falhas</div><div class="kpi-value">{falhou}</div><div class="kpi-sub">{round(falhou/total*100,1) if total else 0}%</div></div>',unsafe_allow_html=True)
        k5.markdown(f'<div class="kpi-card gray"><div class="kpi-label">⏳ Pendentes</div><div class="kpi-value">{pendente}</div><div class="kpi-sub">Na rua</div></div>',unsafe_allow_html=True)
        k6.markdown(f'<div class="kpi-card gold"><div class="kpi-label">🧑 Motoristas</div><div class="kpi-value">{motores}</div><div class="kpi-sub">Em operação</div></div>',unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        if termo: st.info(f"🔍 {len(df_f)} resultado(s) para **{termo}**")

        rotas = [r for r in sorted(df_f["route"].unique())
                 if r and "não identificada" not in str(r).lower()] if "route" in df_f.columns else []
        if rotas:
            st.markdown("### 🧑 Motoristas em Operação")
            cols = st.columns(min(len(rotas), 4))
            for idx, rota in enumerate(rotas):
                dr   = df_f[df_f["route"]==rota]
                nome = nome_motorista(rota)
                tot  = len(dr); ok = int((dr["_status_visual"]=="✅ Sucesso").sum())
                fail = int((dr["_status_visual"]=="❌ Falhou").sum())
                nt   = int(dr["_notificado"].sum())
                pct_n= round(nt/tot*100,1) if tot else 0
                pct_o= round(ok/tot*100) if tot else 0
                with cols[idx%4]:
                    st.markdown(f"""
                    <div class="driver-card">
                        <div style="font-size:0.92rem;font-weight:700;color:#2c3e50;">{nome}</div>
                        <div style="font-size:0.71rem;color:#7f8c8d;margin-bottom:8px;">{rota}</div>
                        <div style="background:#e8ecf0;border-radius:4px;height:5px;margin-bottom:3px;">
                          <div style="background:#2980b9;height:5px;border-radius:4px;width:{pct_o}%;"></div>
                        </div>
                        <div style="font-size:0.7rem;color:#64778d;margin-bottom:7px;">{ok}/{tot} ({pct_o}%)</div>
                        <div>
                            <span class="tag tn">📱 {nt} ({pct_n}%)</span>
                            <span class="tag tg">📦 {tot}</span>
                            <span class="tag tb">✅ {ok}</span>
                            <span class="tag tr">❌ {fail}</span>
                        </div>
                    </div>""", unsafe_allow_html=True)

                    with st.popover(f"📋 {nt} notificado(s)", use_container_width=True):
                        df_n = dr[dr["_notificado"]==True]
                        if df_n.empty: st.info("Nenhum notificado ainda.")
                        else:
                            for _, row in df_n.iterrows():
                                tid = str(row.get("tracking_id","") or "").strip()
                                url = f"{TRACKING_BASE}{tid}" if tid not in ("","—","nan","None") else ""
                                st.markdown(
                                    f"**#{row.get('order','—')} · {row.get('title','—')}**  \n"
                                    f"<span style='font-size:0.8rem;color:#64778d;'>📍 {row.get('address','—')}</span>  \n"
                                    f"<span style='font-size:0.8rem;color:#64778d;'>Notif.: {formatar_data(row.get('on_its_way'))} · {row.get('_status_visual','')}</span>",
                                    unsafe_allow_html=True)
                                if url:
                                    cl,cc = st.columns([3,1])
                                    with cl: st.markdown(f'<a href="{url}" target="_blank" style="font-size:0.8rem;color:#2980b9;word-break:break-all;">{url}</a>', unsafe_allow_html=True)
                                    with cc:
                                        if st.button("📋", key=f"cp_{rota}_{tid}"):
                                            st.components.v1.html(f"<script>navigator.clipboard.writeText('{url}');</script>", height=0)
                                            st.toast("Copiado!", icon="✅")
                                else: st.caption("⚠️ Sem tracking ID")
                                st.markdown("<hr style='margin:5px 0;border:none;border-top:1px solid #eee;'>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown(f"**{len(df_f)} entregas**")
        st.dataframe(pd.DataFrame({
            "Ordem":    get_series(df_f,"order"),
            "Motorista":get_series(df_f,"route").apply(nome_motorista),
            "Cliente":  get_series(df_f,"title"),
            "Endereço": get_series(df_f,"address"),
            "Status":   df_f["_status_visual"],
            "Notif.":   df_f["_notificado"].apply(lambda x:"Sim" if x else "Não"),
            "Notif. em":get_series(df_f,"on_its_way").apply(formatar_data),
            "Check-out":get_series(df_f,"checkout_time").apply(formatar_data),
            "Telefone": get_series(df_f,"contact_phone"),
            "Tracking": get_series(df_f,"tracking_id"),
        }), use_container_width=True, hide_index=True)

    # ══ VISÃO POR MOTORISTA ═══════════════════════════════════════
    with abas[1]:
        rotas = [r for r in sorted(df["route"].unique())
                 if r and "não identificada" not in str(r).lower()] if "route" in df.columns else []
        if not rotas: st.info("Nenhuma rota registrada."); return

        opcoes_m, mapa = [], {}
        for r in rotas:
            n   = int(df[df["route"]==r]["_notificado"].sum())
            lbl = f"{nome_motorista(r)} (📱 {n})"
            opcoes_m.append(lbl); mapa[lbl] = r

        col_m, col_d = st.columns([1.5, 3])
        with col_m:
            sel       = st.radio("", opcoes_m, label_visibility="collapsed")
            mot_ativo = mapa[sel]

            if pode_editar(user):
                st.markdown("---")
                nn = st.text_input("Nome do condutor:", value=nome_motorista(mot_ativo), key=f"nm_{mot_ativo}")
                if st.button("Salvar nome", key=f"sv_{mot_ativo}", type="primary", use_container_width=True):
                    salvar_vinculo_db(extrair_chave(mot_ativo), nn.strip())
                    st.success("Salvo!"); time.sleep(.5); st.rerun()
            else:
                st.markdown("---")
                st.caption(f"Condutor: **{nome_motorista(mot_ativo)}**")
                st.caption("🔒 Edição restrita.")

            if pode_deletar(user):
                st.markdown("---"); st.error("Zona de Perigo")
                if st.checkbox("Liberar exclusão", key=f"chk_{mot_ativo}"):
                    if st.button("Excluir Rota", key=f"del_{mot_ativo}", use_container_width=True):
                        deletar_rota_db(mot_ativo, data_consulta)
                        st.success("Excluído!"); time.sleep(1); st.rerun()

        with col_d:
            dr   = df[df["route"]==mot_ativo].copy()
            tot  = len(dr); nt = int(dr["_notificado"].sum())
            ok   = int((dr["_status_visual"]=="✅ Sucesso").sum())
            fail = int((dr["_status_visual"]=="❌ Falhou").sum())
            pct  = round(ok/tot*100) if tot else 0

            st.markdown(f"""
            <div style="background:#fff;border-left:6px solid #C9A84C;border-radius:10px;
                        padding:14px;margin-bottom:12px;border:1px solid #e2e8f0;">
                <h3 style="margin:0;color:#2c3e50;">{nome_motorista(mot_ativo)}</h3>
                <p style="color:#64778d;font-size:0.8rem;margin:3px 0 10px;">{mot_ativo}</p>
                <span class="tag tg">📦 {tot}</span>
                <span class="tag tn">📱 {nt}</span>
                <span class="tag tb">✅ {ok}</span>
                <span class="tag tr">❌ {fail}</span>
                <div style="background:#e8ecf0;border-radius:4px;height:6px;margin:10px 0 3px;">
                  <div style="background:#2980b9;height:6px;border-radius:4px;width:{pct}%;"></div>
                </div>
                <span style="font-size:0.73rem;color:#64778d;">{ok}/{tot} concluídas ({pct}%)</span>
            </div>""", unsafe_allow_html=True)

            tf, tfl = st.tabs(["📋 Fila de Clientes","⚠️ Ocorrências"])
            with tf:
                st.dataframe(pd.DataFrame({
                    "Ordem":    get_series(dr,"order"),
                    "Cliente":  get_series(dr,"title"),
                    "Endereço": get_series(dr,"address"),
                    "Status":   dr["_status_visual"],
                    "Notif.":   dr["_notificado"].apply(lambda x:"Sim" if x else "Não"),
                    "Notif. em":get_series(dr,"on_its_way").apply(formatar_data),
                    "Check-in": get_series(dr,"checkin_time").apply(formatar_data),
                    "Check-out":get_series(dr,"checkout_time").apply(formatar_data),
                    "ETA":      get_series(dr,"estimated_time_arrival"),
                    "Telefone": get_series(dr,"contact_phone"),
                    "Obs":      get_series(dr,"checkout_observation"),
                    "Tracking": get_series(dr,"tracking_id"),
                }), use_container_width=True, hide_index=True)
            with tfl:
                df_err = dr[dr["_status_visual"]=="❌ Falhou"]
                if df_err.empty: st.success("Nenhuma ocorrência.")
                else:
                    st.dataframe(pd.DataFrame({
                        "Ordem":  get_series(df_err,"order"),
                        "Cliente":get_series(df_err,"title"),
                        "Motivo": get_series(df_err,"checkout_observation"),
                        "Detalhe":get_series(df_err,"checkout_comment","—"),
                        "Horário":get_series(df_err,"checkout_time").apply(formatar_data),
                    }), use_container_width=True, hide_index=True)

    # ══ EXPORTAR ══════════════════════════════════════════════════
    if pode_exp:
        with abas[2]:
            st.markdown("### 💾 Exportação de Dados")

            def montar(df_src):
                return pd.DataFrame({
                    "Ordem":      get_series(df_src,"order"),
                    "Motorista":  get_series(df_src,"route").apply(nome_motorista),
                    "Cliente":    get_series(df_src,"title"),
                    "Endereço":   get_series(df_src,"address"),
                    "Status":     get_series(df_src,"_status_visual","⏳ Pendente"),
                    "Notificado": get_series(df_src,"_notificado").apply(lambda x:"Sim" if x else "Não"),
                    "Notif. em":  get_series(df_src,"on_its_way").apply(formatar_data),
                    "Check-in":   get_series(df_src,"checkin_time").apply(formatar_data),
                    "Check-out":  get_series(df_src,"checkout_time").apply(formatar_data),
                    "ETA":        get_series(df_src,"estimated_time_arrival"),
                    "Obs":        get_series(df_src,"checkout_observation"),
                    "Tracking":   get_series(df_src,"tracking_id"),
                })

            ec1, ec2 = st.columns(2)
            with ec1:
                st.markdown(f"#### 📅 Dia: `{data_consulta}`")
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as w: montar(df).to_excel(w, index=False)
                st.download_button(f"📥 Baixar {data_consulta}", out.getvalue(),
                    f"KingStar_{data_consulta}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary", use_container_width=True)
            with ec2:
                mes     = datetime.strptime(data_consulta,"%Y-%m-%d").strftime("%Y-%m")
                mes_lbl = datetime.strptime(data_consulta,"%Y-%m-%d").strftime("%B/%Y")
                st.markdown(f"#### 🗓️ Mês: `{mes_lbl}`")
                if st.button(f"Carregar {mes_lbl}", use_container_width=True):
                    datas_mes = [d["data"] for d in datas_db if d["data"].startswith(mes)]
                    frames=[]; prog=st.progress(0)
                    for i, dt in enumerate(sorted(datas_mes)):
                        t = obter_tickets_db(dt)
                        if t: frames.append(pd.DataFrame(t))
                        prog.progress((i+1)/len(datas_mes))
                    prog.empty()
                    if frames:
                        df_mes = pd.concat(frames, ignore_index=True)
                        out2   = io.BytesIO()
                        with pd.ExcelWriter(out2,engine="openpyxl") as w: montar(df_mes).to_excel(w,index=False)
                        st.download_button(f"📥 {mes_lbl} ({len(df_mes)} entregas)", out2.getvalue(),
                            f"KingStar_{mes}.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary", use_container_width=True)

    # Auto-refresh silencioso
    if is_hoje:
        time.sleep(20)
        st.rerun()
