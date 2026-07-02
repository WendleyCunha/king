import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone

from database import listar_usuarios, obter_tickets_db
from database_chat import (
    enviar_mensagem_chat, obter_mensagens_chat, marcar_mensagens_lidas,
    listar_conversas_com_nao_lidas, marcar_presenca_adm,
    listar_admins_online,
)

# Import isolado: se o mod_rastreio.py tiver qualquer problema, o Chat
# continua funcionando normalmente — só o resumo "Entregas hoje" fica
# indisponível, em vez de derrubar a tela inteira.
try:
    from modulo.mod_rastreio import extrair_chave, garantir_colunas
    _RESUMO_ENTREGAS_OK = True
except Exception:
    _RESUMO_ENTREGAS_OK = False
    def extrair_chave(rota): return rota
    def garantir_colunas(df): return df

BRT = timezone(timedelta(hours=-3))


def _fmt_hora(ts):
    if not ts:
        return ""
    try:
        return ts.astimezone(BRT).strftime("%H:%M")
    except Exception:
        return ""


def _resumo_entregas_hoje(login_motorista: str):
    """Retorna (total, concluidas, pendentes, falhas) das entregas de HOJE desse motorista."""
    hoje = datetime.now(BRT).date().isoformat()
    tickets = obter_tickets_db(hoje)
    if not tickets:
        return 0, 0, 0, 0
    df = pd.DataFrame(tickets)
    df = garantir_colunas(df.copy())
    if "route" not in df.columns:
        return 0, 0, 0, 0
    df = df[df["route"].apply(extrair_chave) == login_motorista]
    total  = len(df)
    concl  = int((df["_status_visual"] == "✅ Sucesso").sum()) if "_status_visual" in df.columns else 0
    falhas = int((df["_status_visual"] == "❌ Falhou").sum()) if "_status_visual" in df.columns else 0
    pend   = total - concl - falhas
    return total, concl, pend, falhas


def renderizar_chat(papel, user):
    usuario = user.get("usuario", "")
    nome = user.get("nome", usuario)

    if papel in ("adm", "supervisor"):
        marcar_presenca_adm(usuario, nome)
        st.subheader("💬 Chat com Motoristas")

        motoristas_cad  = [u for u in listar_usuarios() if u.get("role") == "motorista"]
        info_motoristas = {u["usuario"]: u for u in motoristas_cad}
        motoristas      = list(info_motoristas.keys())
        if not motoristas:
            st.info("Nenhum motorista cadastrado ainda.")
            return

        conversas = listar_conversas_com_nao_lidas(motoristas)
        # não lidas primeiro, depois mais recentes
        conversas.sort(
            key=lambda c: (c["nao_lidas"] == 0, -(c["ultima_hora"].timestamp() if c["ultima_hora"] else 0))
        )

        col_lista, col_chat = st.columns([1, 2])

        with col_lista:
            st.markdown("**Conversas**")
            labels, mapa = [], {}
            for c in conversas:
                login_m = c["motorista"]
                info    = info_motoristas.get(login_m, {})
                nome_m  = info.get("nome") or login_m
                badge   = f" 🔴 {c['nao_lidas']}" if c["nao_lidas"] else ""
                label   = f"{nome_m}{badge}"
                labels.append(label)
                mapa[label] = login_m
            escolha = st.radio("Motorista", labels, label_visibility="collapsed", key="chat_lista_motoristas")
            motorista_sel = mapa.get(escolha)

        with col_chat:
            if motorista_sel:
                info    = info_motoristas.get(motorista_sel, {})
                nome_m  = info.get("nome") or motorista_sel
                placa_m = info.get("placa") or "—"

                hc1, hc2 = st.columns([3, 1])
                with hc1:
                    st.markdown(f"**🚚 {nome_m}** · placa `{placa_m}` · login `{motorista_sel}`")
                with hc2:
                    if _RESUMO_ENTREGAS_OK:
                        with st.popover("📦 Entregas hoje", use_container_width=True):
                            total, concl, pend, falhas = _resumo_entregas_hoje(motorista_sel)
                            st.markdown(f"**{nome_m}** — {datetime.now(BRT).strftime('%d/%m/%Y')}")
                            if total == 0:
                                st.caption("Nenhuma entrega atribuída a esse motorista hoje.")
                            else:
                                st.markdown(
                                    f"📦 Total: **{total}**  \n"
                                    f"✅ Concluídas: **{concl}**  \n"
                                    f"⏳ Pendentes: **{pend}**  \n"
                                    f"❌ Falhas: **{falhas}**"
                                )
                    else:
                        st.caption("Resumo indisponível")

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

    else:
        # visão do motorista
        st.subheader("💬 Falar com o Suporte")
        online = listar_admins_online()
        if online:
            st.success("🟢 Online agora: " + ", ".join(a["nome"] for a in online))
        else:
            st.warning("🟡 Nenhum ADM online no momento — sua mensagem será respondida assim que possível.")

        marcar_mensagens_lidas(usuario, "adm")
        msgs = obter_mensagens_chat(usuario)
        with st.container(height=420, border=True):
            if not msgs:
                st.caption("Nenhuma mensagem ainda. Envie sua dúvida abaixo.")
            for m in msgs:
                quem = "🚚 Você" if m["remetente_tipo"] == "motorista" else f"🛠️ {m['remetente']}"
                st.markdown(f"**{quem}** · _{_fmt_hora(m.get('timestamp'))}_  \n{m['texto']}")

        txt = st.chat_input("Digite sua mensagem...", key="chat_input_motorista")
        if txt:
            enviar_mensagem_chat(usuario, usuario, txt, "motorista")
            st.rerun()

    # Polling leve — mesmo padrão que você já usa no módulo de rastreio
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=4000, key="chat_auto_refresh")
    except Exception:
        pass
