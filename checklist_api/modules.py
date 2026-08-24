"""
Módulo único: King Star — Motor de Checklists.

Consolidação de todo o backend original (app/core, app/models, app/schemas,
app/api/v1) em um único arquivo, para rodar localmente com o mínimo de
arquivos possível (main.py + requirements.txt + modules.py).

Nenhuma regra de negócio foi alterada — apenas a organização em pastas/pacotes
foi removida. A lógica, validações e comportamento são idênticos ao projeto
original em múltiplos arquivos.
"""
import os
import io
import csv
import uuid
import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import jwt
import bcrypt
from fastapi import (
    APIRouter, Depends, FastAPI, HTTPException, Query, status,
)
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import (
    Column, String, Boolean, Integer, Numeric, ForeignKey, DateTime, Date,
    Enum as SAEnum, create_engine, func,
)
# Renomeado para PG_UUID para não colidir com uuid.UUID (usado nos schemas/rotas
# como tipo de dado Python para path params e validação Pydantic).
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker, declarative_base

# ============================================================================
# CONFIGURAÇÃO (settings)
# ============================================================================
"""
Configuração central da aplicação.

Princípio de segurança (seção 13 do escopo): nenhuma credencial, senha,
token ou chave é definida diretamente no código. Tudo vem de variáveis
de ambiente. Em produção, JWT_SECRET e DATABASE_URL devem ser fornecidos
por um gerenciador de secrets (ex: variáveis de ambiente do orquestrador,
Vault, ou equivalente) — nunca commitados no repositório.
"""
class Settings:
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int

    def __init__(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL", "")
        self.jwt_secret = os.environ.get("JWT_SECRET", "")
        self.jwt_expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL não configurada. Defina a variável de ambiente antes de iniciar a aplicação."
            )
        if not self.jwt_secret:
            raise RuntimeError(
                "JWT_SECRET não configurado. Defina a variável de ambiente antes de iniciar a aplicação. "
                "Nunca use um valor default fixo em código para este segredo."
            )


settings = Settings()


# ============================================================================
# BANCO DE DADOS (engine, sessão, Base)
# ============================================================================
"""
Conexão com o banco. O schema é gerido por migrations SQL puras
(ver V1__core_schema.sql) — os models SQLAlchemy aqui apenas mapeiam
tabelas já existentes, nunca criam ou alteram schema automaticamente.
"""


engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# SEGURANÇA (hash de senha, JWT)
# ============================================================================
"""
Segurança: hashing de senha e emissão/validação de JWT.
Senha nunca é armazenada nem logada em texto puro (seção 13 e 33 do escopo).

Nota de decisão: usamos o pacote `bcrypt` diretamente, em vez de `passlib`.
O `passlib` está sem manutenção ativa e apresenta incompatibilidade conhecida
com versões recentes do `bcrypt` (autoteste interno quebra com bcrypt>=4.1).
Usar a biblioteca de baixo nível diretamente evita essa classe de problema.
"""


_BCRYPT_MAX_BYTES = 72  # limite físico do algoritmo bcrypt


def hash_password(password: str) -> str:
    senha_bytes = password.encode("utf-8")
    if len(senha_bytes) > _BCRYPT_MAX_BYTES:
        raise ValueError("Senha excede o limite de 72 bytes suportado pelo bcrypt.")
    hashed = bcrypt.hashpw(senha_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    senha_bytes = password.encode("utf-8")
    if len(senha_bytes) > _BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(senha_bytes, password_hash.encode("utf-8"))
    except ValueError:
        # hash malformado/legado — trata como não confere, não como erro 500
        return False


def create_access_token(subject: str) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Retorna o 'subject' (usuario_id como string) ou lança jwt.PyJWTError."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return payload["sub"]


# ============================================================================
# MOTOR DE REGRAS CONDICIONAIS
# ============================================================================
"""
Motor de avaliação de regras condicionais.

Lê o formato de árvore já definido em DATABASE.md e usado pelo editor de
checklist (app/api/v1/checklists.py): {"operador": "E"/"OU", "condicoes": [...]}
onde cada folha é {"item_id", "operador_comparacao", "valor"}.

O MVP da API de escrita só permite 1 condição por regra (decisão registrada),
mas este avaliador já suporta árvores aninhadas — não precisa ser reescrito
quando a interface de encadeamento avançado for liberada, só a API de escrita.
"""

_OPERADORES = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


def avaliar_condicao(condicao: Dict[str, Any], respostas_por_item: Dict[str, Any]) -> bool:
    """
    respostas_por_item: mapa {item_id (str) -> valor da resposta}.
    Item sem resposta ainda registrada é tratado como não satisfazendo condições
    de igualdade/comparação (retorna False para a folha correspondente).
    """
    if "item_id" in condicao:
        # Folha
        item_id = str(condicao["item_id"])
        operador = condicao.get("operador_comparacao", "=")
        valor_esperado = condicao.get("valor")

        if item_id not in respostas_por_item:
            return False

        valor_atual = respostas_por_item[item_id]
        comparador = _OPERADORES.get(operador)
        if comparador is None:
            return False
        try:
            return bool(comparador(valor_atual, valor_esperado))
        except TypeError:
            # Tipos não comparáveis (ex: comparar string com número) — condição não satisfeita,
            # não é erro do sistema.
            return False

    # Nó interno (E / OU)
    operador_logico = condicao.get("operador", "E")
    subcondicoes = condicao.get("condicoes", [])
    resultados = [avaliar_condicao(sub, respostas_por_item) for sub in subcondicoes]

    if operador_logico == "OU":
        return any(resultados)
    return all(resultados)  # "E" é o padrão


# ============================================================================
# MODELS (SQLAlchemy)
# ============================================================================
# --- organizacao -------------------------------------------------
class Organizacao(Base):
    __tablename__ = "organizacao"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# --- unidade -----------------------------------------------------
class Unidade(Base):
    __tablename__ = "unidade"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organizacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("organizacao.id"), nullable=False)
    nome = Column(String, nullable=False)
    tipo = Column(String, nullable=True)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)
    raio_permitido_m = Column(Integer, nullable=True)
    ativo = Column(Boolean, nullable=False, default=True)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    atualizado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# --- setor -------------------------------------------------------
class Setor(Base):
    __tablename__ = "setor"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    unidade_id = Column(PG_UUID(as_uuid=True), ForeignKey("unidade.id"), nullable=False)
    nome = Column(String, nullable=False)
    ativo = Column(Boolean, nullable=False, default=True)


# --- usuario -----------------------------------------------------
# create_type=False: o tipo enum já existe no banco (criado pela migration SQL).
# Não deixar o SQLAlchemy tentar recriá-lo.
usuario_status_enum = SAEnum(
    "ativo", "inativo", "bloqueado", name="usuario_status", create_type=False
)


class Usuario(Base):
    __tablename__ = "usuario"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    senha_hash = Column(String, nullable=False)
    status = Column(usuario_status_enum, nullable=False, default="ativo")
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    atualizado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# --- perfil ------------------------------------------------------
class Perfil(Base):
    __tablename__ = "perfil"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    permissoes = Column(JSONB, nullable=False, default=list)


# --- usuario_escopo ----------------------------------------------
class UsuarioEscopo(Base):
    __tablename__ = "usuario_escopo"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    perfil_id = Column(PG_UUID(as_uuid=True), ForeignKey("perfil.id"), nullable=False)
    unidade_id = Column(PG_UUID(as_uuid=True), ForeignKey("unidade.id"), nullable=True)
    setor_id = Column(PG_UUID(as_uuid=True), ForeignKey("setor.id"), nullable=True)


# --- checklist ---------------------------------------------------
checklist_status_enum = SAEnum("rascunho", "ativo", "arquivado", name="checklist_status", create_type=False)


