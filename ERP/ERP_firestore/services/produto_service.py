import streamlit as st
from google.cloud import firestore
from db import get_db, agora_iso
from qr_utils import gerar_qrcode_produto

COL_PRODUTOS = "produtos"          # doc id = SKU
COL_MOVIMENTOS = "movimentos_estoque"
COL_PEDIDOS = "pedidos"


def cadastrar_produto(sku: str, nome: str, preco: float, **dados) -> dict:
    db = get_db()
    ref = db.collection(COL_PRODUTOS).document(sku)
    if ref.get().exists:
        raise ValueError("Já existe produto com esse SKU.")
    dados.update({
        "sku": sku, "nome": nome, "preco": preco, "saldo_estoque": 0,
        "ativo": True, "criado_em": agora_iso(),
    })
    ref.set(dados)
    caminho_qr = gerar_qrcode_produto(sku)
    ref.update({"qrcode_path": caminho_qr})
    dados["qrcode_path"] = caminho_qr
    listar_produtos.clear()
    return dados


def atualizar_produto(sku: str, **dados):
    get_db().collection(COL_PRODUTOS).document(sku).update(dados)
    listar_produtos.clear()


@st.cache_data(ttl=20, show_spinner=False)
def listar_produtos(apenas_ativos=True) -> list:
    docs = get_db().collection(COL_PRODUTOS).stream()
    out = [d.to_dict() for d in docs]
    if apenas_ativos:
        out = [p for p in out if p.get("ativo", True)]
    return sorted(out, key=lambda p: p.get("nome", ""))


def entrada_estoque(sku: str, quantidade: int, usuario_login: str,
                     motivo: str = "Chegada de mercadoria") -> tuple[int, list]:
    """
    ABA PRODUTO -> entrada de item que chegou.

    Roda numa TRANSACTION pra garantir que, se duas entradas chegarem ao
    mesmo tempo (ou uma entrada e uma venda simultânea), o saldo e a
    liberação de pedidos bloqueados fiquem sempre consistentes.

    Cada pedido representa 1 item único (regra do negócio), então a
    liberação é sempre "um pedido bloqueado por vez", do mais antigo pro
    mais novo, até a quantidade recebida acabar.

    ÍNDICE NECESSÁRIO: composto (produto_sku ASC, status ASC, criado_em ASC)
    na coleção 'pedidos' — na primeira execução, se faltar, o próprio erro
    do Firestore traz o link pronto pra criar em 1 clique.
    """
    if quantidade <= 0:
        raise ValueError("Quantidade de entrada deve ser maior que zero.")

    db = get_db()
    produto_ref = db.collection(COL_PRODUTOS).document(sku)

    @firestore.transactional
    def _tx(transaction):
        produto_snap = produto_ref.get(transaction=transaction)
        if not produto_snap.exists:
            raise ValueError("Produto não encontrado.")
        saldo = produto_snap.to_dict().get("saldo_estoque", 0)

        query = (
            db.collection(COL_PEDIDOS)
            .where("produto_sku", "==", sku)
            .where("status", "==", "BLOQUEADO")
            .order_by("criado_em")
        )
        bloqueados = list(query.stream(transaction=transaction))

        liberados = []
        restante = quantidade
        saldo += quantidade
        for doc in bloqueados:
            if restante < 1:
                break
            pedido = doc.to_dict()
            transaction.update(doc.reference, {"status": "LIBERADO"})
            transaction.set(db.collection(COL_MOVIMENTOS).document(), {
                "sku": sku, "tipo": "SAIDA_VENDA", "quantidade": 1,
                "motivo": f"Baixa automática ao liberar pedido {pedido['numero']}",
                "usuario": usuario_login, "pedido_numero": pedido["numero"],
                "criado_em": agora_iso(),
            })
            transaction.set(db.collection("notificacoes").document(), {
                "aba_destino": "AGENDAR",
                "mensagem": f"Pedido {pedido['numero']} foi liberado (estoque chegou) e já pode ser agendado.",
                "pedido_numero": pedido["numero"], "lida": False, "criado_em": agora_iso(),
            })
            saldo -= 1
            restante -= 1
            liberados.append(pedido["numero"])

        transaction.update(produto_ref, {"saldo_estoque": saldo})
        transaction.set(db.collection(COL_MOVIMENTOS).document(), {
            "sku": sku, "tipo": "ENTRADA", "quantidade": quantidade, "motivo": motivo,
            "usuario": usuario_login, "pedido_numero": None, "criado_em": agora_iso(),
        })
        return liberados

    liberados = _tx(db.transaction())
    listar_produtos.clear()
    return liberados
