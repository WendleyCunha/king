import streamlit as st
import pandas as pd
from services import produto_service as svc


def render(pode_editar: bool, usuario_login: str):
    st.header("📦 Produtos e Estoque")

    aba1, aba2 = st.tabs(["Cadastro de produto", "Entrada de mercadoria"])

    with aba1:
        if pode_editar:
            with st.form("form_produto", clear_on_submit=True):
                col1, col2 = st.columns(2)
                sku = col1.text_input("SKU *")
                nome = col2.text_input("Nome *")
                col3, col4 = st.columns(2)
                categoria = col3.text_input("Categoria")
                preco = col4.number_input("Preço de venda (R$) *", min_value=0.0, step=10.0)
                custo = st.number_input("Custo (R$)", min_value=0.0, step=10.0)
                descricao = st.text_area("Descrição")
                if st.form_submit_button("Cadastrar produto"):
                    try:
                        produto = svc.cadastrar_produto(
                            sku=sku, nome=nome, preco=preco, custo=custo,
                            categoria=categoria, descricao=descricao,
                        )
                        st.success(f"Produto {produto['sku']} cadastrado. QR code gerado.")
                        st.image(produto["qrcode_path"], width=150, caption=f"QR do produto {produto['sku']}")
                    except ValueError as e:
                        st.error(str(e))

        st.subheader("Produtos cadastrados")
        produtos = svc.listar_produtos()
        if produtos:
            df = pd.DataFrame([{
                "SKU": p["sku"], "Nome": p["nome"], "Categoria": p.get("categoria"),
                "Preço": p["preco"], "Saldo em estoque": p["saldo_estoque"],
            } for p in produtos])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum produto cadastrado ainda.")

    with aba2:
        st.caption(
            "Registra a chegada de itens no estoque. Isso libera automaticamente "
            "pedidos BLOQUEADOS desse mesmo SKU (mais antigos primeiro)."
        )
        if pode_editar:
            produtos = svc.listar_produtos()
            if not produtos:
                st.info("Cadastre um produto primeiro.")
            else:
                with st.form("form_entrada", clear_on_submit=True):
                    opcoes = {f"{p['sku']} - {p['nome']}": p["sku"] for p in produtos}
                    escolha = st.selectbox("Produto", list(opcoes.keys()))
                    quantidade = st.number_input("Quantidade recebida", min_value=1, step=1)
                    if st.form_submit_button("Registrar entrada"):
                        try:
                            liberados = svc.entrada_estoque(
                                sku=opcoes[escolha], quantidade=int(quantidade), usuario_login=usuario_login,
                            )
                            st.success("Entrada registrada.")
                            if liberados:
                                st.info("Pedidos liberados automaticamente: " + ", ".join(liberados))
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
        else:
            st.warning("Você não tem permissão de edição nesta aba.")