class Checklist(Base):
    __tablename__ = "checklist"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    criado_por = Column(PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    unidade_id = Column(PG_UUID(as_uuid=True), ForeignKey("unidade.id"), nullable=True)
    status = Column(checklist_status_enum, nullable=False, default="rascunho")
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# --- checklist_versao --------------------------------------------
checklist_versao_status_enum = SAEnum(
    "rascunho", "publicada", "obsoleta", name="checklist_versao_status", create_type=False
)


class ChecklistVersao(Base):
    __tablename__ = "checklist_versao"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    checklist_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist.id"), nullable=False)
    numero_versao = Column(Integer, nullable=False)
    publicado_em = Column(DateTime(timezone=True), nullable=True)
    publicado_por = Column(PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True)
    status = Column(checklist_versao_status_enum, nullable=False, default="rascunho")
    snapshot_estrutura = Column(JSONB, nullable=True)
    snapshot_schema_versao = Column(Integer, nullable=True)


# --- checklist_area ----------------------------------------------
class ChecklistArea(Base):
    __tablename__ = "checklist_area"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    checklist_versao_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_versao.id"), nullable=False)
    nome = Column(String, nullable=False)
    ordem = Column(Integer, nullable=False, default=0)
    area_pai_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_area.id"), nullable=True)


# --- checklist_item ----------------------------------------------
class ChecklistItem(Base):
    __tablename__ = "checklist_item"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    area_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_area.id"), nullable=False)
    ordem = Column(Integer, nullable=False, default=0)
    titulo = Column(String, nullable=False)
    tipo_resposta = Column(PG_UUID(as_uuid=True), ForeignKey("tipo_resposta_catalogo.id"), nullable=False)
    obrigatorio = Column(Boolean, nullable=False, default=False)
    peso = Column(Numeric(6, 2), nullable=True)
    resposta_critica = Column(JSONB, nullable=True)
    evidencia_obrigatoria = Column(Boolean, nullable=False, default=False)
    comentario_obrigatorio_se_nao_conforme = Column(Boolean, nullable=False, default=False)


# --- checklist_regra ---------------------------------------------
regra_tipo_efeito_enum = SAEnum(
    "exibir", "ocultar", "exigir", "tornar_opcional", "exigir_evidencia", "disparar_nao_conformidade",
    name="regra_tipo_efeito", create_type=False,
)


class ChecklistRegra(Base):
    __tablename__ = "checklist_regra"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    checklist_versao_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_versao.id"), nullable=False)
    item_alvo_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_item.id"), nullable=False)
    tipo_efeito = Column(regra_tipo_efeito_enum, nullable=False)
    condicao = Column(JSONB, nullable=False)
    schema_versao = Column(Integer, nullable=False, default=1)


# --- tipo_resposta_catalogo --------------------------------------
class TipoRespostaCatalogo(Base):
    __tablename__ = "tipo_resposta_catalogo"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chave = Column(String, nullable=False, unique=True)
    config_schema = Column(JSONB, nullable=False, default=dict)


# --- aplicacao ---------------------------------------------------
aplicacao_status_enum = SAEnum(
    "rascunho", "em_andamento", "concluida", "cancelada", name="aplicacao_status", create_type=False
)


class Aplicacao(Base):
    __tablename__ = "aplicacao"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    checklist_versao_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_versao.id"), nullable=False)
    unidade_id = Column(PG_UUID(as_uuid=True), ForeignKey("unidade.id"), nullable=False)
    setor_id = Column(PG_UUID(as_uuid=True), ForeignKey("setor.id"), nullable=True)
    aplicador_id = Column(PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    status = Column(aplicacao_status_enum, nullable=False, default="em_andamento")
    criado_offline = Column(Boolean, nullable=False, default=False)
    iniciado_em = Column(DateTime(timezone=True), nullable=True)
    concluido_em = Column(DateTime(timezone=True), nullable=True)
    pontuacao_total = Column(Numeric(6, 2), nullable=True)
    percentual_conformidade = Column(Numeric(5, 2), nullable=True)
    sincronizado_em = Column(DateTime(timezone=True), nullable=True)


# --- resposta ----------------------------------------------------
class Resposta(Base):
    __tablename__ = "resposta"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aplicacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("aplicacao.id"), nullable=False)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_item.id"), nullable=False)
    valor = Column(JSONB, nullable=False)
    criado_offline = Column(Boolean, nullable=False, default=False)
    sincronizado_em = Column(DateTime(timezone=True), nullable=True)
    respondido_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# --- evidencia ---------------------------------------------------
evidencia_dono_tipo_enum = SAEnum(
    "APLICACAO", "RESPOSTA", "PLANO_ACAO", "NAO_CONFORMIDADE",
    name="evidencia_dono_tipo", create_type=False,
)
evidencia_tipo_enum = SAEnum(
    "foto", "video", "audio", "documento", "comentario", name="evidencia_tipo", create_type=False
)


class Evidencia(Base):
    __tablename__ = "evidencia"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dono_tipo = Column(evidencia_dono_tipo_enum, nullable=False)
    aplicacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("aplicacao.id"), nullable=True)
    resposta_id = Column(PG_UUID(as_uuid=True), ForeignKey("resposta.id"), nullable=True)
    plano_acao_id = Column(PG_UUID(as_uuid=True), ForeignKey("plano_acao.id"), nullable=True)
    nao_conformidade_id = Column(PG_UUID(as_uuid=True), ForeignKey("nao_conformidade.id"), nullable=True)
    tipo = Column(evidencia_tipo_enum, nullable=False)
    arquivo_url = Column(String, nullable=True)
    capturado_via_camera_direta = Column(Boolean, nullable=False, default=False)
    metadados = Column(JSONB, nullable=False, default=dict)
    criado_offline = Column(Boolean, nullable=False, default=False)
    sincronizado_em = Column(DateTime(timezone=True), nullable=True)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# --- nao_conformidade --------------------------------------------
nc_origem_enum = SAEnum("resposta_critica", "regra", "manual", name="nao_conformidade_origem", create_type=False)
nc_prioridade_enum = SAEnum("baixa", "media", "alta", "critica", name="nao_conformidade_prioridade", create_type=False)
nc_status_enum = SAEnum(
    "aberta", "em_tratamento", "encerrada", "contestada", name="nao_conformidade_status", create_type=False
)


class NaoConformidade(Base):
    __tablename__ = "nao_conformidade"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aplicacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("aplicacao.id"), nullable=False)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_item.id"), nullable=True)
    origem = Column(nc_origem_enum, nullable=False)
    titulo = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    prioridade = Column(nc_prioridade_enum, nullable=False, default="media")
    status = Column(nc_status_enum, nullable=False, default="aberta")
    responsavel_id = Column(PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True)
    prazo = Column(Date, nullable=True)
    criado_offline = Column(Boolean, nullable=False, default=False)
    sincronizado_em = Column(DateTime(timezone=True), nullable=True)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# --- plano_acao --------------------------------------------------
"""
Model completo de plano_acao — suporta múltiplas origens (FKs nullable +
consistência validada tanto na API quanto por CHECK constraint no banco,
conforme decisão registrada em DATABASE.md).
"""



plano_acao_origem_tipo_enum = SAEnum(
    "NAO_CONFORMIDADE", "ITEM_CHECKLIST", "AREA_CHECKLIST", "CHECKLIST", "AVULSO", "WORKFLOW",
    name="plano_acao_origem_tipo", create_type=False,
)
plano_acao_status_enum = SAEnum(
    "pendente", "em_andamento", "concluido", "atrasado", "cancelado",
    name="plano_acao_status", create_type=False,
)


class PlanoAcao(Base):
    __tablename__ = "plano_acao"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    origem_tipo = Column(plano_acao_origem_tipo_enum, nullable=False)

    nao_conformidade_id = Column(PG_UUID(as_uuid=True), ForeignKey("nao_conformidade.id"), nullable=True)
    checklist_item_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_item.id"), nullable=True)
    checklist_area_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist_area.id"), nullable=True)
    checklist_id = Column(PG_UUID(as_uuid=True), ForeignKey("checklist.id"), nullable=True)
    workflow_execucao_id = Column(PG_UUID(as_uuid=True), ForeignKey("workflow_execucao.id"), nullable=True)
    aplicacao_contexto_id = Column(PG_UUID(as_uuid=True), ForeignKey("aplicacao.id"), nullable=True)

    titulo = Column(String, nullable=False)
    what = Column(String, nullable=True)
    why = Column(String, nullable=True)
    where_ = Column("where_", String, nullable=True)
    when_ = Column("when_", String, nullable=True)
    who = Column(String, nullable=True)
    how = Column(String, nullable=True)
    how_much = Column(String, nullable=True)

    responsavel_id = Column(PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False)
    prazo = Column(Date, nullable=False)
    status = Column(plano_acao_status_enum, nullable=False, default="pendente")

    criado_offline = Column(Boolean, nullable=False, default=False)
    sincronizado_em = Column(DateTime(timezone=True), nullable=True)

    encerrado_em = Column(DateTime(timezone=True), nullable=True)
    validado_por = Column(PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# --- workflow_execucao -------------------------------------------
"""
Model stub de workflow_execucao — mapeia só o suficiente para resolver a FK
usada por plano_acao.workflow_execucao_id. O motor de workflow (Fase 4 do
roadmap original) ainda não foi projetado nem implementado; esta tabela
existe no banco apenas como referência reservada (ver DATABASE.md, seção 8).
"""




class WorkflowExecucao(Base):
    __tablename__ = "workflow_execucao"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


# ============================================================================
# DEPENDÊNCIAS DE AUTENTICAÇÃO/AUTORIZAÇÃO
# ============================================================================
"""
Dependências de autenticação e autorização.

Autorização segue o modelo definido em DATABASE.md: papel (perfil) + escopo
territorial (unidade/setor), não apenas papel global. Um usuário pode ter
múltiplos vínculos em usuario_escopo, cada um com seu próprio perfil e escopo.

Regra de escopo para leitura de unidades:
- Se QUALQUER vínculo do usuário tiver a permissão pedida com unidade_id = NULL,
  o acesso é "toda a organização" (sem filtro).
- Caso contrário, o acesso é restrito à união das unidade_id dos vínculos que
  possuem a permissão.
"""


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Usuario:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas ou expiradas.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token)
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.get(Usuario, UUID(user_id))
    if user is None or user.status != "ativo":
        raise credentials_exception
    return user


