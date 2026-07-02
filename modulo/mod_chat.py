import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

from database import listar_usuarios, obter_tickets_db
from database_chat import (
    enviar_mensagem_chat, obter_mensagens_chat, marcar_mensagens_lidas,
    listar_conversas_com_nao_lidas, marcar_presenca_adm,
    listar_admins_online, obter_status_conversa, finalizar_conversa_chat,
    reabrir_ou_criar_conversa,
)

# Import isolado: se o mod_rastreio.py tiver qualquer problema, o Chat
# continua funcionando normalmente — só o resumo "Entregas hoje" (com os
# links de rastreio) fica indisponível, em vez de derrubar a tela inteira.
try:
    from modulo.mod_rastreio import extrair_chave, garantir_colunas, TRACKING_BASE
    _RESUMO_ENTREGAS_OK = True
except Exception:
    _RESUMO_ENTREGAS_OK = False
    def extrair_chave(rota): return rota
    def garantir_colunas(df): return df
    TRACKING_BASE = ""

BRT = timezone(timedelta(hours=-3))

# ── Atualização parcial (st.fragment) em vez de recarregar a página inteira ──
# streamlit-autorefresh recarrega TUDO a cada N segundos, o que "briga" com
# qualquer clique feito bem na hora do refresh (parece travar). st.fragment
# é nativo do Streamlit (>=1.33) e atualiza só o pedaço marcado, sem mexer
# no resto da tela — resolve o travamento e fica mais rápido.
_FRAGMENT_DECORATOR = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
_TEM_FRAGMENT = _FRAGMENT_DECORATOR is not None


def _fmt_hora(ts):
    if not ts:
        return ""
    try:
        return ts.astimezone(BRT).strftime("%H:%M")
    except Exception:
        return ""


def _entregas_hoje_df(login_motorista: str) -> pd.DataFrame:
    hoje = datetime.now(BRT).date().isoformat()
    tickets = obter_tickets_db(hoje)
    if not tickets:
        return pd.DataFrame()
    df = pd.DataFrame(tickets)
    df = garantir_colunas(df.copy())
    if "route" not in df.columns:
        return pd.DataFrame()
    return df[df["route"].apply(extrair_chave) == login_motorista]


def _popover_entregas(login_motorista: str, nome_m: str):
    df = _entregas_hoje_df(login_motorista)
    st.markdown(f"**{nome_m}** — {datetime.now(BRT).strftime('%d/%m/%Y')}")
    if df.empty:
        st.caption("Nenhuma entrega atribuída a esse motorista hoje.")
        return

    total  = len(df)
    concl  = int((df["_status_visual"] == "✅ Sucesso").sum())
    falhas = int((df["_status_visual"] == "❌ Falhou").sum())
    pend   = total - concl - falhas
    st.markdown(
        f"📦 Total: **{total}**  \n✅ Concluídas: **{concl}**  \n"
        f"⏳ Pendentes: **{pend}**  \n❌ Falhas: **{falhas}**"
    )

    st.markdown("---")
    st.caption("🔗 Links de rastreio — clique no ícone de copiar em cada um:")
    tem_link = False
    for _, row in df.iterrows():
        tid = str(row.get("tracking_id", "") or "").strip()
        if tid and tid not in ("—", "nan", "None") and TRACKING_BASE:
            tem_link = True
            st.caption(f"#{row.get('order','—')} · {row.get('title','—')}")
            st.code(f"{TRACKING_BASE}{tid}", language=None)
    if not tem_link:
        st.caption("Nenhum link de rastreio disponível ainda hoje para este motorista.")


def _filtrar_msgs_por_periodo(msgs: list, modo: str, dia=None, ano_mes=None) -> list:
    """Filtra as mensagens de uma conversa por dia específico ou mês específico.
    modo == 'Toda a conversa' não filtra nada."""
    if modo == "Toda a conversa":
        return msgs
    filtradas = []
    for m in msgs:
        ts = m.get("timestamp")
        if not ts:
            continue
        try:
            dt_local = ts.astimezone(BRT)
        except Exception:
            continue
        if modo == "Dia específico" and dia:
            if dt_local.date() == dia:
                filtradas.append(m)
        elif modo == "Mês específico" and ano_mes:
            if (dt_local.year, dt_local.month) == ano_mes:
                filtradas.append(m)
    return filtradas


