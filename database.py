import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json, hashlib
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))

def get_db():
    if "db" not in st.session_state:
        key_dict = json.loads(st.secrets["textkey"])
        creds    = service_account.Credentials.from_service_account_info(key_dict)
        st.session_state.db = firestore.Client(
            credentials=creds, project=creds.project_id, database="portal"
        )
    return st.session_state.db

def hash_senha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

MODULOS_PADRAO = {
    "adm":         ["rastreio","tickets","cartas","exportar"],
    "supervisor":  ["rastreio","tickets","cartas","exportar"],
    "operacional": ["rastreio"],
    "motorista":   ["rastreio"],
}

def modulos_do_usuario(user: dict) -> list:
    return user.get("modulos") or MODULOS_PADRAO.get(user.get("role","operacional"), ["rastreio"])

def tem_permissao(user: dict, modulo: str) -> bool:
    return modulo in modulos_do_usuario(user)

def pode_editar(user: dict) -> bool:
    return user.get("role") in ("supervisor","adm")

def pode_exportar(user: dict) -> bool:
    return "exportar" in modulos_do_usuario(user)

def pode_deletar(user: dict) -> bool:
    return user.get("role") == "adm"

# ── Auth ──────────────────────────────────────────────────────────
def verificar_login(usuario: str, senha: str):
    if usuario == "admin" and senha == "admin123":
        return {"nome":"Administrador Master","usuario":"admin",
                "role":"adm","modulos":["rastreio","tickets","cartas","exportar"],
                "departamento":"Todos"}
    doc = get_db().collection("usuarios").document(usuario).get()
    if doc.exists:
        d = doc.to_dict()
        if d.get("senha_hash") == hash_senha(senha):
            return d
    return None

def criar_usuario(nome, usuario, senha, role, modulos=None, departamento="", placa=""):
    """Cria usuário. Agora aceita 'departamento' (Regra 1) e 'placa' (motoristas)."""
    if modulos is None:
        modulos = MODULOS_PADRAO.get(role, ["rastreio"])
    get_db().collection("usuarios").document(usuario).set({
        "nome": nome, "usuario": usuario,
        "senha_hash": hash_senha(senha),
        "role": role, "modulos": modulos,
        "departamento": departamento,
        "placa": placa,
    })

def atualizar_dados_usuario(usuario: str, nome: str = None, placa: str = None):
    """Edita nome e/ou placa de um usuário (usado na edição de motoristas)."""
    campos = {}
    if nome is not None and nome.strip():
        campos["nome"] = nome.strip()
    if placa is not None:
        campos["placa"] = placa.strip()
    if campos:
        get_db().collection("usuarios").document(usuario).update(campos)

def alterar_senha_usuario(usuario: str, senha_atual: str, nova_senha: str):
    """Retorna (True, msg_sucesso) ou (False, msg_erro)."""
    if usuario == "admin":
        return False, "A senha do admin master não pode ser alterada aqui."
    doc = get_db().collection("usuarios").document(usuario).get()
    if not doc.exists:
        return False, "Usuário não encontrado."
    d = doc.to_dict()
    if d.get("senha_hash") != hash_senha(senha_atual):
        return False, "Senha atual incorreta."
    get_db().collection("usuarios").document(usuario).update(
        {"senha_hash": hash_senha(nova_senha)}
    )
    return True, "Senha alterada com sucesso! Faça login novamente."

def atualizar_modulos_usuario(usuario: str, modulos: list):
    get_db().collection("usuarios").document(usuario).update({"modulos": modulos})

def redefinir_senha_usuario(usuario: str, nova_senha: str):
    """Reset de senha pelo admin — não exige a senha atual."""
    if usuario == "admin":
        return False, "A senha do admin master não pode ser alterada aqui."
    doc = get_db().collection("usuarios").document(usuario).get()
    if not doc.exists:
        return False, "Usuário não encontrado."
    get_db().collection("usuarios").document(usuario).update(
        {"senha_hash": hash_senha(nova_senha)}
    )
    return True, "Senha redefinida com sucesso."

def atualizar_departamento_usuario(usuario: str, departamento: str):
    get_db().collection("usuarios").document(usuario).update({"departamento": departamento})

def listar_usuarios():
    return [d.to_dict() for d in get_db().collection("usuarios").stream()]

def deletar_usuario(usuario):
    get_db().collection("usuarios").document(usuario).delete()