def _permissoes_do_usuario(db: Session, user: Usuario) -> List[dict]:
    """Retorna todos os vínculos (escopo + permissões do perfil) do usuário."""
    escopos = (
        db.query(UsuarioEscopo, Perfil)
        .join(Perfil, Perfil.id == UsuarioEscopo.perfil_id)
        .filter(UsuarioEscopo.usuario_id == user.id)
        .all()
    )
    return [
        {
            "unidade_id": escopo.unidade_id,
            "setor_id": escopo.setor_id,
            "permissoes": perfil.permissoes or [],
        }
        for escopo, perfil in escopos
    ]


def require_permission(permissao: str):
    """Factory de dependência: exige que o usuário tenha a permissão em pelo menos um escopo."""

    def checker(
        user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> Usuario:
        vinculos = _permissoes_do_usuario(db, user)
        tem_permissao = any(permissao in v["permissoes"] for v in vinculos)
        if not tem_permissao:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Usuário não possui a permissão requerida: {permissao}",
            )
        return user

    return checker


def get_unidades_autorizadas(
    db: Session, user: Usuario, permissao: str
) -> Optional[List[UUID]]:
    """
    Retorna None se o usuário tem acesso à organização inteira (escopo global
    com a permissão pedida), ou a lista de unidade_id às quais tem acesso.
    Lista vazia = não tem acesso a nenhuma unidade com essa permissão.
    """
    vinculos = _permissoes_do_usuario(db, user)
    unidades: List[UUID] = []
    for v in vinculos:
        if permissao not in v["permissoes"]:
            continue
        if v["unidade_id"] is None:
            return None  # escopo global — acesso a tudo
        unidades.append(v["unidade_id"])
    return unidades


# ============================================================================
# SCHEMAS (Pydantic)
# ============================================================================
# --- auth --------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- usuario -----------------------------------------------------
class UsuarioCreate(BaseModel):
    nome: str = Field(min_length=1)
    email: EmailStr
    senha: str = Field(min_length=8)


class UsuarioOut(BaseModel):
    id: UUID
    nome: str
    email: EmailStr
    status: str

    model_config = ConfigDict(from_attributes=True)


# --- unidade -----------------------------------------------------
class UnidadeCreate(BaseModel):
    organizacao_id: UUID
    nome: str = Field(min_length=1)
    tipo: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    raio_permitido_m: Optional[int] = None


class UnidadeOut(BaseModel):
    id: UUID
    organizacao_id: UUID
    nome: str
    tipo: Optional[str]
    ativo: bool

    model_config = ConfigDict(from_attributes=True)


# --- setor -------------------------------------------------------
class SetorCreate(BaseModel):
    unidade_id: UUID
    nome: str = Field(min_length=1)


class SetorOut(BaseModel):
    id: UUID
    unidade_id: UUID
    nome: str
    ativo: bool

    model_config = ConfigDict(from_attributes=True)


# --- checklist ---------------------------------------------------
# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------
class ChecklistCreate(BaseModel):
    nome: str = Field(min_length=1)
    descricao: Optional[str] = None
    unidade_id: Optional[UUID] = None  # None = template organizacional (visível a todos)


class ChecklistOut(BaseModel):
    id: UUID
    nome: str
    descricao: Optional[str]
    unidade_id: Optional[UUID]
    status: str
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Versão
# ---------------------------------------------------------------------------
class ChecklistVersaoOut(BaseModel):
    id: UUID
    checklist_id: UUID
    numero_versao: int
    status: str
    snapshot_estrutura: Optional[Any] = None
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Área
# ---------------------------------------------------------------------------
class AreaCreate(BaseModel):
    nome: str = Field(min_length=1)
    ordem: int = 0
    area_pai_id: Optional[UUID] = None


class AreaOut(BaseModel):
    id: UUID
    checklist_versao_id: UUID
    nome: str
    ordem: int
    area_pai_id: Optional[UUID]
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------
class ItemCreate(BaseModel):
    area_id: UUID
    titulo: str = Field(min_length=1)
    tipo_resposta_chave: str  # ex: "sim_nao" — resolvido para UUID no backend
    ordem: int = 0
    obrigatorio: bool = False
    peso: Optional[float] = None
    resposta_critica: Optional[Any] = None
    evidencia_obrigatoria: bool = False
    comentario_obrigatorio_se_nao_conforme: bool = False


class ItemOut(BaseModel):
    id: UUID
    area_id: UUID
    titulo: str
    ordem: int
    obrigatorio: bool
    evidencia_obrigatoria: bool
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Regra condicional — MVP: 1 condição por vez (decisão registrada).
# O JSON persistido já usa o formato de árvore (compatível com evolução futura),
# mas a API só aceita uma condição simples nesta fase.
# ---------------------------------------------------------------------------
class RegraCreate(BaseModel):
    item_alvo_id: UUID
    tipo_efeito: str  # exibir | ocultar | exigir | tornar_opcional | exigir_evidencia | disparar_nao_conformidade
    item_condicao_id: UUID  # item cuja resposta determina a condição
    operador_comparacao: str = "="  # "=", "!=", ">", "<", ">=", "<="
    valor: Any


class RegraOut(BaseModel):
    id: UUID
    checklist_versao_id: UUID
    item_alvo_id: UUID
    tipo_efeito: str
    condicao: Any
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Tipo de resposta (catálogo, somente leitura por esta API por enquanto)
# ---------------------------------------------------------------------------
class TipoRespostaOut(BaseModel):
    id: UUID
    chave: str
    model_config = ConfigDict(from_attributes=True)


# --- aplicacao ---------------------------------------------------
class AplicacaoCreate(BaseModel):
    checklist_id: UUID
    unidade_id: UUID
    setor_id: Optional[UUID] = None
    criado_offline: bool = False


class AplicacaoOut(BaseModel):
    id: UUID
    checklist_versao_id: UUID
    unidade_id: UUID
    setor_id: Optional[UUID]
    aplicador_id: UUID
    status: str
    pontuacao_total: Optional[float]
    percentual_conformidade: Optional[float]
    model_config = ConfigDict(from_attributes=True)


class RespostaCreate(BaseModel):
    item_id: UUID
    valor: Any
    criado_offline: bool = False


class RespostaOut(BaseModel):
    id: UUID
    aplicacao_id: UUID
    item_id: UUID
    valor: Any
    model_config = ConfigDict(from_attributes=True)


class EvidenciaCreate(BaseModel):
    resposta_id: Optional[UUID] = None  # None = evidência geral da aplicação
    tipo: str  # foto | video | audio | documento | comentario
    arquivo_url: Optional[str] = None
    capturado_via_camera_direta: bool = False
    criado_offline: bool = False


class EvidenciaOut(BaseModel):
    id: UUID
    dono_tipo: str
    aplicacao_id: Optional[UUID]
    resposta_id: Optional[UUID]
    plano_acao_id: Optional[UUID] = None
    tipo: str
    arquivo_url: Optional[str]
    model_config = ConfigDict(from_attributes=True)


class NaoConformidadeOut(BaseModel):
    id: UUID
    aplicacao_id: UUID
    item_id: Optional[UUID]
    origem: str
    titulo: str
    prioridade: str
    status: str
    model_config = ConfigDict(from_attributes=True)


class AplicacaoDetalheOut(BaseModel):
    aplicacao: AplicacaoOut
    respostas: List[RespostaOut]
    evidencias: List[EvidenciaOut]
    nao_conformidades: List[NaoConformidadeOut]


# --- plano_acao --------------------------------------------------
# Mapa origem_tipo -> nome do campo de FK correspondente. Replica exatamente
# a lógica do CHECK constraint chk_plano_acao_origem_consistente do banco
# (ver V1__core_schema.sql), para dar erro 400 amigável na API em vez de
# deixar a validação estourar como erro 500 vindo do banco.
_CAMPO_FK_POR_ORIGEM = {
    "NAO_CONFORMIDADE": "nao_conformidade_id",
    "ITEM_CHECKLIST": "checklist_item_id",
    "AREA_CHECKLIST": "checklist_area_id",
    "CHECKLIST": "checklist_id",
    "WORKFLOW": "workflow_execucao_id",
    "AVULSO": None,
}
_TODAS_AS_FKS_DE_ORIGEM = ["nao_conformidade_id", "checklist_item_id", "checklist_area_id", "checklist_id", "workflow_execucao_id"]


class PlanoAcaoCreate(BaseModel):
    origem_tipo: str
    nao_conformidade_id: Optional[UUID] = None
    checklist_item_id: Optional[UUID] = None
    checklist_area_id: Optional[UUID] = None
    checklist_id: Optional[UUID] = None
    workflow_execucao_id: Optional[UUID] = None
    aplicacao_contexto_id: Optional[UUID] = None  # contexto técnico, não é a origem conceitual

    titulo: str = Field(min_length=1)
    what: Optional[str] = None
    why: Optional[str] = None
    where_: Optional[str] = None
    when_: Optional[str] = None
    who: Optional[str] = None
    how: Optional[str] = None
    how_much: Optional[str] = None

    responsavel_id: UUID
    prazo: datetime.date
    criado_offline: bool = False

    @model_validator(mode="after")
    def validar_consistencia_origem(self):
        if self.origem_tipo not in _CAMPO_FK_POR_ORIGEM:
            raise ValueError(f"origem_tipo inválido: {self.origem_tipo}")

        campo_esperado = _CAMPO_FK_POR_ORIGEM[self.origem_tipo]
        for campo in _TODAS_AS_FKS_DE_ORIGEM:
            valor = getattr(self, campo)
            deveria_estar_preenchido = (campo == campo_esperado)
            if deveria_estar_preenchido and valor is None:
                raise ValueError(f"origem_tipo='{self.origem_tipo}' exige o campo '{campo}' preenchido.")
            if not deveria_estar_preenchido and valor is not None:
                raise ValueError(f"origem_tipo='{self.origem_tipo}' não deve ter o campo '{campo}' preenchido.")
        return self


