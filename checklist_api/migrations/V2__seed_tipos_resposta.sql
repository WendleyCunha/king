-- ============================================================================
-- V2__seed_tipos_resposta.sql
-- Seed mínimo do catálogo de tipos de resposta (tabela aberta, extensível).
-- Não é DDL de estrutura — é dado de referência necessário para o sistema
-- operar (o editor de checklist depende de pelo menos um tipo existir).
-- ============================================================================

BEGIN;

INSERT INTO tipo_resposta_catalogo (chave, config_schema) VALUES
    ('sim_nao',      '{"tipo": "boolean"}'),
    ('conforme_nao_conforme', '{"tipo": "enum", "valores": ["conforme", "nao_conforme"]}'),
    ('texto_curto',  '{"tipo": "string", "max_length": 255}'),
    ('texto_longo',  '{"tipo": "string"}'),
    ('numero',       '{"tipo": "number"}'),
    ('nota_0_10',    '{"tipo": "number", "min": 0, "max": 10}'),
    ('foto',         '{"tipo": "url"}'),
    ('data',         '{"tipo": "date"}')
ON CONFLICT (chave) DO NOTHING;

COMMIT;
