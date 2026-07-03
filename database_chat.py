"""
database_chat.py
Banco de dados exclusivo do módulo de Chat (mensagens motorista <-> ADM
+ presença de ADMs online).

IMPORTANTE sobre "separado do resto do sistema":
Este arquivo usa a MESMA conexão Firestore do restante do painel (o banco
nomeado "portal", aberto via get_db() em database.py) — não é um banco de
dados diferente. O que é separado é o CÓDIGO e as COLEÇÕES:
    - mensagens_chat  (uma conversa por motorista, compartilhada com todos os ADMs)
    - conversas_chat  (1 doc-resumo por motorista: status + contadores)
    - presenca_adm    (quem está com o painel aberto agora)
Isso já é suficiente pra isolar o chat: se algo quebrar aqui, não derruba
o database.py principal, e vice-versa.

Fica na raiz do projeto, ao lado do database.py e do main.py.

──────────────────────────────────────────────────────────────────────
OTIMIZAÇÃO DE PERFORMANCE (leia antes de mexer):
Antes, "quantas mensagens não lidas esse motorista tem?" era respondido
baixando até 1000 mensagens da conversa inteira e contando em Python —
e isso rodava para TODOS os motoristas, a cada rerun de QUALQUER página
do sistema (porque o main.py usa esse número no badge da sidebar) e
também a cada 2s dentro do fragment do Chat. Isso é O(mensagens) e caro.

Agora mantemos um contador incremental no doc-resumo /conversas_chat/{id}:
    - nao_lidas_adm       → quantas mensagens do MOTORISTA o ADM não leu
    - nao_lidas_motorista → quantas mensagens do ADM o motorista não leu
Cada envio faz um Increment(1); cada "marcar como lida" zera o campo.
listar_conversas_com_nao_lidas() passa a ler 1 documento pequeno por
motorista, em vez de até 1000 mensagens por motorista.
──────────────────────────────────────────────────────────────────────
"""

from datetime import datetime, timezone

from google.cloud.firestore import Increment

from database import get_db

# Usado só para dar uma mensagem de erro mais clara quando falta um índice
# composto no Firestore (ver _rodar_query abaixo).
try:
    from google.api_core.exceptions import FailedPrecondition
except ImportError:  # pragma: no cover — biblioteca já vem junto do google-cloud-firestore
    FailedPrecondition = None


def _rodar_query(query):
    """
    Executa um .stream() do Firestore e, se faltar um índice composto,
    transforma o erro cru em uma mensagem que qualquer pessoa consegue agir
    (o Firestore já manda o link pronto pra criar o índice em 1 clique —
    só que escondido dentro de uma exceção técnica).
    """
    try:
        return list(query.stream())
    except Exception as e:
        if FailedPrecondition and isinstance(e, FailedPrecondition):
            raise RuntimeError(
                "O Firestore precisa de um índice para essa consulta do Chat "
                "(isso só acontece na primeira vez). Abra o link abaixo, clique "
                "em 'Criar índice' no console do Firebase, espere ~1 minuto e "
                f"tente de novo:\n\n{e}"
            ) from e
        raise


# ── ENVIO E LEITURA DE MENSAGENS ───────────────────────────────────

def enviar_mensagem_chat(motorista_usuario: str, remetente: str, texto: str, remetente_tipo: str):
    """
    Salva uma mensagem na conversa de um motorista específico e incrementa
    o contador de não-lidas do "outro lado" no doc-resumo da conversa
    (em vez de recontar tudo depois).
    remetente_tipo: "motorista" ou "adm"
    A conversa é sempre indexada pelo login do motorista (1 conversa por
    motorista, compartilhada entre todos os ADMs — como uma caixa de
    suporte, e não um chat 1-a-1 fixo).
    Se quem manda é o motorista, a conversa é automaticamente REABERTA
    (mesmo que um ADM já tenha finalizado antes) — é assim que o motorista
    "reaparece" na lista de atendimento ao chamar de novo.
    """
    texto = (texto or "").strip()
    if not texto:
        return

    db = get_db()
    db.collection("mensagens_chat").add({
        "conversa_id": motorista_usuario,
        "remetente": remetente,
        "remetente_tipo": remetente_tipo,
        "texto": texto,
        "timestamp": datetime.now(timezone.utc),
        "lida": False,
    })

    # Quem manda incrementa o contador de quem vai LER (o outro lado).
    campo_incr = "nao_lidas_adm" if remetente_tipo == "motorista" else "nao_lidas_motorista"
    updates = {
        "motorista": motorista_usuario,
        "atualizado_em": datetime.now(timezone.utc),
        campo_incr: Increment(1),
        "ultima_msg": texto,
        "ultima_msg_de": remetente_tipo,
    }
    if remetente_tipo == "motorista":
        updates["status"] = "aberta"
    db.collection("conversas_chat").document(motorista_usuario).set(updates, merge=True)