class PlanoAcaoStatusUpdate(BaseModel):
    status: str  # pendente | em_andamento | concluido | atrasado | cancelado


class PlanoAcaoOut(BaseModel):
    id: UUID
    origem_tipo: str
    nao_conformidade_id: Optional[UUID]
    checklist_item_id: Optional[UUID]
    checklist_area_id: Optional[UUID]
    checklist_id: Optional[UUID]
    workflow_execucao_id: Optional[UUID]
    aplicacao_contexto_id: Optional[UUID]
    titulo: str
    responsavel_id: UUID
    prazo: datetime.date
    status: str
    encerrado_em: Optional[datetime.datetime]
    model_config = ConfigDict(from_attributes=True)


# --- dashboard ---------------------------------------------------
class ResumoAplicacoes(BaseModel):
    total: int
    por_status: Dict[str, int]
    percentual_conformidade_medio: Optional[float]
    periodo_inicio: Optional[datetime.date]
    periodo_fim: Optional[datetime.date]


class ItemReincidente(BaseModel):
    item_id: str
    titulo_item: str
    ocorrencias: int


class ResumoNaoConformidades(BaseModel):
    total: int
    por_status: Dict[str, int]
    por_prioridade: Dict[str, int]
    itens_reincidentes: List[ItemReincidente]


class ResumoPlanosAcao(BaseModel):
    total: int
    por_status: Dict[str, int]
    atrasados: int


# ============================================================================
# ROTAS (FastAPI routers)
# ============================================================================
# --- auth.py -----------------------------------------------------
auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == form_data.username).first()

    # Mensagem genérica de propósito — não revelar se o e-mail existe ou não.
    credenciais_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="E-mail ou senha inválidos.",
    )

    if user is None or not verify_password(form_data.password, user.senha_hash):
        raise credenciais_invalidas

    if user.status != "ativo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo ou bloqueado.",
        )

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


# --- usuarios.py -------------------------------------------------
usuarios_router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@usuarios_router.post("", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def criar_usuario(
    payload: UsuarioCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_permission("usuario.gerenciar")),
):
    usuario = Usuario(
        nome=payload.nome,
        email=payload.email,
        senha_hash=hash_password(payload.senha),
    )
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado.")
    db.refresh(usuario)
    return usuario


@usuarios_router.get("", response_model=List[UsuarioOut])
def listar_usuarios(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_permission("usuario.visualizar")),
):
    return db.query(Usuario).order_by(Usuario.nome).all()


@usuarios_router.get("/me", response_model=UsuarioOut)
def meu_usuario(current_user: Usuario = Depends(get_current_user)):
    return current_user


@usuarios_router.get("/{usuario_id}", response_model=UsuarioOut)
def obter_usuario(
    usuario_id: UUID,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_permission("usuario.visualizar")),
):
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    return usuario


# --- unidades.py -------------------------------------------------
unidades_router = APIRouter(prefix="/unidades", tags=["unidades"])


@unidades_router.post("", response_model=UnidadeOut, status_code=status.HTTP_201_CREATED)
def criar_unidade(
    payload: UnidadeCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_permission("unidade.gerenciar")),
):
    unidade = Unidade(**payload.model_dump())
    db.add(unidade)
    db.commit()
    db.refresh(unidade)
    return unidade


@unidades_router.get("", response_model=List[UnidadeOut])
def listar_unidades(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("unidade.visualizar")),
):
    unidades_autorizadas = get_unidades_autorizadas(db, user, "unidade.visualizar")
    query = db.query(Unidade)
    if unidades_autorizadas is not None:
        # Não é escopo global — restringe às unidades do vínculo do usuário.
        if not unidades_autorizadas:
            return []
        query = query.filter(Unidade.id.in_(unidades_autorizadas))
    return query.order_by(Unidade.nome).all()


@unidades_router.get("/{unidade_id}", response_model=UnidadeOut)
def obter_unidade(
    unidade_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("unidade.visualizar")),
):
    unidades_autorizadas = get_unidades_autorizadas(db, user, "unidade.visualizar")
    if unidades_autorizadas is not None and unidade_id not in unidades_autorizadas:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a esta unidade.")

    unidade = db.get(Unidade, unidade_id)
    if unidade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unidade não encontrada.")
    return unidade


# --- setores.py --------------------------------------------------
setores_router = APIRouter(prefix="/setores", tags=["setores"])


@setores_router.post("", response_model=SetorOut, status_code=status.HTTP_201_CREATED)
def criar_setor(
    payload: SetorCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_permission("unidade.gerenciar")),
):
    setor = Setor(**payload.model_dump())
    db.add(setor)
    db.commit()
    db.refresh(setor)
    return setor


@setores_router.get("", response_model=List[SetorOut])
def listar_setores(
    unidade_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("unidade.visualizar")),
):
    unidades_autorizadas = get_unidades_autorizadas(db, user, "unidade.visualizar")
    query = db.query(Setor)

    if unidade_id is not None:
        if unidades_autorizadas is not None and unidade_id not in unidades_autorizadas:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a esta unidade.")
        query = query.filter(Setor.unidade_id == unidade_id)
    elif unidades_autorizadas is not None:
        if not unidades_autorizadas:
            return []
        query = query.filter(Setor.unidade_id.in_(unidades_autorizadas))

    return query.order_by(Setor.nome).all()


# --- checklists.py -----------------------------------------------
checklists_router = APIRouter(prefix="/checklists", tags=["checklists"])

SNAPSHOT_SCHEMA_VERSAO_ATUAL = 1
CONDICAO_SCHEMA_VERSAO_ATUAL = 1


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _get_checklist_ou_404(db: Session, checklist_id: UUID) -> Checklist:
    checklist = db.get(Checklist, checklist_id)
    if checklist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist não encontrado.")
    return checklist


def _checar_acesso_unidade(db: Session, user: Usuario, unidade_id: Optional[UUID], permissao: str):
    """Checklists de template (unidade_id=None) são visíveis a quem tem a permissão,
    independente de escopo. Checklists de unidade exigem a unidade estar no escopo."""
    if unidade_id is None:
        return
    autorizadas = get_unidades_autorizadas(db, user, permissao)
    if autorizadas is not None and unidade_id not in autorizadas:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a esta unidade.")


def _get_versao_rascunho_ou_erro(db: Session, checklist_id: UUID) -> ChecklistVersao:
    """Retorna a versão em rascunho do checklist. Erra explicitamente se não houver
    nenhuma — é assim que a API impede edição de versão já publicada/obsoleta."""
    versao = (
        db.query(ChecklistVersao)
        .filter(ChecklistVersao.checklist_id == checklist_id, ChecklistVersao.status == "rascunho")
        .order_by(ChecklistVersao.numero_versao.desc())
        .first()
    )
    if versao is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este checklist não possui versão em rascunho editável. "
                   "Crie uma nova versão (POST /checklists/{id}/versoes) antes de editar.",
        )
    return versao


# ---------------------------------------------------------------------------
# Checklist (cabeçalho)
# ---------------------------------------------------------------------------
@checklists_router.post("", response_model=ChecklistOut, status_code=status.HTTP_201_CREATED)
def criar_checklist(
    payload: ChecklistCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.criar")),
):
    _checar_acesso_unidade(db, user, payload.unidade_id, "checklist.criar")

    checklist = Checklist(
        nome=payload.nome,
        descricao=payload.descricao,
        criado_por=user.id,
        unidade_id=payload.unidade_id,
        status="rascunho",
    )
    db.add(checklist)
    db.flush()  # obtém checklist.id sem commitar ainda

    versao_inicial = ChecklistVersao(
        checklist_id=checklist.id,
        numero_versao=1,
        status="rascunho",
    )
    db.add(versao_inicial)
    db.commit()
    db.refresh(checklist)
    return checklist


@checklists_router.get("", response_model=List[ChecklistOut])
def listar_checklists(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.visualizar")),
):
    autorizadas = get_unidades_autorizadas(db, user, "checklist.visualizar")
    query = db.query(Checklist)
    if autorizadas is not None:
        # Vê templates (unidade_id NULL) + checklists das unidades autorizadas
        query = query.filter(
            (Checklist.unidade_id.is_(None)) | (Checklist.unidade_id.in_(autorizadas))
        )
    return query.order_by(Checklist.nome).all()


