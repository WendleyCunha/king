import datetime
from erp.db import get_db, agora_iso
from erp.services import motorista_service

COL_CARGAS = "cargas"
COL_PEDIDOS = "pedidos"


def listar_pedidos_agendados(data: datetime.date = None) -> list:
    docs = get_db().collection(COL_PEDIDOS).where("status", "==", "AGENDADO").stream()
    out = [d.to_dict() for d in docs if d.to_dict().get("carga_id") is None]
    if data:
        out = [
            p for p in out
            if p.get("data_agendamento") and
            datetime.datetime.fromisoformat(p["data_agendamento"]).date() == data
        ]
    return sorted(out, key=lambda p: p.get("data_agendamento", ""))


def criar_carga(data_prevista: datetime.date = None) -> str:
    ref = get_db().collection(COL_CARGAS).document()
    ref.set({
        "id": ref.id, "motorista_login": None, "status": "MONTAGEM",
        "data_prevista": data_prevista.isoformat() if data_prevista else None,
        "pedidos": [], "criado_em": agora_iso(), "finalizada_em": None,
    })
    return ref.id


def _garantir_carga_editavel(carga: dict):
    if carga["status"] != "MONTAGEM":
        raise ValueError(
            "Esta carga já tem motorista/caminhão atribuído e está travada. Nenhuma "
            "alteração é mais possível (eliminar pedido, mudar agendamento, adicionar/retirar pedido)."
        )


def adicionar_pedido_carga(carga_id: str, numero_pedido: str):
    db = get_db()
    carga_ref = db.collection(COL_CARGAS).document(carga_id)
    carga_doc = carga_ref.get()
    if not carga_doc.exists:
        raise ValueError("Carga não encontrada.")
    carga = carga_doc.to_dict()
    _garantir_carga_editavel(carga)

    pedido_ref = db.collection(COL_PEDIDOS).document(numero_pedido)
    pedido_doc = pedido_ref.get()
    if not pedido_doc.exists or pedido_doc.to_dict().get("status") != "AGENDADO":
        raise ValueError("Só é possível adicionar pedidos AGENDADOS (com data de entrega) à carga.")

    batch = db.batch()
    batch.update(pedido_ref, {"carga_id": carga_id, "status": "EM_CARGA", "atualizado_em": agora_iso()})
    batch.update(carga_ref, {"pedidos": carga.get("pedidos", []) + [numero_pedido]})
    batch.commit()


def retirar_pedido_carga(numero_pedido: str):
    """
    Regra específica: ao retirar um pedido de carga...
    - o número do pedido permanece igual
    - o saldo do produto NÃO retorna ao estoque
    - a data de agendamento é removida (precisa ser reagendado)
    - notifica DIRETORIA, RH e AGENDAR
    """
    db = get_db()
    pedido_ref = db.collection(COL_PEDIDOS).document(numero_pedido)
    pedido_doc = pedido_ref.get()
    if not pedido_doc.exists:
        raise ValueError("Pedido não encontrado.")
    pedido = pedido_doc.to_dict()
    if not pedido.get("carga_id"):
        raise ValueError("Este pedido não está em nenhuma carga.")

    carga_ref = db.collection(COL_CARGAS).document(pedido["carga_id"])
    carga_doc = carga_ref.get()
    carga = carga_doc.to_dict()
    _garantir_carga_editavel(carga)

    batch = db.batch()
    batch.update(pedido_ref, {
        "carga_id": None, "data_agendamento": None, "status": "LIBERADO",
        "atualizado_em": agora_iso(),
    })
    novos_pedidos = [p for p in carga.get("pedidos", []) if p != numero_pedido]
    batch.update(carga_ref, {"pedidos": novos_pedidos})

    msg = f"Pedido {numero_pedido} foi retirado de carga. Precisa ser reagendado."
    for aba in ("DIRETORIA", "RH", "AGENDAR"):
        batch.set(db.collection("notificacoes").document(), {
            "aba_destino": aba, "mensagem": msg, "pedido_numero": numero_pedido,
            "lida": False, "criado_em": agora_iso(),
        })
    batch.commit()


def atribuir_motorista(carga_id: str, motorista_login: str):
    """
    Uma vez atribuído o motorista/caminhão, a carga é finalizada e
    TRAVADA — via batch, garantindo que a carga e todos os seus pedidos
    mudem de status juntos ou nenhum muda.
    """
    db = get_db()
    carga_ref = db.collection(COL_CARGAS).document(carga_id)
    carga_doc = carga_ref.get()
    if not carga_doc.exists:
        raise ValueError("Carga não encontrada.")
    carga = carga_doc.to_dict()
    _garantir_carga_editavel(carga)
    if not carga.get("pedidos"):
        raise ValueError("Carga vazia: adicione pedidos antes de atribuir o motorista.")

    motorista_ok = any(u["usuario"] == motorista_login for u in motorista_service.listar_motoristas())
    if not motorista_ok:
        raise ValueError("Motorista não encontrado (verifique em Configurações → Usuários, no Painel).")

    batch = db.batch()
    batch.update(carga_ref, {
        "motorista_login": motorista_login, "status": "FINALIZADA", "finalizada_em": agora_iso(),
    })
    for numero in carga["pedidos"]:
        batch.update(db.collection(COL_PEDIDOS).document(numero), {
            "status": "EM_ROTA", "atualizado_em": agora_iso(),
        })
    batch.commit()


def listar_cargas(status: str = None) -> list:
    q = get_db().collection(COL_CARGAS)
    if status:
        q = q.where("status", "==", status)
    return sorted([d.to_dict() for d in q.stream()], key=lambda c: c.get("criado_em", ""), reverse=True)


def obter_carga(carga_id: str) -> dict:
    doc = get_db().collection(COL_CARGAS).document(carga_id).get()
    return doc.to_dict() if doc.exists else None
