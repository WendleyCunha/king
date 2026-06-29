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
    "adm":         ["rastreio","tickets","exportar"],
    "supervisor":  ["rastreio","tickets","exportar"],
    "operacional": ["rastreio"],
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
                "role":"adm","modulos":["rastreio","tickets","exportar"],
                "departamento":"Todos"}
    doc = get_db().collection("usuarios").document(usuario).get()
    if doc.exists:
        d = doc.to_dict()
        if d.get("senha_hash") == hash_senha(senha):
            return d
    return None

def criar_usuario(nome, usuario, senha, role, modulos=None, departamento=""):
    """Cria usuário. Agora aceita 'departamento' (Regra 1)."""
    if modulos is None:
        modulos = MODULOS_PADRAO.get(role, ["rastreio"])
    get_db().collection("usuarios").document(usuario).set({
        "nome": nome, "usuario": usuario,
        "senha_hash": hash_senha(senha),
        "role": role, "modulos": modulos,
        "departamento": departamento,
    })

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