@checklists_router.get("/{checklist_id}", response_model=ChecklistOut)
def obter_checklist(
    checklist_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.visualizar")),
):
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.visualizar")
    return checklist


@checklists_router.get("/{checklist_id}/versoes", response_model=List[ChecklistVersaoOut])
def listar_versoes(
    checklist_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.visualizar")),
):
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.visualizar")
    return (
        db.query(ChecklistVersao)
        .filter(ChecklistVersao.checklist_id == checklist_id)
        .order_by(ChecklistVersao.numero_versao)
        .all()
    )


# ---------------------------------------------------------------------------
# Nova versão (clona estrutura da última versão para uma nova em rascunho)
# ---------------------------------------------------------------------------
@checklists_router.post("/{checklist_id}/versoes", response_model=ChecklistVersaoOut, status_code=status.HTTP_201_CREATED)
def criar_nova_versao(
    checklist_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.criar")),
):
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.criar")

    existe_rascunho = (
        db.query(ChecklistVersao)
        .filter(ChecklistVersao.checklist_id == checklist_id, ChecklistVersao.status == "rascunho")
        .first()
    )
    if existe_rascunho is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma versão em rascunho para este checklist. Finalize-a antes de criar outra.",
        )

    ultima_versao = (
        db.query(ChecklistVersao)
        .filter(ChecklistVersao.checklist_id == checklist_id)
        .order_by(ChecklistVersao.numero_versao.desc())
        .first()
    )
    novo_numero = (ultima_versao.numero_versao + 1) if ultima_versao else 1

    nova_versao = ChecklistVersao(checklist_id=checklist_id, numero_versao=novo_numero, status="rascunho")
    db.add(nova_versao)
    db.flush()

    # Clona áreas e itens da última versão (se existir), para edição incremental.
    if ultima_versao is not None:
        areas_antigas = db.query(ChecklistArea).filter(ChecklistArea.checklist_versao_id == ultima_versao.id).all()
        mapa_area_antiga_para_nova = {}
        for area_antiga in areas_antigas:
            nova_area = ChecklistArea(
                checklist_versao_id=nova_versao.id,
                nome=area_antiga.nome,
                ordem=area_antiga.ordem,
                area_pai_id=None,  # resolvido em segunda passada se houver hierarquia
            )
            db.add(nova_area)
            db.flush()
            mapa_area_antiga_para_nova[area_antiga.id] = nova_area.id

        for area_antiga in areas_antigas:
            if area_antiga.area_pai_id is not None:
                nova_area_id = mapa_area_antiga_para_nova[area_antiga.id]
                nova_area = db.get(ChecklistArea, nova_area_id)
                nova_area.area_pai_id = mapa_area_antiga_para_nova.get(area_antiga.area_pai_id)

            itens_antigos = db.query(ChecklistItem).filter(ChecklistItem.area_id == area_antiga.id).all()
            for item_antigo in itens_antigos:
                novo_item = ChecklistItem(
                    area_id=mapa_area_antiga_para_nova[area_antiga.id],
                    ordem=item_antigo.ordem,
                    titulo=item_antigo.titulo,
                    tipo_resposta=item_antigo.tipo_resposta,
                    obrigatorio=item_antigo.obrigatorio,
                    peso=item_antigo.peso,
                    resposta_critica=item_antigo.resposta_critica,
                    evidencia_obrigatoria=item_antigo.evidencia_obrigatoria,
                    comentario_obrigatorio_se_nao_conforme=item_antigo.comentario_obrigatorio_se_nao_conforme,
                )
                db.add(novo_item)
        # Nota: regras condicionais não são clonadas automaticamente nesta versão do
        # endpoint — dependem de IDs de item que mudam na clonagem. Fica registrado
        # como limitação conhecida (ver API.md), não como omissão silenciosa.

    db.commit()
    db.refresh(nova_versao)
    return nova_versao


# ---------------------------------------------------------------------------
# Área
# ---------------------------------------------------------------------------
@checklists_router.post("/{checklist_id}/areas", response_model=AreaOut, status_code=status.HTTP_201_CREATED)
def criar_area(
    checklist_id: UUID,
    payload: AreaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.criar")),
):
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.criar")
    versao = _get_versao_rascunho_ou_erro(db, checklist_id)

    area = ChecklistArea(
        checklist_versao_id=versao.id,
        nome=payload.nome,
        ordem=payload.ordem,
        area_pai_id=payload.area_pai_id,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    return area


@checklists_router.get("/{checklist_id}/areas", response_model=List[AreaOut])
def listar_areas(
    checklist_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.visualizar")),
):
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.visualizar")
    versao = (
        db.query(ChecklistVersao)
        .filter(ChecklistVersao.checklist_id == checklist_id)
        .order_by(ChecklistVersao.numero_versao.desc())
        .first()
    )
    if versao is None:
        return []
    return (
        db.query(ChecklistArea)
        .filter(ChecklistArea.checklist_versao_id == versao.id)
        .order_by(ChecklistArea.ordem)
        .all()
    )


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------
@checklists_router.post("/{checklist_id}/itens", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def criar_item(
    checklist_id: UUID,
    payload: ItemCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.criar")),
):
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.criar")
    versao = _get_versao_rascunho_ou_erro(db, checklist_id)

    area = db.get(ChecklistArea, payload.area_id)
    if area is None or area.checklist_versao_id != versao.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Área inválida: não pertence à versão em rascunho deste checklist.",
        )

    tipo = db.query(TipoRespostaCatalogo).filter(TipoRespostaCatalogo.chave == payload.tipo_resposta_chave).first()
    if tipo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de resposta desconhecido: '{payload.tipo_resposta_chave}'. Consulte GET /tipos-resposta.",
        )

    item = ChecklistItem(
        area_id=payload.area_id,
        ordem=payload.ordem,
        titulo=payload.titulo,
        tipo_resposta=tipo.id,
        obrigatorio=payload.obrigatorio,
        peso=payload.peso,
        resposta_critica=payload.resposta_critica,
        evidencia_obrigatoria=payload.evidencia_obrigatoria,
        comentario_obrigatorio_se_nao_conforme=payload.comentario_obrigatorio_se_nao_conforme,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Regra condicional — MVP: 1 condição (decisão registrada em DATABASE.md).
# Persiste já no formato de árvore para compatibilidade futura com encadeamento.
# ---------------------------------------------------------------------------
@checklists_router.post("/{checklist_id}/regras", response_model=RegraOut, status_code=status.HTTP_201_CREATED)
def criar_regra(
    checklist_id: UUID,
    payload: RegraCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.criar")),
):
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.criar")
    versao = _get_versao_rascunho_ou_erro(db, checklist_id)

    def _pertence_a_versao(item_id: UUID) -> bool:
        item = db.get(ChecklistItem, item_id)
        if item is None:
            return False
        area = db.get(ChecklistArea, item.area_id)
        return area is not None and area.checklist_versao_id == versao.id

    if not _pertence_a_versao(payload.item_alvo_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_alvo_id inválido para esta versão.")
    if not _pertence_a_versao(payload.item_condicao_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_condicao_id inválido para esta versão.")

    condicao_json = {
        "operador": "E",
        "condicoes": [
            {
                "item_id": str(payload.item_condicao_id),
                "operador_comparacao": payload.operador_comparacao,
                "valor": payload.valor,
            }
        ],
    }

    regra = ChecklistRegra(
        checklist_versao_id=versao.id,
        item_alvo_id=payload.item_alvo_id,
        tipo_efeito=payload.tipo_efeito,
        condicao=condicao_json,
        schema_versao=CONDICAO_SCHEMA_VERSAO_ATUAL,
    )
    db.add(regra)
    db.commit()
    db.refresh(regra)
    return regra


# ---------------------------------------------------------------------------
# Publicação — gera o snapshot imutável
# ---------------------------------------------------------------------------
@checklists_router.post("/{checklist_id}/publicar", response_model=ChecklistVersaoOut)
def publicar_checklist(
    checklist_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.publicar")),
):
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.publicar")
    versao = _get_versao_rascunho_ou_erro(db, checklist_id)

    areas = (
        db.query(ChecklistArea)
        .filter(ChecklistArea.checklist_versao_id == versao.id)
        .order_by(ChecklistArea.ordem)
        .all()
    )
    if not areas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível publicar um checklist sem nenhuma área/item.",
        )

    snapshot_areas = []
    total_itens = 0
    for area in areas:
        itens = db.query(ChecklistItem).filter(ChecklistItem.area_id == area.id).order_by(ChecklistItem.ordem).all()
        total_itens += len(itens)
        snapshot_itens = []
        for item in itens:
            tipo = db.get(TipoRespostaCatalogo, item.tipo_resposta)
            regras_do_item = db.query(ChecklistRegra).filter(ChecklistRegra.item_alvo_id == item.id).all()
            snapshot_itens.append({
                "id": str(item.id),
                "titulo": item.titulo,
                "ordem": item.ordem,
                "tipo_resposta": tipo.chave if tipo else None,
                "obrigatorio": item.obrigatorio,
                "peso": float(item.peso) if item.peso is not None else None,
                "evidencia_obrigatoria": item.evidencia_obrigatoria,
                "comentario_obrigatorio_se_nao_conforme": item.comentario_obrigatorio_se_nao_conforme,
                "regras": [
                    {"tipo_efeito": r.tipo_efeito, "condicao": r.condicao, "schema_versao": r.schema_versao}
                    for r in regras_do_item
                ],
            })
        snapshot_areas.append({
            "id": str(area.id),
            "nome": area.nome,
            "ordem": area.ordem,
            "area_pai_id": str(area.area_pai_id) if area.area_pai_id else None,
            "itens": snapshot_itens,
        })

    if total_itens == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível publicar um checklist com áreas vazias (sem nenhum item).",
        )

    versao.snapshot_estrutura = {"areas": snapshot_areas}
    versao.snapshot_schema_versao = SNAPSHOT_SCHEMA_VERSAO_ATUAL
    versao.status = "publicada"
    from datetime import datetime, timezone
    versao.publicado_em = datetime.now(timezone.utc)
    versao.publicado_por = user.id

    checklist.status = "ativo"

    # O UNIQUE INDEX parcial (uq_checklist_versao_publicada) garante, em nível de
    # banco, que não haja duas versões "publicada" simultâneas — se por algum motivo
    # de concorrência isso for violado, o commit falha e a IntegrityError sobe como 500,
    # o que é aceitável aqui (cenário de corrida extremamente improvável neste fluxo).
    db.commit()
    db.refresh(versao)
    return versao


@checklists_router.get("/{checklist_id}/versao-publicada", response_model=ChecklistVersaoOut)
def obter_versao_publicada(
    checklist_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("checklist.visualizar")),
):
    """Retorna a versão publicada ativa (com snapshot_estrutura), usada tanto pela
    aplicação de campo (download para execução/offline) quanto pelo módulo de
    execução internamente."""
    checklist = _get_checklist_ou_404(db, checklist_id)
    _checar_acesso_unidade(db, user, checklist.unidade_id, "checklist.visualizar")

    versao = (
        db.query(ChecklistVersao)
        .filter(ChecklistVersao.checklist_id == checklist_id, ChecklistVersao.status == "publicada")
        .first()
    )
    if versao is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhuma versão publicada para este checklist.")
    return versao


