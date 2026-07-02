"""
database_logistica.py
Funções de banco exclusivas da logística de entregas (upload de planilha
roteirizada) — separadas do database.py principal pelo mesmo motivo do
database_chat.py: isolar uma área de negócio específica do restante do
sistema (usuários, tickets, cartas, RH, etc.), sem duplicar a conexão.

Reaproveita a mesma conexão Firestore (banco "portal") via get_db(),
que já vive no database.py.
"""

from database import get_db


def salvar_entregas_db(entregas: list, data_alvo: str) -> int:
    """
    Salva uma lista de entregas (dicts) na coleção 'entregas' para uma data
    específica. Usada pela importação de planilha na aba "Cadastros" do
    módulo Rastreio.

    Cada item de `entregas` deve conter as mesmas chaves que o dashboard
    de Rastreio já espera (title, address, route, contact_phone, order, ...).
    O campo 'data_entrega' é adicionado automaticamente aqui, então não
    precisa incluir na hora de montar a lista.

    Retorna a quantidade de documentos criados.
    """
    db = get_db()
    batch = db.batch()
    count = 0
    for item in entregas:
        doc = dict(item)
        doc["data_entrega"] = data_alvo
        ref = db.collection("entregas").document()
        batch.set(ref, doc)
        count += 1
        # Firestore limita a 500 operações por batch — commitamos em blocos
        # de 400 pra ter margem de segurança.
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    return count
