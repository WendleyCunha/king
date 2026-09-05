from erp.db import get_db


def listar_fila_compras() -> list:
    """
    Agrupa os pedidos BLOQUEADOS por SKU (cada pedido = 1 item único),
    formando a fila de compras. Não existe uma coleção 'encomendas'
    separada: o próprio pedido BLOQUEADO É a encomenda pendente — evita
    manter dois lugares sincronizados pra mesma informação.
    """
    docs = get_db().collection("pedidos").where("status", "==", "BLOQUEADO").stream()
    resumo = {}
    for d in docs:
        p = d.to_dict()
        sku = p["produto_sku"]
        resumo.setdefault(sku, {"produto_nome": p["produto_nome"], "quantidade": 0, "pedidos": []})
        resumo[sku]["quantidade"] += 1
        resumo[sku]["pedidos"].append(p["numero"])
    return [{"sku": sku, **info} for sku, info in resumo.items()]