# ---------------------------------------------------------------------------
# Catálogo de tipos de resposta (somente leitura nesta fase)
# ---------------------------------------------------------------------------
tipos_router = APIRouter(prefix="/tipos-resposta", tags=["tipos-resposta"])


@tipos_router.get("", response_model=List[TipoRespostaOut])
def listar_tipos_resposta(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_permission("checklist.visualizar")),
):
    return db.query(TipoRespostaCatalogo).order_by(TipoRespostaCatalogo.chave).all()


# --- aplicacoes.py -----------------------------------------------
aplicacoes_router = APIRouter(prefix="/aplicacoes", tags=["aplicacoes"])


def _get_aplicacao_ou_404(db: Session, aplicacao_id: UUID) -> Aplicacao:
    aplicacao = db.get(Aplicacao, aplicacao_id)
    if aplicacao is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aplicação não encontrada.")
    return aplicacao


def _checar_acesso(db: Session, user: Usuario, unidade_id: UUID, permissao: str):
    autorizadas = get_unidades_autorizadas(db, user, permissao)
    if autorizadas is not None and unidade_id not in autorizadas:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a esta unidade.")


def _itens_da_versao(db: Session, checklist_versao_id: UUID) -> List[ChecklistItem]:
    return (
        db.query(ChecklistItem)
        .join(ChecklistArea, ChecklistArea.id == ChecklistItem.area_id)
        .filter(ChecklistArea.checklist_versao_id == checklist_versao_id)
        .all()
    )


# ---------------------------------------------------------------------------
# Criar aplicação
# ---------------------------------------------------------------------------
@aplicacoes_router.post("", response_model=AplicacaoOut, status_code=status.HTTP_201_CREATED)
def iniciar_aplicacao(
    payload: AplicacaoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("aplicacao.criar")),
):
    _checar_acesso(db, user, payload.unidade_id, "aplicacao.criar")

    versao_publicada = (
        db.query(ChecklistVersao)
        .filter(ChecklistVersao.checklist_id == payload.checklist_id, ChecklistVersao.status == "publicada")
        .first()
    )
    if versao_publicada is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este checklist não possui versão publicada. Não é possível iniciar uma aplicação.",
        )

    aplicacao = Aplicacao(
        checklist_versao_id=versao_publicada.id,
        unidade_id=payload.unidade_id,
        setor_id=payload.setor_id,
        aplicador_id=user.id,
        status="em_andamento",
        criado_offline=payload.criado_offline,
        iniciado_em=datetime.datetime.now(datetime.timezone.utc),
        sincronizado_em=None if payload.criado_offline else datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(aplicacao)
    db.commit()
    db.refresh(aplicacao)
    return aplicacao


@aplicacoes_router.get("/{aplicacao_id}", response_model=AplicacaoDetalheOut)
def obter_aplicacao(
    aplicacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("aplicacao.visualizar")),
):
    aplicacao = _get_aplicacao_ou_404(db, aplicacao_id)
    _checar_acesso(db, user, aplicacao.unidade_id, "aplicacao.visualizar")

    respostas = db.query(Resposta).filter(Resposta.aplicacao_id == aplicacao_id).all()
    evidencias = db.query(Evidencia).filter(Evidencia.aplicacao_id == aplicacao_id).all()
    nao_conformidades = db.query(NaoConformidade).filter(NaoConformidade.aplicacao_id == aplicacao_id).all()

    return AplicacaoDetalheOut(
        aplicacao=aplicacao,
        respostas=respostas,
        evidencias=evidencias,
        nao_conformidades=nao_conformidades,
    )


# ---------------------------------------------------------------------------
# Responder item
# ---------------------------------------------------------------------------
@aplicacoes_router.post("/{aplicacao_id}/respostas", response_model=RespostaOut, status_code=status.HTTP_201_CREATED)
def responder_item(
    aplicacao_id: UUID,
    payload: RespostaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("aplicacao.executar")),
):
    aplicacao = _get_aplicacao_ou_404(db, aplicacao_id)
    _checar_acesso(db, user, aplicacao.unidade_id, "aplicacao.executar")

    if aplicacao.status not in ("em_andamento", "rascunho"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Não é possível responder: aplicação está com status '{aplicacao.status}'.",
        )

    item = db.get(ChecklistItem, payload.item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_id inválido.")

    area = db.get(ChecklistArea, item.area_id)
    if area is None or area.checklist_versao_id != aplicacao.checklist_versao_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este item não pertence à versão do checklist desta aplicação.",
        )

    # Upsert: se já existe resposta para este item nesta aplicação, atualiza (permite correção).
    resposta_existente = (
        db.query(Resposta)
        .filter(Resposta.aplicacao_id == aplicacao_id, Resposta.item_id == payload.item_id)
        .first()
    )
    if resposta_existente is not None:
        resposta_existente.valor = payload.valor
        resposta_existente.criado_offline = payload.criado_offline
        resposta = resposta_existente
    else:
        resposta = Resposta(
            aplicacao_id=aplicacao_id,
            item_id=payload.item_id,
            valor=payload.valor,
            criado_offline=payload.criado_offline,
            sincronizado_em=None if payload.criado_offline else datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(resposta)

    # Não conformidade automática: se a resposta bate com resposta_critica do item.
    if item.resposta_critica is not None and payload.valor == item.resposta_critica:
        ja_existe_nc = (
            db.query(NaoConformidade)
            .filter(NaoConformidade.aplicacao_id == aplicacao_id, NaoConformidade.item_id == item.id)
            .first()
        )
        if ja_existe_nc is None:
            nc = NaoConformidade(
                aplicacao_id=aplicacao_id,
                item_id=item.id,
                origem="resposta_critica",
                titulo=f"Não conformidade: {item.titulo}",
                prioridade="media",
                status="aberta",
            )
            db.add(nc)

    db.commit()
    db.refresh(resposta)
    return resposta


# ---------------------------------------------------------------------------
# Evidência
# ---------------------------------------------------------------------------
@aplicacoes_router.post("/{aplicacao_id}/evidencias", response_model=EvidenciaOut, status_code=status.HTTP_201_CREATED)
def adicionar_evidencia(
    aplicacao_id: UUID,
    payload: EvidenciaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("aplicacao.executar")),
):
    aplicacao = _get_aplicacao_ou_404(db, aplicacao_id)
    _checar_acesso(db, user, aplicacao.unidade_id, "aplicacao.executar")

    if payload.resposta_id is not None:
        resposta = db.get(Resposta, payload.resposta_id)
        if resposta is None or resposta.aplicacao_id != aplicacao_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="resposta_id inválido para esta aplicação.")
        evidencia = Evidencia(
            dono_tipo="RESPOSTA",
            resposta_id=payload.resposta_id,
            tipo=payload.tipo,
            arquivo_url=payload.arquivo_url,
            capturado_via_camera_direta=payload.capturado_via_camera_direta,
            criado_offline=payload.criado_offline,
            sincronizado_em=None if payload.criado_offline else datetime.datetime.now(datetime.timezone.utc),
        )
    else:
        evidencia = Evidencia(
            dono_tipo="APLICACAO",
            aplicacao_id=aplicacao_id,
            tipo=payload.tipo,
            arquivo_url=payload.arquivo_url,
            capturado_via_camera_direta=payload.capturado_via_camera_direta,
            criado_offline=payload.criado_offline,
            sincronizado_em=None if payload.criado_offline else datetime.datetime.now(datetime.timezone.utc),
        )

    db.add(evidencia)
    db.commit()
    db.refresh(evidencia)
    return evidencia


