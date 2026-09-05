import streamlit as st
from services import cliente_service, produto_service
from services import venda_service as svc


def render(pode_editar: bool, usuario_login: str):
    st.header("🛒 Venda")

    if not pode_editar:
        st.warning("Você não tem permissão de edição nesta aba.")
        return

    st.subheader("1. Buscar cliente")
    termo = st.text_input("Buscar por nome ou CPF/CNPJ")
    clientes = cliente_service.buscar_cliente(termo)
    if not clientes:
        st.info("Nenhum cliente encontrado. Cadastre na ABA CADASTRO.")
        return
    opcoes_cliente = {f"{c['nome']} - {c['cpf_cnpj']}": c["id"] for c in clientes}
    cliente_escolhido = st.selectbox("Cliente", list(opcoes_cliente.keys()))

    st.subheader("2. Produto")
    produtos = produto_service.listar_produtos()
    if not produtos:
        st.info("Nenhum produto cadastrado. Cadastre na ABA PRODUTO.")
        return
    opcoes_produto = {f"{p['sku']} - {p['nome']} (estoque: {p['saldo_estoque']})": p for p in produtos}
    produto = opcoes_produto[st.selectbox("Produto", list(opcoes_produto.keys()))]
    if produto["saldo_estoque"] <= 0:
        st.warning(
            "⚠️ Este produto está sem estoque. A venda pode ser feita, mas o pedido "
            "nascerá BLOQUEADO até a próxima entrada de mercadoria."
        )

    st.subheader("3. Dados da venda")
    col1, col2 = st.columns(2)
    valor = col1.number_input("Valor da venda (R$)", min_value=0.0, value=float(produto["preco"]), step=10.0)
    forma_pagamento = col2.selectbox(
        "Forma de pagamento", ["Dinheiro", "PIX", "Cartão de crédito", "Cartão de débito", "Boleto"]
    )
    vendedor_codigo = st.text_input("Código do vendedor (opcional, para comissão)")

    if st.button("Confirmar venda"):
        try:
            pedido = svc.registrar_venda(
                cliente_id=opcoes_cliente[cliente_escolhido], produto_sku=produto["sku"],
                valor=valor, forma_pagamento=forma_pagamento,
                vendedor_codigo=vendedor_codigo or None, usuario_login=usuario_login,
            )
            if pedido["status"] == "LIBERADO":
                st.success(f"Venda concluída! Pedido {pedido['numero']} está LIBERADO — já pode ser agendado.")
            else:
                st.warning(
                    f"Venda registrada, mas o produto está sem estoque. Pedido {pedido['numero']} "
                    "nasceu BLOQUEADO e foi enviado para a ABA ENCOMENDAR."
                )
            st.image(pedido["qrcode_item_path"], width=150, caption="QR code deste item vendido")
        except ValueError as e:
            st.error(str(e))
