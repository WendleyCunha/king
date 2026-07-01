import streamlit as st
from datetime import datetime, timedelta, timezone

from database import listar_usuarios
from database_chat import (
    enviar_mensagem_chat, obter_mensagens_chat, marcar_mensagens_lidas,
    listar_conversas_com_nao_lidas, marcar_presenca_adm,
    listar_admins_online,
)

BRT = timezone(timedelta(hours=-3))


def _fmt_hora(ts):
    if not ts:
        return ""
    try:
        return ts.astimezone(BRT).strftime("%H:%M")
    except Exception:
        return ""


def renderizar_chat(papel, user):
    usuario = user.get("usuario", "")
    nome = user.get("nome", usuario)

    if papel in ("adm", "supervisor"):
        marcar_presenca_adm(usuario, nome)
        st.subheader("💬 Chat com Motoristas")

        motoristas = [u["usuario"] for u in listar_usuarios() if u.get("role") == "motorista"]
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
                badge = f" 🔴 {c['nao_lidas']}" if c["nao_lidas"] else ""
                label = f"{c['motorista']}{badge}"
                labels.append(label)
                mapa[label] = c["motorista"]
            escolha = st.radio("Motorista", labels, label_visibility="collapsed", key="chat_lista_motoristas")
            motorista_sel = mapa.get(escolha)

        with col_chat:
            if motorista_sel:
                marcar_mensagens_lidas(motorista_sel, "motorista")
                msgs = obter_mensagens_chat(motorista_sel)
                with st.container(height=380, border=True):
                    if not msgs:
                        st.caption("Sem mensagens ainda nesta conversa.")
                    for m in msgs:
                        quem = "🚚 " + m["remetente"] if m["remetente_tipo"] == "motorista" else "🛠️ " + m["remetente"]
                        st.markdown(f"**{quem}** · _{_fmt_hora(m.get('timestamp'))}_  \n{m['texto']}")
                txt = st.chat_input(f"Responder para {motorista_sel}...", key="chat_input_adm")
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
