-- ============================================================================
-- V1__core_schema.sql
-- King Star Colchões — Motor de Checklists
-- Migration inicial (Fase 1 — Arquitetura)
--
-- Escopo: estrutura organizacional, motor de checklists (editor + versionamento
-- imutável + motor de regras), execução, não conformidade / plano de ação,
-- sincronização offline genérica e auditoria transversal.
--
-- NÃO incluído nesta migration (propositalmente — ver DATABASE.md seção 8):
--   workflow de aprovação multi-etapa, agendamento/recorrência, notificações,
--   QR Code. Apenas a tabela `workflow_execucao` existe como STUB, para permitir
--   a FK reservada em `plano_acao`, sem nenhuma lógica de workflow implementada.
--
-- Este script é DDL puro. Revisão obrigatória antes de aplicar em qualquer
-- ambiente. Nenhum dado de seed além dos catálogos mínimos necessários para
-- o sistema funcionar (perfis padrão, tipos de resposta básicos).
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Extensões
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ----------------------------------------------------------------------------
-- Enums
-- ----------------------------------------------------------------------------
CREATE TYPE usuario_status AS ENUM ('ativo', 'inativo', 'bloqueado');

CREATE TYPE checklist_status AS ENUM ('rascunho', 'ativo', 'arquivado');
CREATE TYPE checklist_versao_status AS ENUM ('rascunho', 'publicada', 'obsoleta');

CREATE TYPE regra_tipo_efeito AS ENUM (
    'exibir', 'ocultar', 'exigir', 'tornar_opcional',
    'exigir_evidencia', 'disparar_nao_conformidade'
);

CREATE TYPE aplicacao_status AS ENUM ('rascunho', 'em_andamento', 'concluida', 'cancelada');

CREATE TYPE nao_conformidade_origem AS ENUM ('resposta_critica', 'regra', 'manual');
CREATE TYPE nao_conformidade_prioridade AS ENUM ('baixa', 'media', 'alta', 'critica');
CREATE TYPE nao_conformidade_status AS ENUM ('aberta', 'em_tratamento', 'encerrada', 'contestada');

CREATE TYPE plano_acao_origem_tipo AS ENUM (
    'NAO_CONFORMIDADE', 'ITEM_CHECKLIST', 'AREA_CHECKLIST',
    'CHECKLIST', 'AVULSO', 'WORKFLOW'
);
CREATE TYPE plano_acao_status AS ENUM ('pendente', 'em_andamento', 'concluido', 'atrasado', 'cancelado');

CREATE TYPE contestacao_status AS ENUM ('pendente', 'aprovada', 'rejeitada');

CREATE TYPE evidencia_dono_tipo AS ENUM ('APLICACAO', 'RESPOSTA', 'PLANO_ACAO', 'NAO_CONFORMIDADE');
CREATE TYPE evidencia_tipo AS ENUM ('foto', 'video', 'audio', 'documento', 'comentario');

CREATE TYPE sync_entidade_tipo AS ENUM (
    'aplicacao', 'resposta', 'evidencia', 'nao_conformidade', 'plano_acao', 'assinatura'
);
CREATE TYPE sync_operacao AS ENUM ('criar', 'atualizar', 'concluir', 'cancelar');
CREATE TYPE sync_status AS ENUM ('pendente', 'processado', 'conflito', 'erro');

-- ============================================================================
-- 1. ESTRUTURA ORGANIZACIONAL E IDENTIDADE
-- ============================================================================

