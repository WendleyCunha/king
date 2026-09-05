import streamlit as st
import pandas as pd
from services import cliente_service as svc


def render(pode_editar: bool):
    st.header("📇 Cadastro de Clientes")

    if pode_editar:
        with st.form("form_cliente", clear_on_submit=True):
            col1, col2 = st.columns(2)
            nome = col1.text_input("Nome *")
            cpf_cnpj = col2.text_input("CPF/CNPJ *")
            col3, col4 = st.columns(2)
            telefone = col3.text_input("Telefone")
            email = col4.text_input("E-mail")
            endereco = st.text_input("Endereço")
            col5, col6, col7, col8 = st.columns(4)
            numero = col5.text_input("Número")
            bairro = col6.text_input("Bairro")
            cidade = col7.text_input("Cidade")
            estado = col8.text_input("UF", max_chars=2)
            cep = st.text_input("CEP")
            observacoes = st.text_area("Observações")
            if st.form_submit_button("Cadastrar cliente"):
                try:
                    svc.cadastrar_cliente(
                        nome=nome, cpf_cnpj=cpf_cnpj, telefone=telefone, email=email,
                        endereco=endereco, numero=numero, bairro=bairro, cidade=cidade,
                        estado=estado, cep=cep, observacoes=observacoes,
                    )
                    st.success("Cliente cadastrado com sucesso.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    st.subheader("Clientes cadastrados")
    clientes = svc.listar_clientes()
    if clientes:
        df = pd.DataFrame([{
            "Nome": c["nome"], "CPF/CNPJ": c["cpf_cnpj"], "Telefone": c.get("telefone"),
            "Cidade": c.get("cidade"), "UF": c.get("estado"),
        } for c in clientes])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum cliente cadastrado ainda.")
