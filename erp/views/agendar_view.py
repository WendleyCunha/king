import streamlit as st
import pandas as pd
import datetime
from erp.services import agendamento_service as svc
from erp.services import notificacao_service as notif


def render(pode_editar: bool):
    st.header("📅 Agendar Entrega")

    notificacoes = notif.listar_notificacoes("AGENDAR")
    if notificacoes:
        with st.expander(f"🔔 {len(notificacoes)} notificação(ões)", expanded=True):
            for n in notificacoes:
                st.write(f"- {n['mensagem']}")
                if st.button("Marcar como lida", key=f"lida_{n['id']}"):
                    notif.marcar_como_lida(n["id"])
                    st.rerun()

    liberados = svc.listar_pedidos_liberados_para_agendar()
    if pode_editar and liberados:
        st.subheader("Pedidos liberados aguardando agendamento")
        opcoes = {f"{p['numero']} - {p['cliente_nome']} ({p['produto_nome']})": p["numero"] for p in liberados}
        escolha = st.selectbox("Pedido", list(opcoes.keys()))
        data = st.date_input("Data de entrega", min_value=datetime.date.today())
        if st.button("Agendar entrega"):
            try:
                svc.agendar_entrega(opcoes[escolha], datetime.datetime.combine(data, datetime.time(9, 0)))
                st.success(f"Pedido {opcoes[escolha]} agendado para {data.strftime('%d/%m/%Y')}. Enviado para a ABA LOGISTICA.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    elif not liberados:
        st.info("Nenhum pedido LIBERADO aguardando agendamento no momento.")

    bloqueados = svc.listar_pedidos_bloqueados()
    if bloqueados:
        st.subheader("🔒 Pedidos BLOQUEADOS (sem estoque — não podem ser agendados ainda)")
        df = pd.DataFrame([{
            "Pedido": p["numero"], "Cliente": p["cliente_nome"],
            "Produto": p["produto_nome"], "Criado em": p["criado_em"],
        } for p in bloqueados])
        st.dataframe(df, use_container_width=True, hide_index=True)