# ---------------------------------------------------------------------------
# Concluir — valida obrigatoriedade (incondicional + condicional via regras) e calcula pontuação
# ---------------------------------------------------------------------------
@aplicacoes_router.post("/{aplicacao_id}/concluir", response_model=AplicacaoOut)
def concluir_aplicacao(
    aplicacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("aplicacao.executar")),
):
    aplicacao = _get_aplicacao_ou_404(db, aplicacao_id)
    _checar_acesso(db, user, aplicacao.unidade_id, "aplicacao.executar")

    if aplicacao.status == "concluida":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Aplicação já concluída.")

    itens = _itens_da_versao(db, aplicacao.checklist_versao_id)
    respostas = db.query(Resposta).filter(Resposta.aplicacao_id == aplicacao_id).all()
    respostas_por_item = {str(r.item_id): r.valor for r in respostas}

    regras = (
        db.query(ChecklistRegra)
        .filter(ChecklistRegra.checklist_versao_id == aplicacao.checklist_versao_id)
        .all()
    )

    # Obrigatoriedade condicional: regras com tipo_efeito='exigir' cuja condição
    # avalia True tornam o item_alvo obrigatório, mesmo que obrigatorio=False no cadastro.
    itens_obrigatorios_condicionais = {
        str(r.item_alvo_id)
        for r in regras
        if r.tipo_efeito == "exigir" and avaliar_condicao(r.condicao, respostas_por_item)
    }

    itens_faltando = []
    for item in itens:
        item_id_str = str(item.id)
        obrigatorio_efetivo = item.obrigatorio or item_id_str in itens_obrigatorios_condicionais
        if obrigatorio_efetivo and item_id_str not in respostas_por_item:
            itens_faltando.append({"item_id": item_id_str, "titulo": item.titulo})

    if itens_faltando:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"mensagem": "Itens obrigatórios sem resposta.", "itens": itens_faltando},
        )

    # Cálculo de pontuação: só itens com resposta_critica definida entram no cálculo
    # (são os únicos com noção de "conforme"/"não conforme" neste MVP).
    peso_total = 0.0
    peso_conforme = 0.0
    for item in itens:
        if item.resposta_critica is None:
            continue
        peso = float(item.peso) if item.peso is not None else 1.0
        peso_total += peso
        valor_resposta = respostas_por_item.get(str(item.id))
        if valor_resposta != item.resposta_critica:
            peso_conforme += peso

    aplicacao.status = "concluida"
    aplicacao.concluido_em = datetime.datetime.now(datetime.timezone.utc)
    if peso_total > 0:
        aplicacao.pontuacao_total = round(peso_conforme, 2)
        aplicacao.percentual_conformidade = round((peso_conforme / peso_total) * 100, 2)

    db.commit()
    db.refresh(aplicacao)
    return aplicacao


# --- planos_acao.py ----------------------------------------------
planos_acao_router = APIRouter(prefix="/planos-acao", tags=["planos-acao"])

_TRANSICOES_VALIDAS = {
    "pendente": {"em_andamento", "cancelado"},
    "em_andamento": {"concluido", "atrasado", "cancelado"},
    "atrasado": {"em_andamento", "concluido", "cancelado"},
    "concluido": set(),   # estado final
    "cancelado": set(),   # estado final
}


def _get_plano_ou_404(db: Session, plano_id: UUID) -> PlanoAcao:
    plano = db.get(PlanoAcao, plano_id)
    if plano is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plano de ação não encontrado.")
    return plano


def _unidade_associada(db: Session, plano: PlanoAcao) -> Optional[UUID]:
    """
    Deriva a unidade associada ao plano, quando existir uma relação clara.
    Retorna None quando não há como determinar (ex: AVULSO sem contexto de
    aplicação, ITEM_CHECKLIST/AREA_CHECKLIST de um checklist-template) — nesses
    casos a autorização cai só em permissão, sem filtro de escopo territorial
    (limitação conhecida, registrada em API.md).
    """
    if plano.aplicacao_contexto_id is not None:
        aplicacao = db.get(Aplicacao, plano.aplicacao_contexto_id)
        return aplicacao.unidade_id if aplicacao else None
    if plano.nao_conformidade_id is not None:
        nc = db.get(NaoConformidade, plano.nao_conformidade_id)
        if nc is not None:
            aplicacao = db.get(Aplicacao, nc.aplicacao_id)
            return aplicacao.unidade_id if aplicacao else None
    if plano.checklist_id is not None:
        checklist = db.get(Checklist, plano.checklist_id)
        return checklist.unidade_id if checklist else None
    return None


def _checar_acesso_plano(db: Session, user: Usuario, plano: PlanoAcao, permissao: str):
    unidade_id = _unidade_associada(db, plano)
    if unidade_id is None:
        return  # sem amarração territorial clara — só a permissão já foi checada pelo Depends
    autorizadas = get_unidades_autorizadas(db, user, permissao)
    if autorizadas is not None and unidade_id not in autorizadas:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a esta unidade.")


# ---------------------------------------------------------------------------
# Criar
# ---------------------------------------------------------------------------
@planos_acao_router.post("", response_model=PlanoAcaoOut, status_code=status.HTTP_201_CREATED)
def criar_plano_acao(
    payload: PlanoAcaoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("plano_acao.criar")),
):
    # Validação de referência: garante que a FK preenchida aponta para um registro real
    # (a consistência origem_tipo <-> qual FK está preenchida já foi validada no schema Pydantic).
    if payload.nao_conformidade_id and db.get(NaoConformidade, payload.nao_conformidade_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="nao_conformidade_id inválido.")
    if payload.checklist_id and db.get(Checklist, payload.checklist_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="checklist_id inválido.")
    if payload.aplicacao_contexto_id and db.get(Aplicacao, payload.aplicacao_contexto_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="aplicacao_contexto_id inválido.")

    plano = PlanoAcao(
        origem_tipo=payload.origem_tipo,
        nao_conformidade_id=payload.nao_conformidade_id,
        checklist_item_id=payload.checklist_item_id,
        checklist_area_id=payload.checklist_area_id,
        checklist_id=payload.checklist_id,
        workflow_execucao_id=payload.workflow_execucao_id,
        aplicacao_contexto_id=payload.aplicacao_contexto_id,
        titulo=payload.titulo,
        what=payload.what, why=payload.why, where_=payload.where_, when_=payload.when_,
        who=payload.who, how=payload.how, how_much=payload.how_much,
        responsavel_id=payload.responsavel_id,
        prazo=payload.prazo,
        status="pendente",
        criado_offline=payload.criado_offline,
        sincronizado_em=None if payload.criado_offline else datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(plano)
    db.commit()
    db.refresh(plano)
    return plano


# ---------------------------------------------------------------------------
# Listar (com filtros — visão Kanban simplificada, conforme escopo original)
# ---------------------------------------------------------------------------
@planos_acao_router.get("", response_model=List[PlanoAcaoOut])
def listar_planos_acao(
    status_filtro: Optional[str] = Query(default=None, alias="status"),
    responsavel_id: Optional[UUID] = Query(default=None),
    atrasados: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("plano_acao.visualizar")),
):
    query = db.query(PlanoAcao)
    if status_filtro is not None:
        query = query.filter(PlanoAcao.status == status_filtro)
    if responsavel_id is not None:
        query = query.filter(PlanoAcao.responsavel_id == responsavel_id)
    if atrasados:
        hoje = datetime.date.today()
        query = query.filter(PlanoAcao.prazo < hoje, PlanoAcao.status.notin_(["concluido", "cancelado"]))

    planos = query.order_by(PlanoAcao.prazo).all()

    # Filtro de escopo territorial aplicado em memória (volume baixo neste MVP;
    # ver limitação de paginação já registrada no Módulo 1).
    autorizadas = get_unidades_autorizadas(db, user, "plano_acao.visualizar")
    if autorizadas is None:
        return planos
    resultado = []
    for plano in planos:
        unidade_id = _unidade_associada(db, plano)
        if unidade_id is None or unidade_id in autorizadas:
            resultado.append(plano)
    return resultado


@planos_acao_router.get("/{plano_id}", response_model=PlanoAcaoOut)
def obter_plano_acao(
    plano_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("plano_acao.visualizar")),
):
    plano = _get_plano_ou_404(db, plano_id)
    _checar_acesso_plano(db, user, plano, "plano_acao.visualizar")
    return plano


