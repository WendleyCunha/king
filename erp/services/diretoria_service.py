from google.cloud import firestore
from erp.db import get_db, agora_iso
from erp.services import produto_service

ESTADOS_TRAVADOS = ("EM_ROTA", "FATURADO", "CANCELADO")


def eliminar_pedido(numero_pedido: str, usuario_login: str) -> dict:
    """
    Só a ABA DIRETORIA pode eliminar um pedido.
    - LIBERADO / AGENDADO / EM_CARGA: já havia debitado estoque -> devolve.
    - BLOQUEADO: nunca debitou -> só sai da fila de compras (que é derivada
      do próprio status, então "sair" = virar CANCELADO).
    - EM_ROTA / FATURADO / CANCELADO: carga travada, não pode mais eliminar.
    """
    db = get_db()
    pedido_ref = db.collection("pedidos").document(numero_pedido)

    @firestore.transactional
    def _tx(transaction):
        snap = pedido_ref.get(transaction=transaction)
        if not snap.exists:
            raise ValueError("Pedido não encontrado.")
        pedido = snap.to_dict()
        if pedido["status"] in ESTADOS_TRAVADOS:
            raise ValueError(f"Pedido {numero_pedido} está em status {pedido['status']} e não pode mais ser eliminado.")

        if pedido["status"] in ("LIBERADO", "AGENDADO", "EM_CARGA"):
            produto_ref = db.collection("produtos").document(pedido["produto_sku"])
            produto_snap = produto_ref.get(transaction=transaction)
            saldo_atual = produto_snap.to_dict().get("saldo_estoque", 0)
            transaction.update(produto_ref, {"saldo_estoque": saldo_atual + 1})
            transaction.set(db.collection("movimentos_estoque").document(), {
                "sku": pedido["produto_sku"], "tipo": "DEVOLUCAO", "quantidade": 1,
                "motivo": f"Eliminação do pedido {numero_pedido} pela DIRETORIA",
                "usuario": usuario_login, "pedido_numero": numero_pedido, "criado_em": agora_iso(),
            })

        transaction.update(pedido_ref, {
            "status": "CANCELADO", "carga_id": None, "atualizado_em": agora_iso(),
        })
        transaction.set(db.collection("notificacoes").document(), {
            "aba_destino": "AGENDAR", "mensagem": f"Pedido {numero_pedido} foi eliminado pela DIRETORIA.",
            "pedido_numero": numero_pedido, "lida": False, "criado_em": agora_iso(),
        })
        return pedido

    pedido = _tx(db.transaction())
    produto_service.listar_produtos.clear()
    return pedido


def ajustar_saldo_produto(sku: str, novo_saldo: int, motivo: str, usuario_login: str):
    """Correção de SKU digitado errado na entrada de estoque. Só DIRETORIA."""
    db = get_db()
    produto_ref = db.collection("produtos").document(sku)
    produto_doc = produto_ref.get()
    if not produto_doc.exists:
        raise ValueError("Produto não encontrado.")
    diferenca = novo_saldo - produto_doc.to_dict().get("saldo_estoque", 0)
    produto_ref.update({"saldo_estoque": novo_saldo})
    db.collection("movimentos_estoque").document().set({
        "sku": sku, "tipo": "AJUSTE", "quantidade": abs(diferenca),
        "motivo": f"Ajuste manual DIRETORIA: {motivo} (diferença {diferenca:+d})",
        "usuario": usuario_login, "pedido_numero": None, "criado_em": agora_iso(),
    })
    produto_service.listar_produtos.clear()


def cadastrar_regra_comissao(tipo: str, percentual: float) -> dict:
    ref = get_db().collection("regras_comissao").document()
    regra = {"id": ref.id, "tipo": tipo, "percentual": percentual, "ativo": True, "criado_em": agora_iso()}
    ref.set(regra)
    return regra


def desativar_regra_comissao(regra_id: str):
    get_db().collection("regras_comissao").document(regra_id).update({"ativo": False})


def definir_salario(funcionario_id: str, novo_salario: float):
    ref = get_db().collection("funcionarios").document(funcionario_id)
    if not ref.get().exists:
        raise ValueError("Funcionário não encontrado.")
    ref.update({"salario": novo_salario})
