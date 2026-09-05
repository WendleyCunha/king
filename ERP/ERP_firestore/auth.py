import streamlit as st
from db import get_db, hash_senha, agora_iso

ABAS = [
    "CADASTRO", "PRODUTO", "VENDA", "AGENDAR", "ENCOMENDAR", "LOGISTICA",
    "MOTORISTA", "EMPRESA", "FINANCEIRO", "FISCAL", "RH", "DIRETORIA",
]
NIVEIS = ["NENHUM", "VISUALIZAR", "EDITAR"]


def _normalizar_login(usuario: str) -> str:
    """Mesma regra do painel: login sempre minúsculo e sem espaço nas pontas,
    porque o ID do documento no Firestore é comparado de forma EXATA."""
    return (usuario or "").strip().lower()


def _normalizar_senha(senha: str) -> str:
    return (senha or "").strip()


def permissoes_padrao_vazias() -> dict:
    return {aba: "NENHUM" for aba in ABAS}


# ── Auth ──────────────────────────────────────────────────────────
def verificar_login(usuario: str, senha: str):
    usuario_original = (usuario or "").strip()
    usuario_norm = _normalizar_login(usuario)
    senha = _normalizar_senha(senha)

    if usuario_norm == "admin" and senha == "admin123":
        return {
            "nome": "Administrador Master", "usuario": "admin",
            "permissoes": {aba: "EDITAR" for aba in ABAS}, "ativo": True,
        }

    db = get_db()
    doc = db.collection("usuarios").document(usuario_norm).get()

    if not doc.exists and usuario_original and usuario_original != usuario_norm:
        # Compatibilidade com contas criadas antes da normalização existir.
        doc = db.collection("usuarios").document(usuario_original).get()

    if doc.exists:
        d = doc.to_dict()
        if d.get("ativo", True) and d.get("senha_hash") == hash_senha(senha):
            return d
    return None


def pode_visualizar(usuario: dict, aba: str) -> bool:
    nivel = (usuario.get("permissoes") or {}).get(aba, "NENHUM")
    return nivel in ("VISUALIZAR", "EDITAR")


def pode_editar(usuario: dict, aba: str) -> bool:
    return (usuario.get("permissoes") or {}).get(aba, "NENHUM") == "EDITAR"


def criar_usuario(nome, usuario, senha, permissoes: dict = None) -> str:
    """Retorna o login FINAL (normalizado) que ficou salvo."""
    usuario = _normalizar_login(usuario)
    senha = _normalizar_senha(senha)
    if usuario == "admin":
        raise ValueError("O login 'admin' é reservado ao administrador master.")
    ref = get_db().collection("usuarios").document(usuario)
    if ref.get().exists:
        raise ValueError("Já existe um usuário com esse login.")
    ref.set({
        "nome": nome, "usuario": usuario, "senha_hash": hash_senha(senha),
        "ativo": True, "permissoes": permissoes or permissoes_padrao_vazias(),
        "criado_em": agora_iso(),
    })
    listar_usuarios.clear()
    return usuario


def definir_permissao(usuario_login: str, aba: str, nivel: str):
    if aba not in ABAS:
        raise ValueError(f"Aba inválida: {aba}")
    if nivel not in NIVEIS:
        raise ValueError(f"Nível inválido: {nivel}")
    ref = get_db().collection("usuarios").document(usuario_login)
    doc = ref.get()
    if not doc.exists:
        raise ValueError("Usuário não encontrado.")
    permissoes = doc.to_dict().get("permissoes") or permissoes_padrao_vazias()
    permissoes[aba] = nivel
    ref.update({"permissoes": permissoes})
    listar_usuarios.clear()


@st.cache_data(ttl=15, show_spinner=False)
def listar_usuarios() -> list:
    return [d.to_dict() for d in get_db().collection("usuarios").stream()]


def alterar_senha_usuario(usuario: str, senha_atual: str, nova_senha: str):
    if usuario == "admin":
        return False, "A senha do admin master não pode ser alterada aqui."
    senha_atual = _normalizar_senha(senha_atual)
    nova_senha = _normalizar_senha(nova_senha)
    ref = get_db().collection("usuarios").document(usuario)
    doc = ref.get()
    if not doc.exists:
        return False, "Usuário não encontrado."
    if doc.to_dict().get("senha_hash") != hash_senha(senha_atual):
        return False, "Senha atual incorreta."
    ref.update({"senha_hash": hash_senha(nova_senha)})
    listar_usuarios.clear()
    return True, "Senha alterada com sucesso."