# ── STATUS DA CONVERSA (aberta / finalizada) ────────────────────────

def obter_status_conversa(motorista_usuario: str) -> str:
    """Retorna 'aberta', 'finalizada' ou 'sem_conversa' (nunca existiu)."""
    doc = get_db().collection("conversas_chat").document(motorista_usuario).get()
    if not doc.exists:
        return "sem_conversa"
    return doc.to_dict().get("status", "aberta")


def reabrir_ou_criar_conversa(motorista_usuario: str):
    get_db().collection("conversas_chat").document(motorista_usuario).set({
        "motorista": motorista_usuario,
        "status": "aberta",
        "atualizado_em": datetime.now(timezone.utc),
    }, merge=True)


def finalizar_conversa_chat(motorista_usuario: str, finalizado_por: str):
    get_db().collection("conversas_chat").document(motorista_usuario).set({
        "motorista": motorista_usuario,
        "status": "finalizada",
        "finalizado_por": finalizado_por,
        "finalizado_em": datetime.now(timezone.utc),
    }, merge=True)


def obter_mensagens_chat(motorista_usuario: str, limite: int = 200):
    """Retorna as mensagens da conversa de um motorista, em ordem cronológica.
    Usada para abrir e ler UMA conversa específica (não para contar não-lidas
    de todo mundo — isso agora é listar_conversas_com_nao_lidas)."""
    query = (
        get_db().collection("mensagens_chat")
        .where("conversa_id", "==", motorista_usuario)
        .order_by("timestamp")
        .limit(limite)
    )
    docs = _rodar_query(query)
    return [{**d.to_dict(), "id": d.id} for d in docs]


def marcar_mensagens_lidas(motorista_usuario: str, remetente_tipo_oposto: str):
    """
    Marca como lidas as mensagens vindas do "outro lado" e zera o contador
    correspondente no doc-resumo da conversa.
    Chame com remetente_tipo_oposto="motorista" quando um ADM abrir a conversa,
    e com remetente_tipo_oposto="adm" quando o motorista abrir o chat dele.
    """
    db = get_db()

    # Zera o contador incremental (rápido, 1 escrita) — é o que os badges usam.
    campo_incr = "nao_lidas_adm" if remetente_tipo_oposto == "motorista" else "nao_lidas_motorista"
    db.collection("conversas_chat").document(motorista_usuario).set(
        {campo_incr: 0}, merge=True
    )

    # Mantém o histórico de "lida=True" nas mensagens individuais (usado na
    # tela de conversa aberta, não no cálculo de badge).
    query = (
        db.collection("mensagens_chat")
        .where("conversa_id", "==", motorista_usuario)
        .where("remetente_tipo", "==", remetente_tipo_oposto)
        .where("lida", "==", False)
    )
    docs = _rodar_query(query)
    if not docs:
        return
    batch = db.batch()
    for d in docs:
        batch.update(d.reference, {"lida": True})
    batch.commit()


def listar_conversas_com_nao_lidas(lista_motoristas: list):
    """
    Para o painel do ADM: retorna, para cada motorista, quantas mensagens
    não lidas ele mandou e qual foi a última mensagem.

    OTIMIZADO: lê 1 documento pequeno (/conversas_chat/{motorista}) por
    motorista, em vez de baixar até 1000 mensagens por motorista e contar
    em Python. O contador vem pronto (nao_lidas_adm), mantido de forma
    incremental por enviar_mensagem_chat / marcar_mensagens_lidas.
    """
    db = get_db()
    resultado = []
    for m in lista_motoristas:
        doc = db.collection("conversas_chat").document(m).get()
        d = doc.to_dict() if doc.exists else {}
        resultado.append({
            "motorista": m,
            "nao_lidas": d.get("nao_lidas_adm", 0),
            "ultima_msg": d.get("ultima_msg", ""),
            "ultima_hora": d.get("atualizado_em"),
        })
    return resultado


# ── PRESENÇA DOS ADMs (quem está com o painel aberto agora) ────────

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


def limpar_presenca_antiga(dias: int = 7):
    """
    Manutenção opcional: remove registros de presença muito antigos
    (ex: ADMs que nunca mais logaram) para manter a coleção enxuta.
    Não é chamado automaticamente — use se quiser, de tempos em tempos,
    numa tela de manutenção/administração.
    """
    limite = datetime.now(timezone.utc).timestamp() - (dias * 86400)
    db = get_db()
    batch = db.batch()
    tem_algo = False
    for d in db.collection("presenca_adm").stream():
        ping = d.to_dict().get("ultimo_ping")
        if ping and ping.timestamp() < limite:
            batch.delete(d.reference)
            tem_algo = True
    if tem_algo:
        batch.commit()
