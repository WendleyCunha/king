from db import get_db, agora_iso

COL = "notificacoes"


def notificar(aba_destino: str, mensagem: str, pedido_numero: str = None):
    get_db().collection(COL).document().set({
        "aba_destino": aba_destino, "mensagem": mensagem,
        "pedido_numero": pedido_numero, "lida": False, "criado_em": agora_iso(),
    })


def listar_notificacoes(aba: str, apenas_nao_lidas=True) -> list:
    q = get_db().collection(COL).where("aba_destino", "==", aba)
    docs = q.stream()
    out = [{"id": d.id, **d.to_dict()} for d in docs]
    if apenas_nao_lidas:
        out = [n for n in out if not n.get("lida")]
    return sorted(out, key=lambda n: n.get("criado_em", ""), reverse=True)


def marcar_como_lida(notificacao_id: str):
    get_db().collection(COL).document(notificacao_id).update({"lida": True})