# ══════════════════════════════════════════════════════════════════
# DEPARTAMENTOS  (Regra 1)
# Coleção: /departamentos/{nome}  → { nome, descricao, criado_em }
# ══════════════════════════════════════════════════════════════════
def listar_departamentos() -> list:
    docs = get_db().collection("departamentos").stream()
    out = []
    for d in docs:
        item = d.to_dict()
        item["id"] = d.id           # id == nome (usamos o nome como doc id)
        out.append(item)
    return sorted(out, key=lambda x: x.get("nome",""))

def criar_departamento(nome: str, descricao: str = ""):
    nome = nome.strip()
    if not nome:
        return False, "Informe o nome do departamento."
    ref = get_db().collection("departamentos").document(nome)
    if ref.get().exists:
        return False, f"Departamento '{nome}' já existe."
    ref.set({
        "nome": nome,
        "descricao": descricao,
        "criado_em": datetime.now(BRT).isoformat(),
    })
    return True, f"Departamento '{nome}' criado."

def deletar_departamento(dep_id: str):
    """dep_id == nome do departamento."""
    db = get_db()
    ref = db.collection("departamentos").document(dep_id)
    if not ref.get().exists:
        return False, "Departamento não encontrado."

    # Bloqueia exclusão se houver usuários vinculados
    users = list(db.collection("usuarios").where("departamento","==",dep_id).stream())
    if users:
        nomes = ", ".join(u.to_dict().get("usuario","?") for u in users)
        return False, f"Não excluído: {len(users)} usuário(s) vinculado(s): {nomes}"

    # Bloqueia se houver tabulações vinculadas
    tabs = list(db.collection("tabulacoes").where("departamento","==",dep_id).stream())
    if tabs:
        return False, f"Não excluído: {len(tabs)} tabulação(ões) vinculada(s)."

    ref.delete()
    return True, f"Departamento '{dep_id}' excluído."

# ══════════════════════════════════════════════════════════════════
# TABULAÇÕES  (Regra 3 e 4)
# Coleção: /tabulacoes/{auto_id}
#   { nome, departamento, descricao, atendentes[], prioridade, sla_horas, criado_em }
#   atendentes == []  → liberado para todo o departamento
# ══════════════════════════════════════════════════════════════════
def listar_tabulacoes() -> list:
    docs = get_db().collection("tabulacoes").stream()
    out = []
    for d in docs:
        item = d.to_dict()
        item["id"] = d.id
        item.setdefault("atendentes", [])
        item.setdefault("prioridade", "Normal")
        item.setdefault("sla_horas", 24)
        out.append(item)
    return sorted(out, key=lambda x: (x.get("departamento",""), x.get("nome","")))

def criar_tabulacao(nome, departamento, descricao="",
                    atendentes=None, prioridade="Normal", sla_horas=24):
    nome = (nome or "").strip()
    if not nome or not departamento:
        return False, "Preencha nome e departamento."
    if atendentes is None:
        atendentes = []

    db = get_db()
    # duplicata (mesmo nome no mesmo depto)
    existentes = db.collection("tabulacoes") \
                   .where("departamento","==",departamento) \
                   .where("nome","==",nome).stream()
    if list(existentes):
        return False, f"Tabulação '{nome}' já existe em '{departamento}'."

    db.collection("tabulacoes").document().set({
        "nome": nome,
        "departamento": departamento,
        "descricao": descricao,
        "atendentes": atendentes,          # [] = todo o departamento
        "prioridade": prioridade,
        "sla_horas": int(sla_horas),
        "criado_em": datetime.now(BRT).isoformat(),
    })
    return True, f"Tabulação '{nome}' criada em '{departamento}'."

def atualizar_tabulacao(tab_id, atendentes=None, prioridade=None, sla_horas=None):
    ref = get_db().collection("tabulacoes").document(tab_id)
    if not ref.get().exists:
        return False, "Tabulação não encontrada."
    updates = {}
    if atendentes is not None: updates["atendentes"] = atendentes
    if prioridade is not None: updates["prioridade"] = prioridade
    if sla_horas  is not None: updates["sla_horas"]  = int(sla_horas)
    if updates:
        ref.update(updates)
    return True, "Tabulação atualizada."

def deletar_tabulacao(tab_id):
    ref = get_db().collection("tabulacoes").document(tab_id)
    if not ref.get().exists:
        return False, "Tabulação não encontrada."
    ref.delete()
    return True, "Tabulação excluída."

