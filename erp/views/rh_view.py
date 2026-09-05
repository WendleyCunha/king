import streamlit as st
import pandas as pd
import datetime
from erp.services import rh_service as svc


def render(pode_editar: bool):
    st.header("👥 RH")

    aba1, aba2, aba3 = st.tabs(["Cargos", "Funcionários", "Comissão em tempo real"])

    with aba1:
        if pode_editar:
            with st.form("form_cargo", clear_on_submit=True):
                nome = st.text_input("Nome do cargo *")
                is_vendedor = st.checkbox("Este cargo gera código de vendedor (recebe comissão)")
                descricao = st.text_area("Descrição")
                if st.form_submit_button("Cadastrar cargo"):
                    try:
                        svc.cadastrar_cargo(nome=nome, is_vendedor=is_vendedor, descricao=descricao)
                        st.success("Cargo cadastrado.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        cargos = svc.listar_cargos()
        if cargos:
            st.dataframe(pd.DataFrame([{
                "Cargo": c["nome"], "Gera código de vendedor?": "Sim" if c.get("is_vendedor") else "Não",
            } for c in cargos]), use_container_width=True, hide_index=True)

    with aba2:
        if pode_editar:
            cargos = svc.listar_cargos()
            if not cargos:
                st.info("Cadastre um cargo primeiro.")
            else:
                with st.form("form_funcionario", clear_on_submit=True):
                    nome = st.text_input("Nome *")
                    cpf = st.text_input("CPF *")
                    cargo_escolhido = st.selectbox("Cargo *", [c["nome"] for c in cargos])
                    salario = st.number_input("Salário (R$) *", min_value=0.0, step=100.0)
                    data_admissao = st.date_input("Data de admissão", value=datetime.date.today())
                    if st.form_submit_button("Cadastrar funcionário"):
                        try:
                            func = svc.cadastrar_funcionario(
                                nome=nome, cpf=cpf, cargo_nome=cargo_escolhido, salario=salario,
                                data_admissao=datetime.datetime.combine(data_admissao, datetime.time()).isoformat(),
                            )
                            msg = f"Funcionário {func['nome']} cadastrado."
                            if func.get("vendedor_codigo"):
                                msg += f" Código de vendedor gerado: {func['vendedor_codigo']}"
                            st.success(msg)
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

        funcionarios = svc.listar_funcionarios()
        if funcionarios:
            st.dataframe(pd.DataFrame([{
                "Nome": f["nome"], "Cargo": f["cargo"], "Salário": f["salario"],
                "Código vendedor": f.get("vendedor_codigo") or "-",
            } for f in funcionarios]), use_container_width=True, hide_index=True)

    with aba3:
        vendedores = svc.listar_vendedores()
        if not vendedores:
            st.info("Nenhum vendedor cadastrado ainda.")
        else:
            opcoes = {v["codigo"]: v["codigo"] for v in vendedores}
            escolha = st.selectbox("Vendedor", list(opcoes.keys()))
            resultado = svc.calcular_comissao_vendedor(opcoes[escolha])
            st.metric("Comissão a pagar (tempo real)", f"R$ {resultado['comissao_total']:,.2f}")
            if resultado["detalhe"]:
                st.dataframe(pd.DataFrame(resultado["detalhe"]), use_container_width=True, hide_index=True)
