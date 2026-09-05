"""
Motorista deixou de ter cadastro próprio no ERP — o Painel principal já
tem tudo isso (usuários com role="motorista" e campo "placa", cadastrados
em Configurações → Usuários). Duplicar esse cadastro aqui só criaria duas
fontes da mesma informação desincronizando. Este serviço só LÊ dali.
"""
from database import listar_usuarios  # módulo do Painel principal (Firestore "portal")
from erp.db import get_db

COL_CARGAS = "cargas"


def listar_motoristas() -> list:
    return [u for u in listar_usuarios() if u.get("role") == "motorista"]


def entregas_por_motorista() -> list:
    """
    Quantidade de entregas por motorista — mesma consulta que alimenta o
    APP ENTREGAS / aba "Minhas Entregas" do motorista (ver main.py: quem
    tem role motorista já usa o próprio login pra ver só as suas cargas).
    """
    motoristas = listar_motoristas()
    cargas = list(get_db().collection(COL_CARGAS).stream())
    resultado = []
    for m in motoristas:
        total = sum(
            len(c.to_dict().get("pedidos", []))
            for c in cargas
            if c.to_dict().get("motorista_login") == m["usuario"]
            and c.to_dict().get("status") == "FINALIZADA"
        )
        resultado.append({"motorista": m, "total_entregas": total})
    return resultado


def entregas_do_motorista(motorista_login: str) -> list:
    db = get_db()
    cargas = db.collection(COL_CARGAS).where("motorista_login", "==", motorista_login).stream()
    numeros = []
    for c in cargas:
        numeros.extend(c.to_dict().get("pedidos", []))
    if not numeros:
        return []
    # Firestore 'in' aceita no máximo 30 itens — em volume maior, quebrar em lotes.
    docs = db.collection("pedidos").where("numero", "in", numeros[:30]).stream()
    return [d.to_dict() for d in docs]