CREATE TABLE organizacao (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome        TEXT NOT NULL,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE organizacao IS
    'Preparo estrutural para multi-organização futura. Single-tenant hoje (decisão registrada): apenas King Star Colchões. Nenhuma lógica multi-tenant implementada.';

CREATE TABLE unidade (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organizacao_id    UUID NOT NULL REFERENCES organizacao(id),
    nome              TEXT NOT NULL,
    tipo              TEXT,                       -- catálogo aberto: fábrica, loja, CD...
    latitude          NUMERIC(9,6),
    longitude         NUMERIC(9,6),
    raio_permitido_m  INTEGER,
    ativo             BOOLEAN NOT NULL DEFAULT true,
    criado_em         TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_unidade_organizacao ON unidade(organizacao_id);

CREATE TABLE setor (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unidade_id  UUID NOT NULL REFERENCES unidade(id),
    nome        TEXT NOT NULL,
    ativo       BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX idx_setor_unidade ON setor(unidade_id);

CREATE TABLE usuario (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome           TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    senha_hash     TEXT NOT NULL,
    status         usuario_status NOT NULL DEFAULT 'ativo',
    criado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE perfil (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome        TEXT NOT NULL,
    permissoes  JSONB NOT NULL DEFAULT '[]'::jsonb
);
COMMENT ON COLUMN perfil.permissoes IS
    'Lista de capacidades, ex: ["checklist.criar","checklist.publicar","naoconformidade.tratar"]. Validado na aplicação.';

CREATE TABLE usuario_escopo (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id  UUID NOT NULL REFERENCES usuario(id),
    perfil_id   UUID NOT NULL REFERENCES perfil(id),
    unidade_id  UUID REFERENCES unidade(id),   -- null = escopo em toda a organização
    setor_id    UUID REFERENCES setor(id)
);
CREATE INDEX idx_usuario_escopo_usuario ON usuario_escopo(usuario_id);
CREATE INDEX idx_usuario_escopo_unidade ON usuario_escopo(unidade_id);

-- ============================================================================
-- 2. MOTOR DE CHECKLISTS
-- ============================================================================

CREATE TABLE checklist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome        TEXT NOT NULL,
    descricao   TEXT,
    criado_por  UUID NOT NULL REFERENCES usuario(id),
    unidade_id  UUID REFERENCES unidade(id),
    status      checklist_status NOT NULL DEFAULT 'rascunho',
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_checklist_unidade ON checklist(unidade_id);

CREATE TABLE checklist_versao (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checklist_id           UUID NOT NULL REFERENCES checklist(id),
    numero_versao          INTEGER NOT NULL,
    publicado_em           TIMESTAMPTZ,
    publicado_por          UUID REFERENCES usuario(id),
    status                 checklist_versao_status NOT NULL DEFAULT 'rascunho',
    snapshot_estrutura     JSONB,               -- preenchido apenas na publicação
    snapshot_schema_versao INTEGER,
    UNIQUE (checklist_id, numero_versao)
);
CREATE INDEX idx_checklist_versao_checklist ON checklist_versao(checklist_id);

-- Garante no máximo uma versão "publicada" ativa por checklist
CREATE UNIQUE INDEX uq_checklist_versao_publicada
    ON checklist_versao(checklist_id)
    WHERE status = 'publicada';

COMMENT ON COLUMN checklist_versao.snapshot_estrutura IS
    'Cópia congelada da árvore completa (áreas/itens/regras) no momento da publicação. A execução (aplicacao/resposta) sempre lê deste snapshot, nunca das tabelas normalizadas — protege o histórico de edições futuras no rascunho da próxima versão.';

CREATE TABLE checklist_area (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checklist_versao_id  UUID NOT NULL REFERENCES checklist_versao(id),
    nome                 TEXT NOT NULL,
    ordem                INTEGER NOT NULL DEFAULT 0,
    area_pai_id          UUID REFERENCES checklist_area(id)
);
CREATE INDEX idx_checklist_area_versao ON checklist_area(checklist_versao_id);
CREATE INDEX idx_checklist_area_pai ON checklist_area(area_pai_id);

CREATE TABLE tipo_resposta_catalogo (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chave          TEXT NOT NULL UNIQUE,   -- ex: sim_nao, foto, texto_curto, nota_0_10
    config_schema  JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE checklist_item (
    id                                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    area_id                                UUID NOT NULL REFERENCES checklist_area(id),
    ordem                                  INTEGER NOT NULL DEFAULT 0,
    titulo                                 TEXT NOT NULL,
    tipo_resposta                          UUID NOT NULL REFERENCES tipo_resposta_catalogo(id),
    obrigatorio                            BOOLEAN NOT NULL DEFAULT false,
    peso                                   NUMERIC(6,2),
    resposta_critica                       JSONB,
    evidencia_obrigatoria                  BOOLEAN NOT NULL DEFAULT false,
    comentario_obrigatorio_se_nao_conforme BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX idx_checklist_item_area ON checklist_item(area_id);
CREATE INDEX idx_checklist_item_tipo_resposta ON checklist_item(tipo_resposta);

CREATE TABLE checklist_regra (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checklist_versao_id  UUID NOT NULL REFERENCES checklist_versao(id),
    item_alvo_id         UUID NOT NULL REFERENCES checklist_item(id),
    tipo_efeito          regra_tipo_efeito NOT NULL,
    condicao             JSONB NOT NULL,
    schema_versao        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_checklist_regra_versao ON checklist_regra(checklist_versao_id);
CREATE INDEX idx_checklist_regra_item_alvo ON checklist_regra(item_alvo_id);

COMMENT ON COLUMN checklist_regra.condicao IS
    'Árvore de condição (E/OU aninhado, cross-área). O motor backend suporta encadeamento desde o v1; a interface do MVP expõe apenas 1 condição por vez (decisão registrada) — o schema já comporta evolução da UI sem redesenho.';

-- ----------------------------------------------------------------------------
-- Stub de Workflow (Fase 4) — existe apenas para permitir a FK reservada em
-- plano_acao.workflow_execucao_id. Nenhuma lógica de workflow implementada.
-- ----------------------------------------------------------------------------
CREATE TABLE workflow_execucao (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE workflow_execucao IS
    'STUB reservado para o motor de workflow (Fase 4). Sem lógica implementada nesta migration.';

-- ============================================================================
-- 3. EXECUÇÃO (APLICAÇÃO DO CHECKLIST)
-- ============================================================================

CREATE TABLE aplicacao (
    -- id gerado no dispositivo quando criada offline: mesma identidade final,
    -- sem remapeamento posterior de "id local" para "id de servidor".
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checklist_versao_id      UUID NOT NULL REFERENCES checklist_versao(id),
    unidade_id               UUID NOT NULL REFERENCES unidade(id),
    setor_id                 UUID REFERENCES setor(id),
    aplicador_id             UUID NOT NULL REFERENCES usuario(id),
    status                   aplicacao_status NOT NULL DEFAULT 'rascunho',
    criado_offline           BOOLEAN NOT NULL DEFAULT false,
    iniciado_em              TIMESTAMPTZ,
    concluido_em             TIMESTAMPTZ,
    localizacao_inicio       POINT,
    pontuacao_total          NUMERIC(6,2),
    percentual_conformidade  NUMERIC(5,2),
    sincronizado_em          TIMESTAMPTZ   -- null = pendente (só relevante se criado_offline = true)
);
CREATE INDEX idx_aplicacao_unidade ON aplicacao(unidade_id);
CREATE INDEX idx_aplicacao_checklist_versao ON aplicacao(checklist_versao_id);
CREATE INDEX idx_aplicacao_status ON aplicacao(status);
CREATE INDEX idx_aplicacao_aplicador ON aplicacao(aplicador_id);
-- consulta frequente de dashboard: pendências de sincronização
CREATE INDEX idx_aplicacao_pendente_sync ON aplicacao(unidade_id)
    WHERE criado_offline = true AND sincronizado_em IS NULL;

CREATE TABLE resposta (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aplicacao_id    UUID NOT NULL REFERENCES aplicacao(id),
    item_id         UUID NOT NULL REFERENCES checklist_item(id),   -- referência ao item dentro do snapshot
    valor           JSONB NOT NULL,
    criado_offline  BOOLEAN NOT NULL DEFAULT false,
    sincronizado_em TIMESTAMPTZ,
    respondido_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_resposta_aplicacao ON resposta(aplicacao_id);
CREATE INDEX idx_resposta_item ON resposta(item_id);

-- ============================================================================
-- 4. NÃO CONFORMIDADE E PLANO DE AÇÃO
-- ============================================================================

CREATE TABLE nao_conformidade (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aplicacao_id    UUID NOT NULL REFERENCES aplicacao(id),
    item_id         UUID REFERENCES checklist_item(id),
    origem          nao_conformidade_origem NOT NULL,
    titulo          TEXT NOT NULL,
    descricao       TEXT,
    prioridade      nao_conformidade_prioridade NOT NULL DEFAULT 'media',
    status          nao_conformidade_status NOT NULL DEFAULT 'aberta',
    responsavel_id  UUID REFERENCES usuario(id),
    prazo           DATE,
    criado_offline  BOOLEAN NOT NULL DEFAULT false,
    sincronizado_em TIMESTAMPTZ,
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_nc_aplicacao ON nao_conformidade(aplicacao_id);
CREATE INDEX idx_nc_status ON nao_conformidade(status);
CREATE INDEX idx_nc_responsavel ON nao_conformidade(responsavel_id);

CREATE TABLE plano_acao (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    origem_tipo           plano_acao_origem_tipo NOT NULL,

    -- Múltiplas FKs nullable (uma por origem possível), em vez de origem_id
    -- polimórfico genérico — preserva integridade referencial real no banco.
    nao_conformidade_id   UUID REFERENCES nao_conformidade(id),
    checklist_item_id     UUID REFERENCES checklist_item(id),
    checklist_area_id     UUID REFERENCES checklist_area(id),
    checklist_id          UUID REFERENCES checklist(id),
    workflow_execucao_id  UUID REFERENCES workflow_execucao(id),

    -- Registro técnico de contexto operacional (distinto de origem_tipo):
    -- durante qual inspeção este plano foi aberto, quando aplicável.
    aplicacao_contexto_id UUID REFERENCES aplicacao(id),

    titulo          TEXT NOT NULL,
    what            TEXT,
    why             TEXT,
    where_          TEXT,
    when_           TEXT,
    who             TEXT,
    how             TEXT,
    how_much        TEXT,

    responsavel_id  UUID NOT NULL REFERENCES usuario(id),
    prazo           DATE NOT NULL,
    status          plano_acao_status NOT NULL DEFAULT 'pendente',

    criado_offline  BOOLEAN NOT NULL DEFAULT false,
    sincronizado_em TIMESTAMPTZ,

    encerrado_em    TIMESTAMPTZ,
    validado_por    UUID REFERENCES usuario(id),
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_plano_acao_origem_consistente CHECK (
        (origem_tipo = 'NAO_CONFORMIDADE' AND nao_conformidade_id IS NOT NULL
            AND checklist_item_id IS NULL AND checklist_area_id IS NULL
            AND checklist_id IS NULL AND workflow_execucao_id IS NULL)
        OR (origem_tipo = 'ITEM_CHECKLIST' AND checklist_item_id IS NOT NULL
            AND nao_conformidade_id IS NULL AND checklist_area_id IS NULL
            AND checklist_id IS NULL AND workflow_execucao_id IS NULL)
        OR (origem_tipo = 'AREA_CHECKLIST' AND checklist_area_id IS NOT NULL
            AND nao_conformidade_id IS NULL AND checklist_item_id IS NULL
            AND checklist_id IS NULL AND workflow_execucao_id IS NULL)
        OR (origem_tipo = 'CHECKLIST' AND checklist_id IS NOT NULL
            AND nao_conformidade_id IS NULL AND checklist_item_id IS NULL
            AND checklist_area_id IS NULL AND workflow_execucao_id IS NULL)
        OR (origem_tipo = 'WORKFLOW' AND workflow_execucao_id IS NOT NULL
            AND nao_conformidade_id IS NULL AND checklist_item_id IS NULL
            AND checklist_area_id IS NULL AND checklist_id IS NULL)
        OR (origem_tipo = 'AVULSO'
            AND nao_conformidade_id IS NULL AND checklist_item_id IS NULL
            AND checklist_area_id IS NULL AND checklist_id IS NULL
            AND workflow_execucao_id IS NULL)
    )
);
CREATE INDEX idx_plano_acao_responsavel ON plano_acao(responsavel_id);
CREATE INDEX idx_plano_acao_status ON plano_acao(status);
CREATE INDEX idx_plano_acao_prazo ON plano_acao(prazo);
CREATE INDEX idx_plano_acao_nc ON plano_acao(nao_conformidade_id);
CREATE INDEX idx_plano_acao_aplicacao_contexto ON plano_acao(aplicacao_contexto_id);

COMMENT ON CONSTRAINT chk_plano_acao_origem_consistente ON plano_acao IS
    'Garante, em nível de banco, que apenas a FK correspondente ao origem_tipo esteja preenchida. Nova origem futura = nova coluna FK nullable + atualização deste CHECK, sem reconstrução da entidade.';

CREATE TABLE contestacao (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nao_conformidade_id UUID NOT NULL REFERENCES nao_conformidade(id),
    solicitado_por      UUID NOT NULL REFERENCES usuario(id),
    justificativa       TEXT NOT NULL,
    status              contestacao_status NOT NULL DEFAULT 'pendente',
    decidido_por        UUID REFERENCES usuario(id),
    decidido_em         TIMESTAMPTZ,
    criado_em           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_contestacao_nc ON contestacao(nao_conformidade_id);

-- ============================================================================
-- 5. EVIDÊNCIAS E ASSINATURA (donos múltiplos, generalizado)
-- ============================================================================

CREATE TABLE evidencia (
    id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dono_tipo                     evidencia_dono_tipo NOT NULL,
    aplicacao_id                  UUID REFERENCES aplicacao(id),
    resposta_id                   UUID REFERENCES resposta(id),
    plano_acao_id                 UUID REFERENCES plano_acao(id),
    nao_conformidade_id           UUID REFERENCES nao_conformidade(id),
    tipo                          evidencia_tipo NOT NULL,
    arquivo_url                   TEXT,
    capturado_via_camera_direta   BOOLEAN NOT NULL DEFAULT false,
    metadados                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    localizacao                   POINT,
    criado_offline                BOOLEAN NOT NULL DEFAULT false,
    sincronizado_em               TIMESTAMPTZ,
    criado_em                     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_evidencia_dono_consistente CHECK (
        (dono_tipo = 'APLICACAO' AND aplicacao_id IS NOT NULL
            AND resposta_id IS NULL AND plano_acao_id IS NULL AND nao_conformidade_id IS NULL)
        OR (dono_tipo = 'RESPOSTA' AND resposta_id IS NOT NULL
            AND aplicacao_id IS NULL AND plano_acao_id IS NULL AND nao_conformidade_id IS NULL)
        OR (dono_tipo = 'PLANO_ACAO' AND plano_acao_id IS NOT NULL
            AND aplicacao_id IS NULL AND resposta_id IS NULL AND nao_conformidade_id IS NULL)
        OR (dono_tipo = 'NAO_CONFORMIDADE' AND nao_conformidade_id IS NOT NULL
            AND aplicacao_id IS NULL AND resposta_id IS NULL AND plano_acao_id IS NULL)
    )
);
CREATE INDEX idx_evidencia_aplicacao ON evidencia(aplicacao_id);
CREATE INDEX idx_evidencia_resposta ON evidencia(resposta_id);
CREATE INDEX idx_evidencia_plano_acao ON evidencia(plano_acao_id);
CREATE INDEX idx_evidencia_nc ON evidencia(nao_conformidade_id);

CREATE TABLE assinatura (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aplicacao_id           UUID NOT NULL REFERENCES aplicacao(id),
    usuario_id             UUID NOT NULL REFERENCES usuario(id),
    imagem_assinatura_url  TEXT NOT NULL,
    criado_offline         BOOLEAN NOT NULL DEFAULT false,
    sincronizado_em        TIMESTAMPTZ,
    assinado_em            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_assinatura_aplicacao ON assinatura(aplicacao_id);

-- ============================================================================
-- 6. SINCRONIZAÇÃO OFFLINE — MOTOR GENÉRICO (agnóstico de entidade)
-- ============================================================================

CREATE TABLE evento_sincronizacao (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_evento_local       UUID NOT NULL UNIQUE,   -- gerado no dispositivo: idempotência do EVENTO
    usuario_id            UUID NOT NULL REFERENCES usuario(id),
    entidade_tipo         sync_entidade_tipo NOT NULL,
    entidade_id           UUID NOT NULL,           -- sem FK: polimórfico por natureza (trade-off registrado)
    operacao              sync_operacao NOT NULL,
    payload               JSONB NOT NULL,
    schema_versao         INTEGER NOT NULL DEFAULT 1,
    criado_em_dispositivo TIMESTAMPTZ NOT NULL,
    recebido_em_servidor  TIMESTAMPTZ,
    status                sync_status NOT NULL DEFAULT 'pendente',
    detalhe_conflito      JSONB
);
CREATE INDEX idx_evento_sync_status ON evento_sincronizacao(status);
CREATE INDEX idx_evento_sync_entidade ON evento_sincronizacao(entidade_tipo, entidade_id);
CREATE INDEX idx_evento_sync_usuario ON evento_sincronizacao(usuario_id);

COMMENT ON TABLE evento_sincronizacao IS
    'Motor de sincronização agnóstico de entidade. entidade_tipo é extensível (novo valor de enum = nova entidade sincronizável, sem alterar a estrutura da tabela). entidade_id não tem FK de banco por ser polimórfico — validação de consistência ocorre na aplicação.';

-- ============================================================================
-- 7. AUDITORIA (transversal)
-- ============================================================================

CREATE TABLE log_auditoria (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id     UUID REFERENCES usuario(id),
    acao           TEXT NOT NULL,          -- ex: 'checklist.publicar', 'usuario.permissao.alterar', 'sincronizacao.processar'
    entidade_tipo  TEXT NOT NULL,
    entidade_id    UUID NOT NULL,
    valor_anterior JSONB,
    valor_novo     JSONB,
    ip_dispositivo TEXT,
    criado_em      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_log_auditoria_entidade ON log_auditoria(entidade_tipo, entidade_id);
CREATE INDEX idx_log_auditoria_usuario ON log_auditoria(usuario_id);
CREATE INDEX idx_log_auditoria_criado_em ON log_auditoria(criado_em);

COMMIT;

-- ============================================================================
-- FIM DA MIGRATION V1
--
-- Não incluído (deliberadamente, conforme DATABASE.md seção 8):
--   - Tabelas de agendamento/recorrência
--   - Tabelas de notificação
--   - Tabelas de QR Code
--   - Qualquer lógica real de workflow (workflow_execucao é STUB vazio)
--   - Dados de seed além do necessário para o sistema operar (perfis/tipos
--     de resposta básicos, que devem ser adicionados em migration separada,
--     ex. V2__seed_catalogos.sql, para manter esta migration só DDL)
-- ============================================================================
