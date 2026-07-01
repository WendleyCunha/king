"""
database_chat.py
Banco exclusivo do módulo de Chat (mensagens motorista <-> ADM + presença de ADMs online).

Este arquivo PRECISA ficar na raiz do projeto, ao lado do database.py e do main.py
(mesma pasta), porque o mod_chat.py importa com `from database_chat import ...`.

Ele reaproveita o client Firestore que o seu database.py já inicializa, para não
tentar abrir uma segunda conexão com o Firebase (o que causa erro de "app já
inicializado").
"""

from datetime import datetime, timezone

# ── Reaproveita o client Firestore já existente no seu database.py ────────
# Se o seu database.py tiver o client Firestore com um nome diferente de "db",
# troque "db" abaixo pelo nome real (ex: from database import firestore_db as db).
try:
    from database import db
except ImportError as e:
    raise ImportError(
        "database_chat.py não conseguiu importar o client Firestore `db` de database.py. "
        "Abra o seu database.py, encontre a linha onde ele guarda o client "
        "(algo como `db = firestore.client()`) e garanta que essa variável se "
        "chama `db` — ou ajuste o import no topo do database_chat.py para o "
        "nome correto."
    ) from e


# ── ENVIO E LEITURA DE MENSAGENS ───────────────────────────────────

def enviar_mensagem_chat(motorista_usuario: str, remetente: str, texto: str, remetente_tipo: str):
    """
    Salva uma mensagem na conversa de um motorista específico.
    remetente_tipo: "motorista" ou "adm"
    A conversa é sempre indexada pelo login do motorista (1 conversa por
    motorista, compartilhada entre todos os ADMs — como uma caixa de
    suporte, e não um chat 1-a-1 fixo).
    """
    if not texto or not texto.strip():
        return
    db.collection("mensagens_chat").add({
        "conversa_id": motorista_usuario,
        "remetente": remetente,
        "remetente_tipo": remetente_tipo,
        "texto": texto.strip(),
        "timestamp": datetime.now(timezone.utc),
        "lida": False,
    })


def obter_mensagens_chat(motorista_usuario: str, limite: int = 200):
    """Retorna as mensagens da conversa de um motorista, em ordem cronológica."""
    docs = (
        db.collection("mensagens_chat")
        .where("conversa_id", "==", motorista_usuario)
        .order_by("timestamp")
        .limit(limite)
        .stream()
    )
    return [{**d.to_dict(), "id": d.id} for d in docs]


def marcar_mensagens_lidas(motorista_usuario: str, remetente_tipo_oposto: str):
    """
    Marca como lidas as mensagens vindas do "outro lado".
    Chame com remetente_tipo_oposto="motorista" quando um ADM abrir a conversa,
    e com remetente_tipo_oposto="adm" quando o motorista abrir o chat dele.
    """
    docs = (
        db.collection("mensagens_chat")
        .where("conversa_id", "==", motorista_usuario)
        .where("remetente_tipo", "==", remetente_tipo_oposto)
        .where("lida", "==", False)
        .stream()
    )
    batch = db.batch()
    tem_algo = False
    for d in docs:
        batch.update(d.reference, {"lida": True})
        tem_algo = True
    if tem_algo:
        batch.commit()


def listar_conversas_com_nao_lidas(lista_motoristas: list):
    """
    Para o painel do ADM: retorna, para cada motorista, quantas mensagens
    não lidas ele mandou e qual foi a última mensagem.
    """
    resultado = []
    for m in lista_motoristas:
        msgs = obter_mensagens_chat(m, limite=1000)
        nao_lidas = sum(1 for x in msgs if x["remetente_tipo"] == "motorista" and not x["lida"])
        ultima = msgs[-1] if msgs else None
        resultado.append({
            "motorista": m,
            "nao_lidas": nao_lidas,
            "ultima_msg": ultima["texto"] if ultima else "",
            "ultima_hora": ultima["timestamp"] if ultima else None,
        })
    return resultado


# ── PRESENÇA DOS ADMs (quem está com o painel aberto agora) ───────

def marcar_presenca_adm(usuario: str, nome: str):
    """Chamar a cada carregamento/refresh da tela do ADM para 'renovar' o status online."""
    db.collection("presenca_adm").document(usuario).set({
        "nome": nome,
        "ultimo_ping": datetime.now(timezone.utc),
    })


def listar_admins_online(janela_segundos: int = 60):
    """Considera 'online' quem deu um ping nos últimos N segundos."""
    agora = datetime.now(timezone.utc)
    online = []
    for d in db.collection("presenca_adm").stream():
        data = d.to_dict()
        ping = data.get("ultimo_ping")
        if ping and (agora - ping).total_seconds() <= janela_segundos:
            online.append({"usuario": d.id, "nome": data.get("nome", d.id)})
    return online
