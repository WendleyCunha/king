import datetime
from db import get_db

COL = "lancamentos_financeiros"


def listar_lancamentos(data_inicio: datetime.date = None, data_fim: datetime.date = None) -> list:
    docs = get_db().collection(COL).stream()
    out = [d.to_dict() for d in docs]
    if data_inicio or data_fim:
        filtrado = []
        for l in out:
            dt = datetime.datetime.fromisoformat(l["criado_em"]).date()
            if data_inicio and dt < data_inicio:
                continue
            if data_fim and dt > data_fim:
                continue
            filtrado.append(l)
        out = filtrado
    return sorted(out, key=lambda l: l["criado_em"], reverse=True)


def total_por_forma_pagamento(**filtros) -> dict:
    totais = {}
    for l in listar_lancamentos(**filtros):
        totais[l["forma_pagamento"]] = totais.get(l["forma_pagamento"], 0) + l["valor"]
    return totais


def total_por_vendedor(**filtros) -> dict:
    totais = {}
    for l in listar_lancamentos(**filtros):
        chave = l.get("vendedor_codigo") or "SEM VENDEDOR"
        totais[chave] = totais.get(chave, 0) + l["valor"]
    return totais
