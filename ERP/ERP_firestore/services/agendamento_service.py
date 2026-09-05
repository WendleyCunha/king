import datetime
from db import get_db, agora_iso

COL = "pedidos"


def agendar_entrega(numero_pedido: str, data_entrega: datetime.datetime):
    ref = get_db().collection(COL).document(numero_pedido)
    doc = ref.get()
    if not doc.exists:
        raise ValueError("Pedido não encontrado.")
    pedido = doc.to_dict()

    if pedido["status"] == "BLOQUEADO":
        raise ValueError(f"Pedido {numero_pedido} está BLOQUEADO (sem estoque) e não pode ser agendado.")
    if pedido["status"] != "LIBERADO":
        raise ValueError(
            f"Pedido {numero_pedido} está em status {pedido['status']}; só pedidos LIBERADOS podem ser agendados."
        )

    ref.update({
        "status": "AGENDADO",
        "data_agendamento": data_entrega.isoformat(),
        "atualizado_em": agora_iso(),
    })


def listar_pedidos_liberados_para_agendar() -> list:
    docs = get_db().collection(COL).where("status", "==", "LIBERADO").stream()
    return [d.to_dict() for d in docs]


def listar_pedidos_bloqueados() -> list:
    docs = get_db().collection(COL).where("status", "==", "BLOQUEADO").stream()
    return [d.to_dict() for d in docs]
