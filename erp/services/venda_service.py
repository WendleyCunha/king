from google.cloud import firestore
from erp.db import get_db, agora_iso, proximo_numero
from erp.qr_utils import gerar_qrcode_item_venda
from erp.services import produto_service

COL_PEDIDOS = "pedidos"


def registrar_venda(cliente_id: str, produto_sku: str, valor: float, forma_pagamento: str,
                     vendedor_codigo: str = None, usuario_login: str = None) -> dict:
    """
    ABA VENDA: busca cliente, vincula ao produto. Roda numa TRANSACTION
    pra checar/baixar o estoque de forma atômica — evita que duas vendas
    simultâneas do último item em estoque liberem os dois pedidos.
    """
    db = get_db()
    numero = proximo_numero("pedidos", "PED")
    pedido_ref = db.collection(COL_PEDIDOS).document(numero)
    produto_ref = db.collection("produtos").document(produto_sku)
    cliente_ref = db.collection("clientes").document(cliente_id)

    @firestore.transactional
    def _tx(transaction):
        cliente_snap = cliente_ref.get(transaction=transaction)
        if not cliente_snap.exists:
            raise ValueError("Cliente não encontrado.")
        produto_snap = produto_ref.get(transaction=transaction)
        if not produto_snap.exists:
            raise ValueError("Produto não encontrado.")

        if vendedor_codigo:
            vend_snap = db.collection("vendedores").document(vendedor_codigo).get(transaction=transaction)
            if not vend_snap.exists or not vend_snap.to_dict().get("ativo", True):
                raise ValueError("Código de vendedor inválido ou inativo.")

        cliente = cliente_snap.to_dict()
        produto = produto_snap.to_dict()
        tem_estoque = produto.get("saldo_estoque", 0) > 0
        status = "LIBERADO" if tem_estoque else "BLOQUEADO"

        pedido_doc = {
            "numero": numero, "cliente_id": cliente_id, "cliente_nome": cliente["nome"],
            "produto_sku": produto_sku, "produto_nome": produto["nome"],
            "valor": valor, "forma_pagamento": forma_pagamento, "vendedor_codigo": vendedor_codigo,
            "status": status, "data_agendamento": None, "carga_id": None,
            "nota_fiscal_numero": None, "qrcode_item_path": None,
            "criado_em": agora_iso(), "atualizado_em": agora_iso(),
        }
        transaction.set(pedido_ref, pedido_doc)

        if tem_estoque:
            transaction.update(produto_ref, {"saldo_estoque": produto["saldo_estoque"] - 1})
            transaction.set(db.collection("movimentos_estoque").document(), {
                "sku": produto_sku, "tipo": "SAIDA_VENDA", "quantidade": 1,
                "motivo": f"Venda / Pedido {numero}", "usuario": usuario_login,
                "pedido_numero": numero, "criado_em": agora_iso(),
            })

        transaction.set(db.collection("lancamentos_financeiros").document(), {
            "pedido_numero": numero, "valor": valor, "forma_pagamento": forma_pagamento,
            "vendedor_codigo": vendedor_codigo, "criado_em": agora_iso(),
        })
        return pedido_doc

    pedido_doc = _tx(db.transaction())

    # QR code é I/O de arquivo local, fica fora da transaction do Firestore.
    caminho_qr = gerar_qrcode_item_venda(numero, produto_sku)
    pedido_ref.update({"qrcode_item_path": caminho_qr})
    pedido_doc["qrcode_item_path"] = caminho_qr

    produto_service.listar_produtos.clear()
    return pedido_doc


def listar_pedidos(status: str = None) -> list:
    q = get_db().collection(COL_PEDIDOS)
    if status:
        q = q.where("status", "==", status)
    docs = q.stream()
    return sorted([d.to_dict() for d in docs], key=lambda p: p.get("criado_em", ""), reverse=True)
