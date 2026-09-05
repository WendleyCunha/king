import streamlit as st
import pandas as pd
from services import motorista_service as svc


def render(pode_editar: bool):
    st.header("🚛 Motoristas")

    if pode_editar:
        with st.form("form_motorista", clear_on_submit=True):
            col1, col2 = st.columns(2)
            nome = col1.text_input("Nome *")
            placa = col2.text_input("Placa *")
            col3, col4 = st.columns(2)
            login = col3.text_input("Login (para o APP ENTREGAS) *")
            senha = col4.text_input("Senha *", type="password")
            if st.form_submit_button("Cadastrar motorista"):
                if nome and placa and login and senha:
                    try:
                        svc.cadastrar_motorista(nome=nome, placa=placa, login=login, senha=senha)
                        st.success("Motorista cadastrado.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                else:
                    st.error("Preencha todos os campos.")

    st.subheader("Entregas por motorista")
    st.caption("Esta é a mesma informação disponibilizada ao APP ENTREGAS — cada motorista só vê as próprias entregas.")
    dados = svc.entregas_por_motorista()
    if dados:
        df = pd.DataFrame([{
            "Motorista": d["motorista"]["nome"], "Placa": d["motorista"].get("placa"),
            "Entregas": d["total_entregas"],
        } for d in dados])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum motorista cadastrado ainda.")