def resolver_destinatario_ticket(departamento, tabulacao_nome=None):
    """
    Regra 1: ao abrir um ticket, decide para quem vai.
    Retorna: { departamento, atendentes[], sla_horas, prioridade }
      - tabulação COM atendentes  → só esses atendentes
      - tabulação SEM atendentes  → todos do departamento
      - sem tabulação             → todos do departamento
    """
    db = get_db()
    res = {"departamento": departamento, "atendentes": [],
           "sla_horas": 24, "prioridade": "Normal"}

    if tabulacao_nome:
        docs = db.collection("tabulacoes") \
                 .where("departamento","==",departamento) \
                 .where("nome","==",tabulacao_nome).stream()
        for d in docs:
            t = d.to_dict()
            res["atendentes"] = t.get("atendentes", [])
            res["sla_horas"]  = t.get("sla_horas", 24)
            res["prioridade"] = t.get("prioridade", "Normal")
            break

    if not res["atendentes"]:
        users = db.collection("usuarios").where("departamento","==",departamento).stream()
        res["atendentes"] = [u.to_dict().get("usuario","") for u in users]

    return res

# ── Entregas ──────────────────────────────────────────────────────
def obter_tickets_db(data_alvo: str) -> list:
    docs = get_db().collection("entregas") \
                   .where("data_entrega","==",data_alvo).stream()
    return [d.to_dict().get("payload", d.to_dict()) for d in docs]

def obter_datas_disponiveis_db() -> list:
    docs  = get_db().collection("entregas").select(["data_entrega"]).stream()
    datas: dict = {}
    for d in docs:
        v = d.to_dict().get("data_entrega")
        if v: datas[v] = datas.get(v, 0) + 1
    return [{"data":k,"total":v} for k,v in sorted(datas.items(), reverse=True)]

# ── De-Para motoristas ────────────────────────────────────────────
def obter_vinculo_db(chave: str) -> str:
    doc = get_db().collection("de_para_motoristas").document(chave).get()
    return doc.to_dict().get("nome_motorista", chave) if doc.exists else chave

def salvar_vinculo_db(chave: str, nome: str):
    get_db().collection("de_para_motoristas").document(chave).set({"nome_motorista": nome})

def deletar_rota_db(rota: str, data: str):
    db    = get_db()
    docs  = db.collection("entregas").where("rota","==",rota).where("data_entrega","==",data).stream()
    batch = db.batch()
    for d in docs: batch.delete(d.reference)
    batch.commit()

# ══════════════════════════════════════════════════════════════════
# CARTAS DE DÉBITO (RH)
# Coleções:
#   /colaboradores_base/{NOME}      → { cpf }
#   /cartas_rh/{id}                 → { id, NOME, CPF, COD_CLI, VALOR, LOJA,
#                                        DATA, MOTIVO, status, anexo_bin,
#                                        nome_arquivo, id_lote, data_criacao }
#   /lotes_rh/{id_lote}             → { id, data, total, valor_total, ids_cartas }
# ══════════════════════════════════════════════════════════════════

def obter_base_colaboradores_db() -> dict:
    """Retorna {NOME: cpf} de todos os colaboradores cadastrados."""
    docs = get_db().collection("colaboradores_base").stream()
    return {doc.id: doc.to_dict().get("cpf") for doc in docs}

def salvar_novo_colaborador_db(nome: str, cpf: str):
    nome = (nome or "").upper().strip()
    get_db().collection("colaboradores_base").document(nome).set(
        {"cpf": str(cpf).strip()}
    )

def deletar_colaborador_db(nome: str):
    get_db().collection("colaboradores_base").document(nome).delete()

def obter_cartas_db() -> list:
    """Retorna todas as cartas de débito cadastradas."""
    docs = get_db().collection("cartas_rh").stream()
    return [d.to_dict() for d in docs]

def criar_carta_db(nome, cpf, cod_cli, valor, loja, data_str, motivo) -> str:
    """Cria uma nova carta de débito e retorna o id gerado."""
    id_carta = datetime.now(BRT).strftime("%Y%m%d%H%M%S")
    get_db().collection("cartas_rh").document(id_carta).set({
        "id": id_carta,
        "NOME": nome, "CPF": cpf, "COD_CLI": cod_cli,
        "VALOR": valor, "LOJA": loja, "DATA": data_str, "MOTIVO": motivo,
        "status": "Aguardando Assinatura",
        "anexo_bin": None, "nome_arquivo": None, "id_lote": "",
        "data_criacao": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"),
    })
    return id_carta

def atualizar_carta_db(id_carta: str, **campos):
    if campos:
        get_db().collection("cartas_rh").document(id_carta).update(campos)

