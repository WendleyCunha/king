from db import get_db

REF = ("empresa", "config")  # coleção "empresa", doc fixo "config"


def salvar_dados_empresa(**dados):
    get_db().collection(REF[0]).document(REF[1]).set(dados, merge=True)


def obter_dados_empresa() -> dict:
    doc = get_db().collection(REF[0]).document(REF[1]).get()
    return doc.to_dict() if doc.exists else None