def _gerar_html_transcript(nome_m: str, login_m: str, msgs: list, rotulo_periodo: str = "") -> bytes:
    """Gera um HTML autônomo da conversa (ou de um recorte dela) — abre no
    navegador e pode ser impresso/salvo como PDF via Ctrl+P > Salvar como PDF."""
    linhas = []
    for m in msgs:
        quem = nome_m if m["remetente_tipo"] == "motorista" else m.get("remetente", "ADM")
        hora = _fmt_hora(m.get("timestamp"))
        data_msg = ""
        ts = m.get("timestamp")
        if ts:
            try:
                data_msg = ts.astimezone(BRT).strftime("%d/%m/%Y")
            except Exception:
                pass
        texto = str(m.get("texto", "")).replace("<", "&lt;").replace(">", "&gt;")
        linhas.append(
            f'<div style="margin:8px 0;padding:8px 12px;border-left:3px solid #C9A84C;'
            f'background:#f8f9fa;border-radius:6px;"><b>{quem}</b> '
            f'<span style="color:#888;font-size:0.8rem;">{data_msg} {hora}</span>'
            f'<br>{texto}</div>'
        )
    subtitulo_periodo = f" · Período: {rotulo_periodo}" if rotulo_periodo else ""
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Conversa - {nome_m}</title></head>
<body style="font-family:Arial,sans-serif;max-width:700px;margin:20px auto;color:#2c3e50;">
<h2 style="color:#C9A84C;">KingStar · Conversa com {nome_m}</h2>
<p style="color:#888;">Login: {login_m} · Exportado em {datetime.now(BRT).strftime('%d/%m/%Y %H:%M')}{subtitulo_periodo}</p>
<hr>
{''.join(linhas) if linhas else '<p>Nenhuma mensagem neste período.</p>'}
</body></html>"""
    return html.encode("utf-8")


def _card_conversa(c: dict, info_motoristas: dict, selecionado_atual):
    login_m = c["motorista"]
    info    = info_motoristas.get(login_m, {})
    nome_m  = info.get("nome") or login_m
    nao_lidas = c["nao_lidas"]
    piscando  = nao_lidas > 0
    ctx = "pend" if piscando else "ok"

    label = f"🚚 {nome_m}"
    if piscando:
        label += f" 🔴 {nao_lidas} nova(s)"

    if st.button(label, key=f"cvcard_{ctx}_{login_m}", use_container_width=True):
        st.session_state.chat_motorista_sel = login_m
        st.rerun()


# ── ABA: ATENDIMENTO (conversas em aberto) ─────────────────────────
def _render_atendimento_impl(usuario: str, motoristas: list, info_motoristas: dict):
    # CSS aqui dentro (não no nível do módulo) porque, ao virar st.fragment,
    # esta função pode reexecutar sozinha sem passar pelo restante da página.
    st.markdown("""
    <style>
    @keyframes cvpiscar { 0%,100%{opacity:1;} 50%{opacity:.30;} }
    @keyframes cvbordapiscar {
        0%,100%{box-shadow:0 0 0 0 rgba(138,109,31,0);}
        50%{box-shadow:0 0 0 3px rgba(138,109,31,.35);}
    }
    div[class*="st-key-cvcard_pend_"] button {
        text-align:left !important; justify-content:flex-start !important;
        border:2px solid #8A6D1F !important; background:#FBF3D9 !important;
        color:#6B5A2A !important; font-weight:800 !important;
        animation: cvbordapiscar 1s infinite; border-radius:10px !important;
    }
    div[class*="st-key-cvcard_ok_"] button {
        text-align:left !important; justify-content:flex-start !important;
        background:#fff !important; border:1px solid #e2e8f0 !important;
        border-left:4px solid #C9A84C !important;
        color:#2c3e50 !important; font-weight:600 !important; border-radius:10px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    if not motoristas:
        st.info("Nenhum motorista cadastrado ainda.")
        return

    todas = listar_conversas_com_nao_lidas(motoristas)
    ativas = []
    for c in todas:
        if not c["ultima_hora"]:
            continue  # esse motorista nunca mandou mensagem — não aparece
        if obter_status_conversa(c["motorista"]) == "finalizada":
            continue  # conversa encerrada — só aparece no Histórico
        ativas.append(c)

    ativas.sort(key=lambda c: (c["nao_lidas"] == 0, -(c["ultima_hora"].timestamp())))

    if "chat_motorista_sel" not in st.session_state:
        st.session_state.chat_motorista_sel = ativas[0]["motorista"] if ativas else None

    logins_ativos = [c["motorista"] for c in ativas]
    if st.session_state.chat_motorista_sel not in logins_ativos:
        st.session_state.chat_motorista_sel = logins_ativos[0] if logins_ativos else None

    col_lista, col_chat = st.columns([1, 2])

    with col_lista:
        st.markdown("**Conversas em atendimento**")
        if not ativas:
            st.caption("Nenhuma conversa em aberto no momento. 🎉")
        for c in ativas:
            _card_conversa(c, info_motoristas, st.session_state.chat_motorista_sel)

    motorista_sel = st.session_state.chat_motorista_sel

    with col_chat:
        if not motorista_sel:
            st.info("Nenhuma conversa selecionada.")
            return

        info    = info_motoristas.get(motorista_sel, {})
        nome_m  = info.get("nome") or motorista_sel
        placa_m = info.get("placa") or "—"

        hc1, hc2, hc3 = st.columns([2.2, 1, 1])
        with hc1:
            st.markdown(f"**🚚 {nome_m}** · placa `{placa_m}` · login `{motorista_sel}`")
        with hc2:
            if _RESUMO_ENTREGAS_OK:
                with st.popover("📦 Entregas hoje", use_container_width=True):
                    _popover_entregas(motorista_sel, nome_m)
            else:
                st.caption("Resumo indisponível")
        with hc3:
            if st.button("✅ Finalizar", use_container_width=True, key=f"finalizar_{motorista_sel}"):
                finalizar_conversa_chat(motorista_sel, usuario)
                st.session_state.chat_motorista_sel = None
                st.success(f"Conversa com {nome_m} finalizada!")
                time.sleep(.5)
                st.rerun()

        marcar_mensagens_lidas(motorista_sel, "motorista")
        msgs = obter_mensagens_chat(motorista_sel)
        with st.container(height=380, border=True):
            if not msgs:
                st.caption("Sem mensagens ainda nesta conversa.")
            for m in msgs:
                quem = ("🚚 " + nome_m) if m["remetente_tipo"] == "motorista" else ("🛠️ " + m["remetente"])
                st.markdown(f"**{quem}** · _{_fmt_hora(m.get('timestamp'))}_  \n{m['texto']}")
        txt = st.chat_input(f"Responder para {nome_m}...", key="chat_input_adm")
        if txt:
            enviar_mensagem_chat(motorista_sel, usuario, txt, "adm")
            st.rerun()

    st.markdown("---")
    if _TEM_FRAGMENT:
        st.caption("🔄 Atualização automática ativa (parcial, a cada 2s — não recarrega a página inteira).")
    else:
        st.caption(
            "⚠️ Seu Streamlit é muito antigo para atualização automática parcial. "
            "Atualize `streamlit>=1.35.0` no requirements.txt, ou use o botão abaixo."
        )
        if st.button("🔄 Atualizar agora", key="btn_refresh_adm", use_container_width=True):
            st.rerun()


# Aplica o fragment (atualização parcial a cada 2s) se disponível na sua
# versão do Streamlit; senão, roda normal (só atualiza com interação manual).
if _TEM_FRAGMENT:
    _render_atendimento = _FRAGMENT_DECORATOR(run_every=2)(_render_atendimento_impl)
else:
    _render_atendimento = _render_atendimento_impl


# ── ABA: HISTÓRICO (conversas finalizadas, busca + exportação) ─────
def _render_historico(motoristas: list, info_motoristas: dict):
    st.markdown("**Buscar conversas finalizadas**")
    termo = st.text_input("🔍 Nome ou login do motorista", key="hist_busca",
                          placeholder="Digite para filtrar...")

    finalizadas = []
    for m in motoristas:
        if obter_status_conversa(m) != "finalizada":
            continue
        info = info_motoristas.get(m, {})
        nome_m = info.get("nome") or m
        if termo and termo.lower() not in nome_m.lower() and termo.lower() not in m.lower():
            continue
        finalizadas.append((m, nome_m))

    if not finalizadas:
        st.info("Nenhuma conversa finalizada encontrada.")
        return

    st.caption(f"{len(finalizadas)} conversa(s) finalizada(s).")

    for login_m, nome_m in finalizadas:
        with st.expander(f"🚚 {nome_m} · `{login_m}`"):
            msgs = obter_mensagens_chat(login_m)
            if not msgs:
                st.caption("Sem mensagens.")
                continue

            st.markdown("**📅 Período do download**")
            modo_periodo = st.radio(
                "Período", ["Toda a conversa", "Dia específico", "Mês específico"],
                key=f"periodo_modo_{login_m}", horizontal=True, label_visibility="collapsed",
            )

            dia_sel, ano_mes_sel, rotulo_periodo, sufixo_arquivo = None, None, "", "completa"
            if modo_periodo == "Dia específico":
                dia_sel = st.date_input("Escolha o dia", key=f"periodo_dia_{login_m}")
                rotulo_periodo = dia_sel.strftime("%d/%m/%Y")
                sufixo_arquivo = dia_sel.strftime("%Y%m%d")
            elif modo_periodo == "Mês específico":
                mes_ref = st.date_input(
                    "Escolha qualquer dia dentro do mês desejado", key=f"periodo_mes_{login_m}"
                )
                ano_mes_sel = (mes_ref.year, mes_ref.month)
                rotulo_periodo = mes_ref.strftime("%m/%Y")
                sufixo_arquivo = mes_ref.strftime("%Y%m")

            msgs_filtradas = _filtrar_msgs_por_periodo(msgs, modo_periodo, dia_sel, ano_mes_sel)

            with st.container(height=280, border=True):
                if not msgs_filtradas:
                    st.caption("Nenhuma mensagem no período selecionado.")
                for m in msgs_filtradas:
                    quem = ("🚚 " + nome_m) if m["remetente_tipo"] == "motorista" else ("🛠️ " + m["remetente"])
                    st.markdown(f"**{quem}** · _{_fmt_hora(m.get('timestamp'))}_  \n{m['texto']}")

            if msgs_filtradas:
                html_bytes = _gerar_html_transcript(nome_m, login_m, msgs_filtradas, rotulo_periodo)
                st.download_button(
                    "📄 Baixar este recorte (.html — abra e use Ctrl+P → Salvar como PDF)",
                    data=html_bytes,
                    file_name=f"Conversa_{login_m}_{sufixo_arquivo}.html",
                    mime="text/html",
                    key=f"dl_hist_{login_m}_{modo_periodo}_{sufixo_arquivo}",
                    use_container_width=True,
                )

            if st.button("↩️ Reabrir conversa", key=f"reabrir_{login_m}", use_container_width=True):
                reabrir_ou_criar_conversa(login_m)
                st.success("Conversa reaberta! Vá para a aba Atendimento para continuar.")
                time.sleep(.6)
                st.rerun()


# ── ABA: visão do motorista (falar com o suporte) ──────────────────
def _render_chat_motorista_impl(usuario: str):
    # Sem título, sem aviso de "ADM online/offline" — só a caixa de digitar
    # (no topo) e a conversa, pra caber limpo no celular.

    with st.form("form_msg_motorista", clear_on_submit=True):
        col_txt, col_btn = st.columns([5, 1])
        txt = col_txt.text_input(
            "Mensagem", label_visibility="collapsed",
            placeholder="Digite sua mensagem...", key="chat_input_motorista_txt",
        )
        enviar = col_btn.form_submit_button("Enviar", type="primary", use_container_width=True)
        if enviar:
            if txt.strip():
                enviar_mensagem_chat(usuario, usuario, txt.strip(), "motorista")
                st.rerun()
            else:
                st.warning("Escreva uma mensagem antes de enviar.")

    marcar_mensagens_lidas(usuario, "adm")
    msgs = obter_mensagens_chat(usuario)

    if not _TEM_FRAGMENT:
        if st.button("🔄 Atualizar mensagens", use_container_width=True, key="btn_refresh_motorista"):
            st.rerun()

    with st.container(height=400, border=True):
        if not msgs:
            st.caption("Nenhuma mensagem ainda. Envie sua dúvida acima.")
        # Mais recente primeiro — a última resposta já aparece no topo da
        # caixa, sem precisar rolar nada.
        for m in reversed(msgs):
            quem = "🚚 Você" if m["remetente_tipo"] == "motorista" else f"🛠️ {m['remetente']}"
            st.markdown(f"**{quem}** · _{_fmt_hora(m.get('timestamp'))}_  \n{m['texto']}")


if _TEM_FRAGMENT:
    _render_chat_motorista = _FRAGMENT_DECORATOR(run_every=2)(_render_chat_motorista_impl)
else:
    _render_chat_motorista = _render_chat_motorista_impl


# ── FUNÇÃO PRINCIPAL ────────────────────────────────────────────────
def renderizar_chat(papel, user):
    usuario = user.get("usuario", "")
    nome = user.get("nome", usuario)

    if papel in ("adm", "supervisor"):
        marcar_presenca_adm(usuario, nome)
        st.subheader("💬 Chat com Motoristas")

        motoristas_cad  = [u for u in listar_usuarios() if u.get("role") == "motorista"]
        info_motoristas = {u["usuario"]: u for u in motoristas_cad}
        motoristas      = list(info_motoristas.keys())

        aba_atend, aba_hist = st.tabs(["💬 Atendimento", "📜 Histórico"])
        with aba_atend:
            _render_atendimento(usuario, motoristas, info_motoristas)
        with aba_hist:
            _render_historico(motoristas, info_motoristas)

    else:
        _render_chat_motorista(usuario)
