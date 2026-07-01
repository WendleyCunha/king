"""
database_chat.py
Banco exclusivo do módulo de Chat (mensagens motorista <-> ADM + presença de ADMs online).

Fica na raiz do projeto, ao lado do database.py e do main.py.
Reaproveita a MESMA conexão Firestore do resto do sistema, chamando get_db()
(seu database.py já cuida de abrir a conexão certa, com o banco nomeado "portal",
e de guardar em st.session_state para não reconectar a cada rerun).
"""

from datetime import datetime, timezone

from database import get_db


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
    get_db().collection("mensagens_chat").add({
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
        get_db().collection("mensagens_chat")
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
    db = get_db()
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
    get_db().collection("presenca_adm").document(usuario).set({
        "nome": nome,
        "ultimo_ping": datetime.now(timezone.utc),
    })


def listar_admins_online(janela_segundos: int = 60):
    """Considera 'online' quem deu um ping nos últimos N segundos."""
    agora = datetime.now(timezone.utc)
    online = []
    for d in get_db().collection("presenca_adm").stream():
        data = d.to_dict()
        ping = data.get("ultimo_ping")
        if ping and (agora - ping).total_seconds() <= janela_segundos:
            online.append({"usuario": d.id, "nome": data.get("nome", d.id)})
    return online
