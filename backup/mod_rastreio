import sys, os, io, time
from datetime import datetime, timezone, timedelta
import pandas as pd
import streamlit as st

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database import (obter_vinculo_db, salvar_vinculo_db, deletar_rota_db,
                      pode_editar, pode_deletar, pode_exportar)

BRT           = timezone(timedelta(hours=-3))
TRACKING_BASE = "https://livetracking.simpliroute.com/widget/account/88033/tracking/"

def get_series(df, col, default=""):
    if col in df.columns: return df[col]
    return pd.Series([default] * len(df))

def formatar_data(v):
    if not v or str(v).strip() in ("","None","null"): return "—"
    try: return datetime.fromisoformat(str(v).strip().replace("+00:00","").replace("Z","")).strftime("%d/%m %H:%M")
    except: return str(v)[:16]

def extrair_chave(rota):
    if not rota: return "SEM_ROTA"
    return rota.split(" - ",1)[1].strip() if " - " in rota else rota.strip()

def nome_motorista(rota): return obter_vinculo_db(extrair_chave(rota))

def garantir_colunas(df):
    if "_notificado" not in df.columns:
        df["_notificado"] = get_series(df,"on_its_way").apply(
            lambda x: bool(x and str(x).strip().lower() not in ("","none","null","false")))
    else:
        df["_notificado"] = df["_notificado"].apply(
            lambda x: x if isinstance(x,bool) else str(x).lower() not in ("false","0","none","null",""))
    df["_status_visual"] = df.get("_status_visual", pd.Series(["⏳ Pendente"]*len(df))).fillna("⏳ Pendente") \
        if "_status_visual" in df.columns else pd.Series(["⏳ Pendente"]*len(df))
    for col, default in {
        "title":"—","address":"—","route":"Rota não identificada",
        "contact_name":"—","contact_phone":"—","contact_email":"—",
        "tracking_id":"—","on_its_way":None,"checkout_time":None,"checkin_time":None,
        "estimated_time_arrival":"—","checkout_observation":"—","checkout_comment":"—",
        "notes":"—","planned_date":"—","order":"—",
    }.items():
        if col not in df.columns: df[col] = default
    return df