def registrar_assinatura_carta_db(id_carta: str, arquivo_bytes: bytes, nome_arquivo: str):
    atualizar_carta_db(
        id_carta,
        status="CARTA RECEBIDA",
        anexo_bin=arquivo_bytes,
        nome_arquivo=nome_arquivo,
    )

def deletar_carta_db(id_carta: str):
    get_db().collection("cartas_rh").document(id_carta).delete()

def reabrir_carta_db(id_carta: str):
    atualizar_carta_db(id_carta, status="Aguardando Assinatura", id_lote="")

def fechar_lote_cartas_db(cartas_prontas: list) -> str:
    """Cria o documento do lote e atualiza o status de cada carta para LOTE_FECHADO."""
    db         = get_db()
    id_lote    = datetime.now(BRT).strftime("%Y%m%d_%H%M")
    ids_cartas = [c["id"] for c in cartas_prontas]
    total_valor = sum(c.get("VALOR", 0) for c in cartas_prontas)

    db.collection("lotes_rh").document(id_lote).set({
        "id": id_lote,
        "data": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"),
        "total": len(cartas_prontas),
        "valor_total": total_valor,
        "ids_cartas": ids_cartas,
    })

    batch = db.batch()
    for id_c in ids_cartas:
        ref = db.collection("cartas_rh").document(id_c)
        batch.update(ref, {"status": "LOTE_FECHADO", "id_lote": id_lote})
    batch.commit()
    return id_lote

def listar_lotes_cartas_db() -> list:
    docs = get_db().collection("lotes_rh").stream()
    lotes = [d.to_dict() for d in docs]
    return sorted(lotes, key=lambda x: x.get("id",""), reverse=True)

def limpar_anexos_lote_db(ids_cartas: list):
    """Remove só o arquivo binário (anexo_bin) das cartas de um lote já
    fechado, mantendo todo o resto do histórico (nome, valor, status, datas
    etc.) intacto. Usado para manter o banco de dados leve, já que os
    arquivos assinados (docx/pdf/imagem) podem ser pesados e o ZIP do lote
    já foi baixado pelo usuário antes de excluir."""
    db = get_db()
    batch = db.batch()
    for id_c in ids_cartas:
        ref = db.collection("cartas_rh").document(id_c)
        batch.update(ref, {"anexo_bin": None})
    batch.commit()

# ══════════════════════════════════════════════════════════════════
# HOME — Lembretes pessoais e Projetos RACI
# Coleções:
#   /lembretes_pessoais/{id} → { id, usuario, texto, data_hora, status, criado_em,
#                                 historico_adiamentos: [{de, motivo, data_alteracao}] }
#   /raci_projetos/{id}      → { id, nome, data_criacao, pessoas[], etapas[] }
#       etapas: [{ id, nome, atividades: [{ id, atividade, prioridade,
#                   status, data_prevista, data_entregue, papeis:{pessoa:R/A/C/I} }] }]
#   /diario_bordo/{id}       → { id, usuario, atividade, data, hora, criado_em }
# ══════════════════════════════════════════════════════════════════

def listar_lembretes_pessoais(usuario: str) -> list:
    """Lembretes do usuário logado (não aparecem para outros usuários)."""
    docs = get_db().collection("lembretes_pessoais").where("usuario", "==", usuario).stream()
    return sorted([d.to_dict() for d in docs], key=lambda x: x.get("criado_em",""), reverse=True)

def criar_lembrete_pessoal_db(usuario: str, texto: str, data_hora: str, vinculo: str = "") -> str:
    """vinculo: nome do projeto RACI relacionado, ou "" para 'Pontual (fora de projetos)'."""
    ref = get_db().collection("lembretes_pessoais").document()
    ref.set({
        "id": ref.id, "usuario": usuario, "texto": texto,
        "data_hora": data_hora, "status": "Pendente", "vinculo": vinculo,
        "historico_adiamentos": [],
        "criado_em": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"),
    })
    return ref.id

def atualizar_lembrete_pessoal_db(id_lembrete: str, **campos):
    if campos:
        get_db().collection("lembretes_pessoais").document(id_lembrete).update(campos)