# ---------------------------------------------------------------------------
# Mudança de status
# ---------------------------------------------------------------------------
@planos_acao_router.patch("/{plano_id}/status", response_model=PlanoAcaoOut)
def atualizar_status_plano_acao(
    plano_id: UUID,
    payload: PlanoAcaoStatusUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("plano_acao.gerenciar")),
):
    plano = _get_plano_ou_404(db, plano_id)
    _checar_acesso_plano(db, user, plano, "plano_acao.gerenciar")

    transicoes_permitidas = _TRANSICOES_VALIDAS.get(plano.status, set())
    if payload.status not in transicoes_permitidas:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transição inválida: '{plano.status}' -> '{payload.status}'. "
                   f"Transições permitidas a partir de '{plano.status}': {sorted(transicoes_permitidas) or 'nenhuma (estado final)'}.",
        )

    plano.status = payload.status
    if payload.status == "concluido":
        plano.encerrado_em = datetime.datetime.now(datetime.timezone.utc)
        plano.validado_por = user.id

    db.commit()
    db.refresh(plano)
    return plano


# ---------------------------------------------------------------------------
# Evidência vinculada ao plano de ação (reusa a entidade generalizada)
# ---------------------------------------------------------------------------
@planos_acao_router.post("/{plano_id}/evidencias", response_model=EvidenciaOut, status_code=status.HTTP_201_CREATED)
def adicionar_evidencia_plano_acao(
    plano_id: UUID,
    payload: EvidenciaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("plano_acao.gerenciar")),
):
    plano = _get_plano_ou_404(db, plano_id)
    _checar_acesso_plano(db, user, plano, "plano_acao.gerenciar")

    evidencia = Evidencia(
        dono_tipo="PLANO_ACAO",
        plano_acao_id=plano_id,
        tipo=payload.tipo,
        arquivo_url=payload.arquivo_url,
        capturado_via_camera_direta=payload.capturado_via_camera_direta,
        criado_offline=payload.criado_offline,
        sincronizado_em=None if payload.criado_offline else datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(evidencia)
    db.commit()
    db.refresh(evidencia)
    return evidencia


# --- dashboards.py -----------------------------------------------
dashboards_router = APIRouter(tags=["dashboards"])


def _aplicar_filtro_unidade_aplicacao(query, db, user, unidade_id: Optional[UUID], permissao: str):
    autorizadas = get_unidades_autorizadas(db, user, permissao)
    if unidade_id is not None:
        if autorizadas is not None and unidade_id not in autorizadas:
            return query.filter(Aplicacao.id == None)  # noqa: E711 — força resultado vazio, sem vazar 403 em endpoint agregado
        return query.filter(Aplicacao.unidade_id == unidade_id)
    if autorizadas is not None:
        if not autorizadas:
            return query.filter(Aplicacao.id == None)  # noqa: E711
        return query.filter(Aplicacao.unidade_id.in_(autorizadas))
    return query


# ---------------------------------------------------------------------------
# Resumo de aplicações
# ---------------------------------------------------------------------------
@dashboards_router.get("/dashboards/aplicacoes", response_model=ResumoAplicacoes)
def resumo_aplicacoes(
    data_inicio: Optional[datetime.date] = Query(default=None),
    data_fim: Optional[datetime.date] = Query(default=None),
    unidade_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("dashboard.visualizar")),
):
    query = db.query(Aplicacao)
    query = _aplicar_filtro_unidade_aplicacao(query, db, user, unidade_id, "dashboard.visualizar")
    if data_inicio is not None:
        query = query.filter(Aplicacao.iniciado_em >= data_inicio)
    if data_fim is not None:
        query = query.filter(Aplicacao.iniciado_em <= data_fim)

    aplicacoes = query.all()
    total = len(aplicacoes)
    por_status: dict = {}
    for a in aplicacoes:
        por_status[a.status] = por_status.get(a.status, 0) + 1

    concluidas_com_percentual = [
        float(a.percentual_conformidade) for a in aplicacoes
        if a.status == "concluida" and a.percentual_conformidade is not None
    ]
    percentual_medio = (
        round(sum(concluidas_com_percentual) / len(concluidas_com_percentual), 2)
        if concluidas_com_percentual else None
    )

    return ResumoAplicacoes(
        total=total,
        por_status=por_status,
        percentual_conformidade_medio=percentual_medio,
        periodo_inicio=data_inicio,
        periodo_fim=data_fim,
    )


# ---------------------------------------------------------------------------
# Resumo de não conformidades (incluindo reincidência por item)
# ---------------------------------------------------------------------------
@dashboards_router.get("/dashboards/nao-conformidades", response_model=ResumoNaoConformidades)
def resumo_nao_conformidades(
    unidade_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("dashboard.visualizar")),
):
    query = db.query(NaoConformidade).join(Aplicacao, Aplicacao.id == NaoConformidade.aplicacao_id)
    query = _aplicar_filtro_unidade_aplicacao(query, db, user, unidade_id, "dashboard.visualizar")

    nao_conformidades = query.all()
    total = len(nao_conformidades)

    por_status: dict = {}
    por_prioridade: dict = {}
    contagem_por_item: dict = {}
    for nc in nao_conformidades:
        por_status[nc.status] = por_status.get(nc.status, 0) + 1
        por_prioridade[nc.prioridade] = por_prioridade.get(nc.prioridade, 0) + 1
        if nc.item_id is not None:
            contagem_por_item[nc.item_id] = contagem_por_item.get(nc.item_id, 0) + 1

    # Reincidência: itens com mais de 1 ocorrência, ordenados do mais frequente
    itens_reincidentes = []
    for item_id, ocorrencias in sorted(contagem_por_item.items(), key=lambda kv: -kv[1]):
        if ocorrencias <= 1:
            continue
        item = db.get(ChecklistItem, item_id)
        itens_reincidentes.append(ItemReincidente(
            item_id=str(item_id),
            titulo_item=item.titulo if item else "(item removido)",
            ocorrencias=ocorrencias,
        ))

    return ResumoNaoConformidades(
        total=total,
        por_status=por_status,
        por_prioridade=por_prioridade,
        itens_reincidentes=itens_reincidentes[:10],  # top 10
    )


# ---------------------------------------------------------------------------
# Resumo de planos de ação
# ---------------------------------------------------------------------------
@dashboards_router.get("/dashboards/planos-acao", response_model=ResumoPlanosAcao)
def resumo_planos_acao(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_permission("dashboard.visualizar")),
):
    # NOTA (limitação registrada em API.md): plano_acao não tem coluna própria
    # de unidade, então este resumo não aplica filtro de escopo territorial —
    # mesma limitação já documentada no Módulo 5.
    planos = db.query(PlanoAcao).all()
    total = len(planos)
    por_status: dict = {}
    hoje = datetime.date.today()
    atrasados = 0
    for p in planos:
        por_status[p.status] = por_status.get(p.status, 0) + 1
        if p.prazo < hoje and p.status not in ("concluido", "cancelado"):
            atrasados += 1

    return ResumoPlanosAcao(total=total, por_status=por_status, atrasados=atrasados)


# ---------------------------------------------------------------------------
# Exportação CSV de aplicações
# ---------------------------------------------------------------------------
@dashboards_router.get("/relatorios/aplicacoes.csv")
def exportar_aplicacoes_csv(
    data_inicio: Optional[datetime.date] = Query(default=None),
    data_fim: Optional[datetime.date] = Query(default=None),
    unidade_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("relatorio.exportar")),
):
    query = (
        db.query(Aplicacao, ChecklistVersao, Checklist, Unidade, UsuarioModel)
        .join(ChecklistVersao, ChecklistVersao.id == Aplicacao.checklist_versao_id)
        .join(Checklist, Checklist.id == ChecklistVersao.checklist_id)
        .join(Unidade, Unidade.id == Aplicacao.unidade_id)
        .join(UsuarioModel, UsuarioModel.id == Aplicacao.aplicador_id)
    )
    query = _aplicar_filtro_unidade_aplicacao(query, db, user, unidade_id, "relatorio.exportar")
    if data_inicio is not None:
        query = query.filter(Aplicacao.iniciado_em >= data_inicio)
    if data_fim is not None:
        query = query.filter(Aplicacao.iniciado_em <= data_fim)

    linhas = query.order_by(Aplicacao.iniciado_em).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "aplicacao_id", "checklist", "unidade", "aplicador", "status",
        "percentual_conformidade", "iniciado_em", "concluido_em",
    ])
    for aplicacao, versao, checklist, unidade, aplicador in linhas:
        writer.writerow([
            str(aplicacao.id), checklist.nome, unidade.nome, aplicador.nome, aplicacao.status,
            aplicacao.percentual_conformidade if aplicacao.percentual_conformidade is not None else "",
            aplicacao.iniciado_em.isoformat() if aplicacao.iniciado_em else "",
            aplicacao.concluido_em.isoformat() if aplicacao.concluido_em else "",
        ])
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aplicacoes.csv"},
    )


# ============================================================================
# AGREGADOR DE ROTAS (/api/v1)
# ============================================================================
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(usuarios_router)
api_router.include_router(unidades_router)
api_router.include_router(setores_router)
api_router.include_router(checklists_router)
api_router.include_router(tipos_router)
api_router.include_router(aplicacoes_router)
api_router.include_router(planos_acao_router)
api_router.include_router(dashboards_router)