# ─────────────────────────────────────────────
def renderizar_rastreio(df: pd.DataFrame, data_consulta: str, papel: str, user: dict = None):
    if user is None: user = {"role": papel}

    if df.empty:
        st.info("⏳ Nenhum dado de entrega para o dia selecionado.")
        return

    df = garantir_colunas(df.copy())

    abas_nomes = ["🏠 Dashboard", "🧑‍✈️ Visão por Motorista"]
    abas       = st.tabs(abas_nomes)

    # ══ ABA 1 — DASHBOARD ════════════════════════════════════════
    with abas[0]:
        total      = len(df)
        notif      = int(df["_notificado"].sum())
        sucesso    = int((df["_status_visual"]=="✅ Sucesso").sum())
        falhou     = int((df["_status_visual"]=="❌ Falhou").sum())
        em_rota    = int((df["_status_visual"]=="🚚 Em rota").sum())
        pendentes  = total - sucesso - falhou - em_rota

        k1,k2,k3,k4,k5 = st.columns(5)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-label">📦 Total</div><div class="kpi-value">{total}</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-label">📱 Notificados</div><div class="kpi-value" style="color:#2ecc71;">{notif}</div><div class="kpi-sub">{round(notif/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-label">✅ Sucessos</div><div class="kpi-value" style="color:#3498db;">{sucesso}</div><div class="kpi-sub">{round(sucesso/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-label">❌ Falhas</div><div class="kpi-value" style="color:#e74c3c;">{falhou}</div><div class="kpi-sub">{round(falhou/total*100,1) if total>0 else 0}%</div></div>', unsafe_allow_html=True)
        k5.markdown(f'<div class="kpi-card"><div class="kpi-label">⏳ Pendentes</div><div class="kpi-value">{pendentes}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Cards de motorista com popover
        rotas = sorted(df["route"].unique()) if "route" in df.columns else []
        if rotas:
            st.markdown("### 🧑‍✈️ Motoristas em Operação")
            cols = st.columns(min(len(rotas), 4))
            for idx, rota in enumerate(rotas):
                df_r    = df[df["route"]==rota]
                nome    = nome_motorista(rota)
                tot_r   = len(df_r)
                ok_r    = int((df_r["_status_visual"]=="✅ Sucesso").sum())
                fail_r  = int((df_r["_status_visual"]=="❌ Falhou").sum())
                notif_r = int(df_r["_notificado"].sum())
                pct_n   = round(notif_r/tot_r*100,1) if tot_r>0 else 0
                with cols[idx%4]:
                    st.markdown(f"""
                    <div style="background:#fff;border:1px solid #dbe2e9;border-radius:12px;
                                padding:14px;margin-bottom:4px;border-top:4px solid #C9A84C;">
                        <div style="font-size:1rem;font-weight:700;color:#2c3e50;">🧑‍✈️ {nome}</div>
                        <div style="font-size:0.75rem;color:#7f8c8d;margin-bottom:8px;">{rota}</div>
                        <div style="display:flex;flex-wrap:wrap;gap:3px;">
                            <span style="background:rgba(46,204,113,.12);color:#27ae60;padding:3px 8px;border-radius:12px;font-size:0.75rem;font-weight:700;">📱 {notif_r} ({pct_n}%)</span>
                            <span style="background:rgba(201,168,76,.15);color:#b0913b;padding:3px 8px;border-radius:12px;font-size:0.75rem;font-weight:700;">📦 {tot_r}</span>
                            <span style="background:rgba(52,152,219,.12);color:#2980b9;padding:3px 8px;border-radius:12px;font-size:0.75rem;font-weight:700;">✅ {ok_r}</span>
                            <span style="background:rgba(231,76,60,.12);color:#c0392b;padding:3px 8px;border-radius:12px;font-size:0.75rem;font-weight:700;">❌ {fail_r}</span>
                        </div>
                    </div>""", unsafe_allow_html=True)

                    with st.popover(f"📋 Ver {notif_r} notificado(s)", use_container_width=True):
                        df_notif = df_r[df_r["_notificado"]==True].copy()
                        if df_notif.empty:
                            st.info("Nenhum cliente notificado ainda.")
                        else:
                            st.markdown(f"**{nome}** — {len(df_notif)} notificado(s)")
                            st.markdown("---")
                            for _, row in df_notif.iterrows():
                                tid   = str(row.get("tracking_id","") or "").strip()
                                url   = f"{TRACKING_BASE}{tid}" if tid not in ("","—","nan","None") else ""
                                st.markdown(
                                    f"**#{row.get('order','—')} · {row.get('title','—')}**  \n"
                                    f"<span style='font-size:0.8rem;color:#64778d;'>📍 {row.get('address','—')}</span>  \n"
                                    f"<span style='font-size:0.8rem;color:#64778d;'>Notif.: {formatar_data(row.get('on_its_way'))} · {row.get('_status_visual','')}</span>",
                                    unsafe_allow_html=True)
                                if url:
                                    cl, cc = st.columns([3,1])
                                    with cl:
                                        st.markdown(f'<a href="{url}" target="_blank" style="font-size:0.8rem;color:#2980b9;">🔗 {url}</a>', unsafe_allow_html=True)
                                    with cc:
                                        if st.button("📋", key=f"cp_{rota}_{tid}"):
                                            st.components.v1.html(f"<script>navigator.clipboard.writeText('{url}');</script>", height=0)
                                            st.toast("Link copiado!", icon="✅")
                                else:
                                    st.caption("⚠️ Sem tracking ID")
                                st.markdown("<hr style='margin:6px 0;border:none;border-top:1px solid #eee;'>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({
            "Ordem":    get_series(df,"order"),
            "Motorista":get_series(df,"route").apply(nome_motorista),
            "Cliente":  get_series(df,"title"),
            "Status":   df["_status_visual"],
            "Notif.?":  df["_notificado"].apply(lambda x:"Sim" if x else "Não"),
            "Notif. em":get_series(df,"on_its_way").apply(formatar_data),
            "Check-out":get_series(df,"checkout_time").apply(formatar_data),
        }), use_container_width=True, hide_index=True)

    # ══ ABA 2 — VISÃO POR MOTORISTA ══════════════════════════════
    with abas[1]:
        rotas = sorted(df["route"].unique()) if "route" in df.columns else []
        if not rotas:
            st.info("Nenhuma rota registrada.")
            return

        opcoes, mapa = [], {}
        for r in rotas:
            n   = int(df[df["route"]==r]["_notificado"].sum())
            lbl = f"📍 {nome_motorista(r)} (📱 {n} Notif.)"
            opcoes.append(lbl); mapa[lbl] = r

        col_m, col_d = st.columns([1.5, 3])

        with col_m:
            lbl_sel   = st.radio("Rotas do Dia", options=opcoes, label_visibility="collapsed")
            mot_ativo = mapa[lbl_sel]

            # Edição de nome — só supervisor/adm
            if pode_editar(user):
                st.markdown("---")
                novo_nome = st.text_input("Nome do condutor:", value=nome_motorista(mot_ativo), key=f"nome_{mot_ativo}")
                if st.button("💾 Salvar nome", use_container_width=True, key=f"save_{mot_ativo}", type="primary"):
                    salvar_vinculo_db(extrair_chave(mot_ativo), novo_nome.strip())
                    st.success("Salvo!")
                    time.sleep(0.5); st.rerun()
            else:
                st.markdown("---")
                st.caption(f"Condutor: **{nome_motorista(mot_ativo)}**")
                st.caption("🔒 Edição restrita a supervisores.")

            # Exclusão — só adm
            if pode_deletar(user):
                st.markdown("---")
                st.error("🚨 Zona de Perigo")
                if st.checkbox("Liberar exclusão", key=f"chk_{mot_ativo}"):
                    if st.button("🗑️ Excluir Rota", use_container_width=True, key=f"del_{mot_ativo}"):
                        deletar_rota_db(mot_ativo, data_consulta)
                        st.success("Dados excluídos!")
                        time.sleep(1); st.rerun()

        with col_d:
            df_rota = df[df["route"]==mot_ativo].copy()
            t_m  = len(df_rota)
            n_m  = int(df_rota["_notificado"].sum())
            ok_m = int((df_rota["_status_visual"]=="✅ Sucesso").sum())
            f_m  = int((df_rota["_status_visual"]=="❌ Falhou").sum())
            p_m  = t_m - ok_m - f_m

            st.markdown(f"""
            <div style="background:#fff;border-left:6px solid #C9A84C;border-radius:10px;
                        padding:14px;margin-bottom:12px;border:1px solid #dbe2e9;">
                <h3 style="margin:0;color:#2c3e50;">🧑‍✈️ {nome_motorista(mot_ativo)}</h3>
                <p style="color:#64778d;font-size:0.85rem;margin:4px 0 10px;">{mot_ativo}</p>
                <span style="background:rgba(201,168,76,.15);color:#b0913b;padding:4px 10px;border-radius:12px;font-size:0.8rem;font-weight:700;margin-right:4px;">📦 Total: {t_m}</span>
                <span style="background:rgba(46,204,113,.12);color:#27ae60;padding:4px 10px;border-radius:12px;font-size:0.8rem;font-weight:700;margin-right:4px;">📱 Notif.: {n_m}</span>
                <span style="background:rgba(52,152,219,.12);color:#2980b9;padding:4px 10px;border-radius:12px;font-size:0.8rem;font-weight:700;margin-right:4px;">✅ {ok_m}</span>
                <span style="background:rgba(231,76,60,.12);color:#c0392b;padding:4px 10px;border-radius:12px;font-size:0.8rem;font-weight:700;">❌ {f_m}</span>
            </div>""", unsafe_allow_html=True)

            t_fila, t_falhas = st.tabs(["📋 Fila de Clientes","⚠️ Ocorrências"])
            with t_fila:
                st.dataframe(pd.DataFrame({
                    "Ordem":    get_series(df_rota,"order"),
                    "Cliente":  get_series(df_rota,"title"),
                    "Endereço": get_series(df_rota,"address"),
                    "Status":   df_rota["_status_visual"],
                    "Notif.?":  df_rota["_notificado"].apply(lambda x:"Sim" if x else "Não"),
                    "Notif. em":get_series(df_rota,"on_its_way").apply(formatar_data),
                    "Check-in": get_series(df_rota,"checkin_time").apply(formatar_data),
                    "Check-out":get_series(df_rota,"checkout_time").apply(formatar_data),
                    "ETA":      get_series(df_rota,"estimated_time_arrival"),
                    "Observação":get_series(df_rota,"checkout_observation"),
                    "Telefone": get_series(df_rota,"contact_phone"),
                    "Tracking": get_series(df_rota,"tracking_id"),
                }), use_container_width=True, hide_index=True)
            with t_falhas:
                df_err = df_rota[df_rota["_status_visual"]=="❌ Falhou"]
                if df_err.empty: st.success("Nenhuma devolução registrada.")
                else:
                    st.dataframe(pd.DataFrame({
                        "Ordem":  get_series(df_err,"order"),
                        "Cliente":get_series(df_err,"title"),
                        "Motivo": get_series(df_err,"checkout_observation"),
                        "Detalhe":get_series(df_err,"checkout_comment","—"),
                        "Horário":get_series(df_err,"checkout_time").apply(formatar_data),
                    }), use_container_width=True, hide_index=True)


def renderizar_exportar(df: pd.DataFrame, data_consulta: str, datas_db: list):
    """Aba de exportação separada — só aparece para quem tem permissão."""
    st.markdown("### 💾 Exportação de Dados")
    if df.empty:
        st.warning("Nenhum dado para exportar nesta data.")
        return

    def montar_excel(df_src):
        return pd.DataFrame({
            "Ordem":      get_series(df_src,"order"),
            "Motorista":  get_series(df_src,"route").apply(nome_motorista),
            "Cliente":    get_series(df_src,"title"),
            "Endereço":   get_series(df_src,"address"),
            "Status":     get_series(df_src,"_status_visual","⏳ Pendente"),
            "Notificado": get_series(df_src,"_notificado").apply(lambda x:"Sim" if x else "Não"),
            "Notif. em (BRT)":  get_series(df_src,"on_its_way").apply(formatar_data),
            "Check-in (BRT)":   get_series(df_src,"checkin_time").apply(formatar_data),
            "Check-out (BRT)":  get_series(df_src,"checkout_time").apply(formatar_data),
            "ETA":        get_series(df_src,"estimated_time_arrival"),
            "Observação": get_series(df_src,"checkout_observation"),
            "Tracking ID":get_series(df_src,"tracking_id"),
        })

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"#### 📅 Dia: `{data_consulta}`")
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as w: montar_excel(df).to_excel(w, index=False)
        st.download_button(f"📥 Baixar {data_consulta}", out.getvalue(),
            f"KingStar_{data_consulta}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary", use_container_width=True)

    with c2:
        mes     = datetime.strptime(data_consulta,"%Y-%m-%d").strftime("%Y-%m")
        mes_lbl = datetime.strptime(data_consulta,"%Y-%m-%d").strftime("%B/%Y")
        st.markdown(f"#### 🗓️ Mês: `{mes_lbl}`")
        if st.button(f"🔄 Carregar {mes_lbl}", use_container_width=True):
            from database import obter_tickets_db
            datas_mes = [d["data"] for d in datas_db if d["data"].startswith(mes)]
            frames = []
            prog = st.progress(0)
            for i, dt in enumerate(sorted(datas_mes)):
                t = obter_tickets_db(dt)
                if t: frames.append(pd.DataFrame(t))
                prog.progress((i+1)/len(datas_mes))
            prog.empty()
            if frames:
                df_mes = pd.concat(frames, ignore_index=True)
                out2   = io.BytesIO()
                with pd.ExcelWriter(out2, engine="openpyxl") as w: montar_excel(df_mes).to_excel(w, index=False)
                st.download_button(f"📥 Baixar {mes_lbl} ({len(df_mes)} entregas)", out2.getvalue(),
                    f"KingStar_{mes}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary", use_container_width=True)
