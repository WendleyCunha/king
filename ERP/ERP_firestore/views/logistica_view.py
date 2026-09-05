import streamlit as st
import pandas as pd
import datetime
from services import logistica_service as svc
from services import motorista_service, fiscal_service
from db import get_db


def render(pode_editar: bool):
    st.header("🚚 Logística")

    aba1, aba2 = st.tabs(["Montar carga", "Cargas em andamento / faturamento"])

    with aba1:
        st.subheader("Pedidos agendados")
        data_filtro = st.date_input("Filtrar por data de entrega", value=None)
        pedidos = svc.listar_pedidos_agendados(data_filtro if data_filtro else None)
        if pedidos:
            df = pd.DataFrame([{
                "Pedido": p["numero"], "Cliente": p["cliente_nome"], "Produto": p["produto_nome"],
                "Data de entrega": datetime.datetime.fromisoformat(p["data_agendamento"]).strftime("%d/%m/%Y"),
            } for p in pedidos])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum pedido agendado (sem carga) para esse filtro.")

        if pode_editar:
            st.subheader("Carga")
            cargas_abertas = svc.listar_cargas("MONTAGEM")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("➕ Criar nova carga"):
                    svc.criar_carga()
                    st.success("Carga criada.")
                    st.rerun()
            with col2:
                opcoes_carga = {f"Carga #{c['id'][:6]}": c["id"] for c in cargas_abertas}
                if opcoes_carga and pedidos:
                    carga_escolhida = st.selectbox("Adicionar pedido à carga", list(opcoes_carga.keys()))
                    opcoes_pedido = {p["numero"]: p["numero"] for p in pedidos}
                    pedido_escolhido = st.selectbox("Pedido", list(opcoes_pedido.keys()))
                    if st.button("Adicionar à carga"):
                        try:
                            svc.adicionar_pedido_carga(opcoes_carga[carga_escolhida], opcoes_pedido[pedido_escolhido])
                            st.success("Pedido adicionado à carga.")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

    with aba2:
        cargas = svc.listar_cargas()
        if not cargas:
            st.info("Nenhuma carga criada ainda.")
            return
        opcoes = {
            f"Carga #{c['id'][:6]} [{c['status']}]" + (f" - {c['motorista_login']}" if c.get("motorista_login") else ""): c["id"]
            for c in cargas
        }
        escolha = st.selectbox("Selecione a carga", list(opcoes.keys()))
        carga = svc.obter_carga(opcoes[escolha])

        st.write(f"**Status:** {carga['status']}")
        numeros = carga.get("pedidos", [])
        if numeros:
            pedidos_carga = [get_db().collection("pedidos").document(n).get().to_dict() for n in numeros]
            df = pd.DataFrame([{
                "Pedido": p["numero"], "Cliente": p["cliente_nome"], "Status": p["status"],
                "Nota fiscal": p.get("nota_fiscal_numero") or "-",
            } for p in pedidos_carga])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Carga sem pedidos.")

        if pode_editar and carga["status"] == "MONTAGEM":
            st.subheader("Ações (carga ainda em montagem)")
            if numeros:
                pedido_remover = st.selectbox("Retirar pedido da carga", numeros)
                if st.button("Retirar da carga"):
                    try:
                        svc.retirar_pedido_carga(pedido_remover)
                        st.success("Pedido retirado. DIRETORIA, RH e AGENDAR foram notificados.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

            st.markdown("---")
            motoristas = motorista_service.listar_motoristas()
            if motoristas:
                opcoes_mot = {f"{m['nome']} ({m.get('placa','')})": m["usuario"] for m in motoristas}
                motorista_escolhido = st.selectbox("Atribuir motorista/caminhão", list(opcoes_mot.keys()))
                st.warning(
                    "⚠️ Depois de atribuir o motorista, a carga é travada: não será mais "
                    "possível eliminar pedidos, alterar agendamento ou mexer nesta carga."
                )
                if st.button("Finalizar carga com este motorista"):
                    try:
                        svc.atribuir_motorista(carga["id"], opcoes_mot[motorista_escolhido])
                        st.success("Carga finalizada e travada.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
            else:
                st.info("Cadastre motoristas na ABA MOTORISTA antes de finalizar a carga.")

        if pode_editar and carga["status"] == "FINALIZADA":
            st.subheader("Faturamento")
            if st.button("💵 Faturar pedidos desta carga"):
                try:
                    notas = fiscal_service.faturar_carga(carga["id"])
                    st.success(f"{len(notas)} nota(s) fiscal(is) gerada(s): " + ", ".join(n["numero"] for n in notas))
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
