import streamlit as st
from erp.services import empresa_service as svc


def render(pode_editar: bool):
    st.header("🏢 Dados da Empresa")
    st.caption("Estes dados aparecem na emissão da nota fiscal ao faturar um pedido na ABA LOGISTICA.")

    empresa = svc.obter_dados_empresa() or {}

    if pode_editar:
        with st.form("form_empresa"):
            razao_social = st.text_input("Razão social *", value=empresa.get("razao_social", ""))
            nome_fantasia = st.text_input("Nome fantasia", value=empresa.get("nome_fantasia", ""))
            col1, col2 = st.columns(2)
            cnpj = col1.text_input("CNPJ *", value=empresa.get("cnpj", ""))
            ie = col2.text_input("Inscrição estadual", value=empresa.get("inscricao_estadual", ""))
            endereco = st.text_input("Endereço", value=empresa.get("endereco", ""))
            col3, col4, col5 = st.columns(3)
            cidade = col3.text_input("Cidade", value=empresa.get("cidade", ""))
            estado = col4.text_input("UF", max_chars=2, value=empresa.get("estado", ""))
            cep = col5.text_input("CEP", value=empresa.get("cep", ""))
            col6, col7 = st.columns(2)
            telefone = col6.text_input("Telefone", value=empresa.get("telefone", ""))
            email = col7.text_input("E-mail", value=empresa.get("email", ""))
            if st.form_submit_button("Salvar"):
                svc.salvar_dados_empresa(
                    razao_social=razao_social, nome_fantasia=nome_fantasia, cnpj=cnpj,
                    inscricao_estadual=ie, endereco=endereco, cidade=cidade, estado=estado,
                    cep=cep, telefone=telefone, email=email,
                )
                st.success("Dados da empresa salvos.")
                st.rerun()
    elif empresa:
        st.write(f"**{empresa.get('razao_social')}** — CNPJ {empresa.get('cnpj')}")
        st.write(f"{empresa.get('endereco')}, {empresa.get('cidade')}/{empresa.get('estado')}")
    else:
        st.info("Dados da empresa ainda não cadastrados.")