def adiar_lembrete_pessoal_db(id_lembrete: str, nova_data_hora: str, motivo: str):
    """
    Adia um lembrete para uma nova data/hora, exigindo o motivo do atraso.
    Mantém o lembrete como 'Pendente' e registra o histórico de adiamentos
    (data anterior, motivo e quando foi alterado) para consulta futura.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        return False, "Informe o motivo do atraso."

    ref = get_db().collection("lembretes_pessoais").document(id_lembrete)
    doc = ref.get()
    if not doc.exists:
        return False, "Lembrete não encontrado."

    d = doc.to_dict()
    historico = d.get("historico_adiamentos", [])
    historico.append({
        "de": d.get("data_hora", ""),
        "para": nova_data_hora,
        "motivo": motivo,
        "data_alteracao": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"),
    })
    ref.update({
        "data_hora": nova_data_hora,
        "status": "Pendente",
        "historico_adiamentos": historico,
    })
    return True, "Lembrete adiado e motivo registrado."

def deletar_lembrete_pessoal_db(id_lembrete: str):
    get_db().collection("lembretes_pessoais").document(id_lembrete).delete()

def listar_raci_projetos() -> list:
    """Projetos RACI — compartilhados entre todos os usuários com acesso ao Home."""
    docs = get_db().collection("raci_projetos").stream()
    return sorted([d.to_dict() for d in docs], key=lambda x: x.get("nome",""))

def criar_raci_projeto_db(nome: str, pessoas: list) -> str:
    ref = get_db().collection("raci_projetos").document()
    ref.set({
        "id": ref.id, "nome": nome, "pessoas": pessoas, "etapas": [],
        "data_criacao": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"),
    })
    return ref.id

def atualizar_raci_projeto_db(id_projeto: str, **campos):
    if campos:
        get_db().collection("raci_projetos").document(id_projeto).update(campos)

def deletar_raci_projeto_db(id_projeto: str):
    get_db().collection("raci_projetos").document(id_projeto).delete()

def salvar_arquivo_raci_db(file_id: str, conteudo: bytes) -> bool:
    """Salva um arquivo do Dossiê (Pastas) de um projeto RACI."""
    try:
        get_db().collection("raci_arquivos").document(file_id).set({"bin": conteudo})
        return True
    except Exception:
        return False

def baixar_arquivo_raci_db(file_id: str):
    doc = get_db().collection("raci_arquivos").document(file_id).get()
    return doc.to_dict().get("bin") if doc.exists else None

def deletar_arquivo_raci_db(file_id: str):
    get_db().collection("raci_arquivos").document(file_id).delete()

# ══════════════════════════════════════════════════════════════════
# DIÁRIO DE BORDO
# Coleção: /diario_bordo/{id} → { id, usuario, atividade, data, hora, criado_em }
# Regra: cada usuário só enxerga (por padrão) os próprios registros;
# passar usuario=None em listar_diario_bordo_db traz de todos (uso admin/gestão).
# ══════════════════════════════════════════════════════════════════

def _parse_data_curta(s: str):
    """Converte 'dd/mm/yyyy' em datetime, ou None se inválido/vazio."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip(), "%d/%m/%Y")
    except Exception:
        return None

def criar_registro_diario_db(usuario: str, atividade: str) -> str:
    """Registra a atividade que o usuário está executando agora, com data e hora,
    gerando um histórico consultável posteriormente (diário de bordo)."""
    ref = get_db().collection("diario_bordo").document()
    agora = datetime.now(BRT)
    ref.set({
        "id": ref.id,
        "usuario": usuario,
        "atividade": atividade,
        "data": agora.strftime("%d/%m/%Y"),
        "hora": agora.strftime("%H:%M"),
        "criado_em": agora.strftime("%d/%m/%Y %H:%M:%S"),
    })
    return ref.id

def listar_diario_bordo_db(usuario: str = None, data_ini=None, data_fim=None) -> list:
    """
    Lista os registros do diário de bordo.
    - usuario=None  → traz registros de todos os usuários (visão de gestão).
    - data_ini/data_fim: objetos date (opcional) para filtrar o período.
    """
    q = get_db().collection("diario_bordo")
    if usuario:
        q = q.where("usuario", "==", usuario)
    docs = q.stream()
    out = [d.to_dict() for d in docs]

    if data_ini or data_fim:
        filtrado = []
        for r in out:
            dt = _parse_data_curta(r.get("data", ""))
            if dt is None:
                continue
            if data_ini and dt.date() < data_ini:
                continue
            if data_fim and dt.date() > data_fim:
                continue
            filtrado.append(r)
        out = filtrado

    return sorted(out, key=lambda x: x.get("criado_em", ""), reverse=True)

def deletar_registro_diario_db(id_registro: str):
    get_db().collection("diario_bordo").document(id_registro).delete()
