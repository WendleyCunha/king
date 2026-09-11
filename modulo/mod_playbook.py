"""
Módulo PLAYBOOK — "Ferramenta externa → solução interna".

Mesma lógica do checklist reutilizável (14 fases: enquadramento →
diagnóstico → desenho → desenvolvimento → migração → implantação →
estabilização → encerramento do contrato anterior), agora vivendo dentro
do Painel como módulo de verdade: dados no Firestore (reaproveita o
`get_db()` de database.py — mesmo banco "portal", sem precisar criar
banco novo nenhum), anexos, notas internas por item, e tema escuro/claro.

Coleções:
  /playbook_iniciativas/{id} → { nome, ferramenta, solucao, responsavel,
                                  custo_mensal, tema_preferido, criado_em,
                                  fases: [ { titulo, gate, itens: [
                                      { texto, status, nota_interna,
                                        anexos: [{id, nome_arquivo,
                                                  tamanho, tipo,
                                                  enviado_por, enviado_em}]
                                      } ] } ] }
  /playbook_anexos/{id}      → { bin, nome_arquivo, tipo, tamanho,
                                  iniciativa_id, enviado_por, enviado_em }
    (arquivo binário separado da iniciativa pra não estourar o limite de
    1 MiB por documento do Firestore à medida que anexos se acumulam)
"""
import streamlit as st
import mimetypes
from datetime import datetime, timezone, timedelta

from database import get_db

BRT = timezone(timedelta(hours=-3))
def _agora_iso(): return datetime.now(BRT).isoformat()
def _agora_str(): return datetime.now(BRT).strftime("%d/%m/%Y %H:%M")

COL_INICIATIVAS = "playbook_iniciativas"
COL_ANEXOS = "playbook_anexos"
TAMANHO_MAX_ANEXO = 900_000  # ~900 KB — folga dentro do limite de 1 MiB/doc do Firestore

STATUS_OPCOES = ["pendente", "andamento", "solicitado", "feito", "bloqueado", "na"]
STATUS_LABEL = {
    "pendente": "Pendente", "andamento": "Em andamento", "solicitado": "Solicitado",
    "feito": "Feito", "bloqueado": "Bloqueado", "na": "N/A",
}
STATUS_COR = {
    "pendente": "#8b98a5", "andamento": "#e8a33d", "solicitado": "#6ea8d8",
    "feito": "#4fb8ae", "bloqueado": "#d9695f", "na": "#5f6b78",
}

FASE_INDICE_GATE_INICIO = 10  # fases 11-14 (índice 10..13) dependem da Fase 7


# ═══════════════════════════════════════════════════════════════════
# MODELO PADRÃO (as 14 fases) — usado toda vez que uma iniciativa nova
# é criada "a partir do modelo".
# ═══════════════════════════════════════════════════════════════════
def _item(texto):
    return {"texto": texto, "status": "pendente", "nota_interna": "", "anexos": []}


def modelo_base_fases():
    return [
        {"titulo": "1. Enquadramento e Decisão", "gate": False, "itens": [
            _item("Consolidar o custo atual da ferramenta externa vs. custo de construir e manter internamente"),
            _item("Buscar valor atualizado com o fornecedor/financeiro"),
            _item("Realizar o levantamento do investimento técnico com o TI"),
            _item("Levantar com o Jurídico o prazo de aviso prévio e cláusulas críticas do contrato atual, para calibrar o cronograma"),
            _item("Coletar contratos e aditivos vigentes"),
            _item("Fornecer contratos/aditivos ao Jurídico com prazo definido para avaliação"),
            _item("Definir a arquitetura da solução interna"),
            _item("Validar e aprovar o enquadramento com os Heads"),
            _item("Registrar a decisão formalmente e iniciar a Fase 2 (se reprovado, revisar o projeto)"),
        ]},
        {"titulo": "2. Diagnóstico e Levantamento (AS IS)", "gate": False, "itens": [
            _item("Mapear todas as funcionalidades hoje usadas na ferramenta externa"),
            _item("Aplicar o formulário de diagnóstico ao administrador da ferramenta"),
            _item("Aplicar o formulário de levantamento aos usuários finais das áreas envolvidas"),
            _item("Levantar volumetria e indicadores de uso relevantes (volume/mês, taxa de resposta, SLA, etc.)"),
            _item("Consultar o Financeiro para confirmar quanto a empresa paga hoje, como é calculado e se há cobranças adicionais"),
            _item("Consolidar o diagnóstico e submeter para aprovação"),
        ]},
        {"titulo": "3. Desenho da Solução (TO BE)", "gate": False, "itens": [
            _item("Desenhar o fluxo/jornada completa, com regras de disparo por canal e frequência"),
            _item("Construir a Matriz de Gaps (ferramenta externa x solução interna)"),
            _item("Desenhar a arquitetura de integração com os canais necessários"),
            _item("Desenhar o modelo de dados único atravessando as etapas"),
            _item("Desenhar o processo de tratativa/fechamento de loop (dono, prazo, escalonamento)"),
            _item("Submeter o desenho para revisão de LGPD/Jurídico"),
            _item("Aprovar o desenho"),
        ]},
        {"titulo": "4. Desenvolvimento/Parametrização", "gate": False, "itens": [
            _item("Priorizar as ondas de construção"),
            _item("Desenvolver/parametrizar cada onda conforme o desenho aprovado"),
            _item("Acompanhar o orçamento de desenvolvimento vs. TCO projetado"),
            _item("Testar cada onda antes de liberar para migração"),
            _item("Obter aprovação por onda entregue"),
        ]},
        {"titulo": "5. Migração e Testes", "gate": False, "itens": [
            _item("Rodar cada etapa em paralelo com a ferramenta externa pelo período mínimo definido"),
            _item("Comparar indicadores entre as duas ferramentas (taxa de resposta, tempo de tratativa)"),
            _item("Migrar ou preservar acesso ao histórico de dados"),
            _item("Validar critérios de aceite por onda"),
            _item("Aprovar formalmente cada onda migrada"),
        ]},
        {"titulo": "6. Implantação", "gate": False, "itens": [
            _item("Treinar cada área envolvida na nova ferramenta"),
            _item("Comunicar o RACI de quem trata cada frente"),
            _item("Ativar a ferramenta em produção, etapa por etapa, substituindo a ferramenta externa"),
            _item("Validar que os dados estão sendo capturados corretamente após a ativação"),
        ]},
        {"titulo": "7. Estabilização", "gate": False, "itens": [
            _item("Acompanhar indicadores de aderência (taxa de resposta, SLA de tratativa)"),
            _item("Coletar e tratar feedback das áreas usuárias nas primeiras semanas"),
            _item("Ajustar parametrizações/regras identificadas como problema"),
            _item("Obter aprovação final de estabilização — libera o início do cancelamento da ferramenta externa"),
        ]},
        {"titulo": "8. Revisar cláusulas contratuais do contrato anterior", "gate": False, "itens": [
            _item("Localizar o contrato vigente e eventuais aditivos"),
            _item("Identificar o prazo de aviso prévio exigido"),
            _item("Identificar multa rescisória, se houver, e sua condição de aplicação"),
            _item("Identificar vigência mínima e data de renovação automática"),
            _item("Identificar a forma exigida de notificação (e-mail, carta, portal)"),
            _item("Repassar o levantamento ao Financeiro"),
        ]},
        {"titulo": "9. Levantar situação financeira do contrato anterior", "gate": False, "itens": [
            _item("Levantar faturas em aberto e status de pagamento"),
            _item("Confirmar o ciclo de cobrança vigente"),
            _item("Calcular o valor de eventual multa rescisória"),
            _item("Consolidar o valor total do encerramento"),
        ]},
        {"titulo": "10. Exportar e validar backup do histórico de dados", "gate": False, "itens": [
            _item("Levantar todos os dados históricos existentes"),
            _item("Executar a extração completa dos dados na plataforma"),
            _item("Validar a integridade do que foi exportado (comparar volumetria exportada vs. conhecida)"),
            _item("Armazenar o backup em local definitivo e seguro"),
            _item("Confirmar formalmente que o backup está validado"),
        ]},
        {"titulo": "11. Envio da notificação de aviso prévio", "gate": True, "itens": [
            _item("Confirmar que o backup do histórico já foi validado"),
            _item("Redigir a notificação conforme a forma exigida pelo contrato"),
            _item("Validar o texto com o Jurídico"),
            _item("Enviar a notificação dentro do prazo contratual de aviso prévio"),
            _item("Guardar o comprovante de envio/protocolo"),
        ]},
        {"titulo": "12. Desativar usuários, remover integrações e revogar credenciais", "gate": True, "itens": [
            _item("Confirmar que a notificação já foi enviada e o prazo contratual está em curso"),
            _item("Levantar todos os usuários com acesso à plataforma"),
            _item("Remover/desativar integrações ativas"),
            _item("Revogar credenciais e acessos de API"),
            _item("Confirmar o encerramento técnico completo com TI"),
        ]},
        {"titulo": "13. Confirmar ausência de cobranças e arquivar comprovante", "gate": True, "itens": [
            _item("Solicitar ao fornecedor o comprovante formal de cancelamento"),
            _item("Confirmar com o Financeiro que não há cobranças futuras programadas"),
            _item("Arquivar contrato, aditivos, notificação enviada e comprovante"),
            _item("Encerrar formalmente o processo junto ao Financeiro/Jurídico"),
        ]},
        {"titulo": "14. Notificar áreas sobre a desativação", "gate": True, "itens": [
            _item("Confirmar que a desativação técnica (Fase 12) foi concluída"),
            _item("Comunicar as áreas envolvidas sobre a desativação"),
            _item("Reforçar o canal de suporte para dúvidas sobre a ferramenta nova"),
            _item("Registrar o encerramento do processo de cancelamento como concluído"),
        ]},
    ]


# ═══════════════════════════════════════════════════════════════════
# FIRESTORE — CRUD
# ═══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=20, show_spinner=False)
def listar_iniciativas_playbook_db() -> list:
    """Lista leve (id + nome), usada só pra montar o seletor."""
    docs = get_db().collection(COL_INICIATIVAS).stream()
    out = [{"id": d.id, "nome": d.to_dict().get("nome", "(sem nome)")} for d in docs]
    return sorted(out, key=lambda x: x["nome"])


def obter_iniciativa_playbook_db(iniciativa_id: str) -> dict:
    """Sem cache: a iniciativa ativa muda a cada clique de status/nota."""
    doc = get_db().collection(COL_INICIATIVAS).document(iniciativa_id).get()
    if not doc.exists:
        return None
    d = doc.to_dict()
    d["id"] = doc.id
    return d


def criar_iniciativa_playbook_db(nome: str, ferramenta="", solucao="") -> str:
    ref = get_db().collection(COL_INICIATIVAS).document()
    ref.set({
        "nome": nome, "ferramenta": ferramenta, "solucao": solucao,
        "responsavel": "", "custo_mensal": 0.0,
        "criado_em": _agora_iso(), "fases": modelo_base_fases(),
    })
    listar_iniciativas_playbook_db.clear()
    return ref.id


def renomear_iniciativa_playbook_db(iniciativa_id: str, novo_nome: str):
    get_db().collection(COL_INICIATIVAS).document(iniciativa_id).update({"nome": novo_nome})
    listar_iniciativas_playbook_db.clear()


def atualizar_meta_iniciativa_db(iniciativa_id: str, **campos):
    get_db().collection(COL_INICIATIVAS).document(iniciativa_id).update(campos)


def atualizar_item_playbook_db(iniciativa_id: str, fase_idx: int, item_idx: int, **campos):
    """
    O Firestore não atualiza um único elemento de um array aninhado
    via dot-path — por isso lê o documento inteiro, altera o item em
    memória e regrava o campo 'fases' completo. Como é tudo texto (sem
    os binários dos anexos, que ficam em outra coleção), o documento
    fica bem abaixo do limite de 1 MiB mesmo com muitas iniciativas.
    """
    ini = obter_iniciativa_playbook_db(iniciativa_id)
    if not ini:
        return
    ini["fases"][fase_idx]["itens"][item_idx].update(campos)
    get_db().collection(COL_INICIATIVAS).document(iniciativa_id).update({"fases": ini["fases"]})


def excluir_iniciativa_playbook_db(iniciativa_id: str):
    db = get_db()
    # remove também os anexos binários associados, pra não deixar lixo órfão
    anexos = db.collection(COL_ANEXOS).where("iniciativa_id", "==", iniciativa_id).stream()
    for a in anexos:
        a.reference.delete()
    db.collection(COL_INICIATIVAS).document(iniciativa_id).delete()
    listar_iniciativas_playbook_db.clear()


def salvar_anexo_item_db(iniciativa_id, fase_idx, item_idx, arquivo_bytes, nome_arquivo, tipo, enviado_por):
    if len(arquivo_bytes) > TAMANHO_MAX_ANEXO:
        return False, f"Arquivo muito grande ({len(arquivo_bytes)//1000} KB) — limite de {TAMANHO_MAX_ANEXO//1000} KB por anexo."

    db = get_db()
    ref_anexo = db.collection(COL_ANEXOS).document()
    ref_anexo.set({
        "bin": arquivo_bytes, "nome_arquivo": nome_arquivo, "tipo": tipo,
        "tamanho": len(arquivo_bytes), "iniciativa_id": iniciativa_id,
        "enviado_por": enviado_por, "enviado_em": _agora_str(),
    })

    ini = obter_iniciativa_playbook_db(iniciativa_id)
    anexos = ini["fases"][fase_idx]["itens"][item_idx].setdefault("anexos", [])
    anexos.append({
        "id": ref_anexo.id, "nome_arquivo": nome_arquivo, "tipo": tipo,
        "tamanho": len(arquivo_bytes), "enviado_por": enviado_por, "enviado_em": _agora_str(),
    })
    db.collection(COL_INICIATIVAS).document(iniciativa_id).update({"fases": ini["fases"]})
    return True, "Anexo enviado."


def baixar_anexo_db(anexo_id: str):
    doc = get_db().collection(COL_ANEXOS).document(anexo_id).get()
    return doc.to_dict() if doc.exists else None


def excluir_anexo_item_db(iniciativa_id, fase_idx, item_idx, anexo_id):
    db = get_db()
    db.collection(COL_ANEXOS).document(anexo_id).delete()
    ini = obter_iniciativa_playbook_db(iniciativa_id)
    item = ini["fases"][fase_idx]["itens"][item_idx]
    item["anexos"] = [a for a in item.get("anexos", []) if a["id"] != anexo_id]
    db.collection(COL_INICIATIVAS).document(iniciativa_id).update({"fases": ini["fases"]})


# ═══════════════════════════════════════════════════════════════════
# CÁLCULOS
# ═══════════════════════════════════════════════════════════════════
def _progresso_fase(fase: dict) -> tuple:
    total = len(fase["itens"])
    feitos = sum(1 for i in fase["itens"] if i["status"] in ("feito", "na"))
    return feitos, total


def moeda(v: float) -> str:
    return f"R$ {v:,.0f}".replace(",", ".")


# ═══════════════════════════════════════════════════════════════════
# CSS — visual "painel de controle" (mesmo estilo do protótipo em HTML),
# com variante clara. Escopado dentro de .pb-wrap pra não vazar pros
# outros módulos do Painel.
# ═══════════════════════════════════════════════════════════════════
def _injetar_css(tema: str):
    if tema == "escuro":
        bg, painel, linha = "#11161c", "#1a222b", "#2b3846"
        texto, muted, muted_dim = "#e9edf1", "#8b98a5", "#5f6b78"
    else:
        bg, painel, linha = "#eef1f4", "#ffffff", "#d7dee5"
        texto, muted, muted_dim = "#1b232c", "#5c6b7a", "#8b98a5"

    st.markdown(f"""
    <style>
    .pb-wrap {{
        background:
            linear-gradient({bg}, {bg}),
            repeating-linear-gradient(0deg, transparent, transparent 27px, rgba(120,120,120,0.06) 27px, rgba(120,120,120,0.06) 28px),
            repeating-linear-gradient(90deg, transparent, transparent 27px, rgba(120,120,120,0.05) 27px, rgba(120,120,120,0.05) 28px);
        color:{texto}; padding:20px 22px; border-radius:6px; margin-bottom:14px;
        font-family:'IBM Plex Sans', sans-serif;
    }}
    .pb-wrap .pb-id {{ font-family:'IBM Plex Mono', monospace; font-size:0.7rem; color:{muted_dim}; letter-spacing:0.06em; margin-bottom:6px; }}
    .pb-wrap h2 {{ font-family:'Space Grotesk', sans-serif; font-weight:700; margin:0 0 4px; color:{texto}; }}
    .pb-kpi-strip {{ display:grid; grid-template-columns:repeat(4,1fr); gap:1px; background:{linha}; border:1px solid {linha}; margin:16px 0; }}
    .pb-kpi {{ background:{painel}; padding:14px 16px; }}
    .pb-kpi-label {{ font-family:'IBM Plex Mono', monospace; font-size:0.64rem; color:{muted}; letter-spacing:0.03em; margin-bottom:6px; }}
    .pb-kpi-value {{ font-family:'Space Grotesk', sans-serif; font-size:1.3rem; font-weight:700; color:{texto}; }}
    .pb-kpi.accent .pb-kpi-value {{ color:#e8a33d; }}
    .pb-kpi.teal .pb-kpi-value {{ color:#4fb8ae; }}
    .pb-progress-track {{ height:6px; background:{linha}; border-radius:3px; overflow:hidden; margin-bottom:4px; }}
    .pb-progress-fill {{ height:100%; background:#e8a33d; }}
    .pb-gate {{ padding:8px 12px; border:1px dashed #d9695f; color:#d9695f; font-family:'IBM Plex Mono',monospace; font-size:0.75rem; border-radius:4px; margin-bottom:10px; }}
    .pb-item-status {{ font-family:'IBM Plex Mono', monospace; font-size:0.68rem; padding:2px 8px; border-radius:3px; display:inline-block; }}
    .pb-footer {{ font-family:'IBM Plex Mono', monospace; font-size:0.7rem; color:{muted_dim}; line-height:1.6; margin-top:10px; }}
    </style>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════
def renderizar_playbook(papel, user=None):
    user = user or {}
    login = user.get("usuario", "")

    if "pb_tema" not in st.session_state:
        st.session_state.pb_tema = "escuro"

    _injetar_css(st.session_state.pb_tema)

    st.markdown('<div class="pb-wrap">', unsafe_allow_html=True)
    st.markdown('<div class="pb-id">PLAYBOOK · REDUÇÃO DE CUSTO POR INTERNALIZAÇÃO</div>', unsafe_allow_html=True)
    st.markdown('<h2>Ferramenta externa → solução interna</h2>', unsafe_allow_html=True)

    topo1, topo2, topo3, topo4, topo5 = st.columns([2.4, 1, 1, 1, 0.8])

    iniciativas = listar_iniciativas_playbook_db()

    with topo1:
        if iniciativas:
            opcoes = {i["nome"]: i["id"] for i in iniciativas}
            nome_escolhido = st.selectbox("Iniciativa", list(opcoes.keys()), label_visibility="collapsed")
            iniciativa_id = opcoes[nome_escolhido]
        else:
            iniciativa_id = None
            st.caption("Nenhuma iniciativa criada ainda.")

    with topo2:
        if st.button("+ Nova iniciativa", use_container_width=True):
            st.session_state["pb_criando"] = True

    with topo3:
        if iniciativa_id and st.button("Renomear", use_container_width=True):
            st.session_state["pb_renomeando"] = iniciativa_id

    with topo4:
        if iniciativa_id and st.button("🗑️ Excluir", use_container_width=True):
            st.session_state["pb_confirmando_exclusao"] = iniciativa_id

    with topo5:
        rotulo_tema = "☀️" if st.session_state.pb_tema == "escuro" else "🌙"
        if st.button(rotulo_tema, use_container_width=True, help="Alternar tema claro/escuro"):
            st.session_state.pb_tema = "claro" if st.session_state.pb_tema == "escuro" else "escuro"
            st.rerun()

    if st.session_state.get("pb_criando"):
        with st.form("form_nova_iniciativa"):
            st.markdown("**Nova iniciativa** — nasce com as mesmas 14 fases do modelo.")
            nome = st.text_input("Nome da iniciativa (ex: nome da ferramenta a substituir)")
            c1, c2 = st.columns(2)
            ferramenta = c1.text_input("Ferramenta atual")
            solucao = c2.text_input("Solução interna prevista")
            colA, colB = st.columns(2)
            if colA.form_submit_button("Criar", type="primary"):
                if nome.strip():
                    novo_id = criar_iniciativa_playbook_db(nome.strip(), ferramenta, solucao)
                    st.session_state.pop("pb_criando", None)
                    st.success(f"Iniciativa '{nome}' criada.")
                    st.rerun()
                else:
                    st.error("Informe um nome.")
            if colB.form_submit_button("Cancelar"):
                st.session_state.pop("pb_criando", None)
                st.rerun()

    if st.session_state.get("pb_renomeando") == iniciativa_id and iniciativa_id:
        with st.form("form_renomear"):
            novo_nome = st.text_input("Novo nome", value=nome_escolhido)
            c1, c2 = st.columns(2)
            if c1.form_submit_button("Salvar", type="primary"):
                renomear_iniciativa_playbook_db(iniciativa_id, novo_nome)
                st.session_state.pop("pb_renomeando", None)
                st.rerun()
            if c2.form_submit_button("Cancelar"):
                st.session_state.pop("pb_renomeando", None)
                st.rerun()

    if st.session_state.get("pb_confirmando_exclusao") == iniciativa_id and iniciativa_id:
        st.warning(f"Excluir **{nome_escolhido}** e todo o progresso/anexos? Não é possível desfazer.")
        c1, c2 = st.columns(2)
        if c1.button("Sim, excluir definitivamente", type="primary"):
            excluir_iniciativa_playbook_db(iniciativa_id)
            st.session_state.pop("pb_confirmando_exclusao", None)
            st.rerun()
        if c2.button("Cancelar exclusão"):
            st.session_state.pop("pb_confirmando_exclusao", None)
            st.rerun()

    if not iniciativa_id:
        st.markdown('</div>', unsafe_allow_html=True)
        st.info("Crie a primeira iniciativa pra começar (ex: a que você já está tocando com o Amplifique.me).")
        return

    ini = obter_iniciativa_playbook_db(iniciativa_id)
    if not ini:
        st.markdown('</div>', unsafe_allow_html=True)
        st.error("Iniciativa não encontrada (pode ter sido excluída em outra sessão).")
        return

    # ── Campos de contexto ──
    with st.form("form_meta", border=False):
        m1, m2, m3, m4, m5 = st.columns([2, 2, 2, 1.4, 1])
        v_ferramenta = m1.text_input("Ferramenta atual", value=ini.get("ferramenta", ""))
        v_solucao = m2.text_input("Solução interna", value=ini.get("solucao", ""))
        v_responsavel = m3.text_input("Responsável", value=ini.get("responsavel", ""))
        v_custo = m4.number_input("Custo atual (R$/mês)", min_value=0.0, step=50.0, value=float(ini.get("custo_mensal", 0)))
        if m5.form_submit_button("Salvar", use_container_width=True):
            atualizar_meta_iniciativa_db(iniciativa_id, ferramenta=v_ferramenta, solucao=v_solucao,
                                          responsavel=v_responsavel, custo_mensal=v_custo)
            st.rerun()

    fases = ini["fases"]
    progressos = [_progresso_fase(f) for f in fases]
    total_itens = sum(t for _, t in progressos)
    total_feitos = sum(f for f, _ in progressos)
    pct_geral = round(100 * total_feitos / total_itens) if total_itens else 0
    fases_completas = sum(1 for f, t in progressos if t > 0 and f == t)
    fase_atual_idx = next((idx for idx, (f, t) in enumerate(progressos) if f < t), None)
    fase7_completa = progressos[6][0] == progressos[6][1]

    st.markdown(f"""
    <div class="pb-kpi-strip">
      <div class="pb-kpi"><div class="pb-kpi-label">FASE ATUAL</div>
        <div class="pb-kpi-value" style="font-size:0.95rem;">{fases[fase_atual_idx]['titulo'].split('. ',1)[-1] if fase_atual_idx is not None else 'Concluído 🎉'}</div></div>
      <div class="pb-kpi accent"><div class="pb-kpi-label">PROGRESSO GERAL</div><div class="pb-kpi-value">{pct_geral}%</div></div>
      <div class="pb-kpi teal"><div class="pb-kpi-label">FASES CONCLUÍDAS</div><div class="pb-kpi-value">{fases_completas}/{len(fases)}</div></div>
      <div class="pb-kpi"><div class="pb-kpi-label">ECONOMIA ANUAL PROJETADA</div><div class="pb-kpi-value">{moeda(ini.get('custo_mensal',0)*12)}</div></div>
    </div>
    <div class="pb-progress-track"><div class="pb-progress-fill" style="width:{pct_geral}%"></div></div>
    """, unsafe_allow_html=True)

    # ── Fases ──
    for fi, fase in enumerate(fases):
        feitos, total = progressos[fi]
        rotulo = f"{fase['titulo']}  ·  {feitos}/{total}" + ("  ✅" if total and feitos == total else "")
        with st.expander(rotulo, expanded=(fi == fase_atual_idx)):
            if fase.get("gate") and not fase7_completa:
                st.markdown('<div class="pb-gate">⚠ Formalizar só após aprovação da Fase 7 — Estabilização</div>', unsafe_allow_html=True)

            for ii, item_ in enumerate(fase["itens"]):
                c_texto, c_status, c_detalhe = st.columns([3.4, 1.1, 0.5])
                cor = STATUS_COR[item_["status"]]
                riscado = "text-decoration:line-through;opacity:.65;" if item_["status"] == "feito" else ""
                c_texto.markdown(f'<div style="font-size:0.87rem;{riscado}">{item_["texto"]}</div>', unsafe_allow_html=True)

                novo_status = c_status.selectbox(
                    "status", STATUS_OPCOES, index=STATUS_OPCOES.index(item_["status"]),
                    format_func=lambda v: STATUS_LABEL[v], label_visibility="collapsed",
                    key=f"status_{iniciativa_id}_{fi}_{ii}",
                )
                if novo_status != item_["status"]:
                    atualizar_item_playbook_db(iniciativa_id, fi, ii, status=novo_status)
                    st.rerun()

                n_anexos = len(item_.get("anexos", []))
                rotulo_pop = f"🗒️{'·'+str(n_anexos) if n_anexos else ''}"
                with c_detalhe.popover(rotulo_pop, use_container_width=True):
                    st.markdown("**Nota interna**")
                    nota_key = f"nota_{iniciativa_id}_{fi}_{ii}"
                    nova_nota = st.text_area("Nota interna", value=item_.get("nota_interna", ""),
                                              label_visibility="collapsed", key=nota_key, height=80)
                    if st.button("Salvar nota", key=f"btn_nota_{iniciativa_id}_{fi}_{ii}"):
                        atualizar_item_playbook_db(iniciativa_id, fi, ii, nota_interna=nova_nota)
                        st.success("Nota salva.")
                        st.rerun()

                    st.markdown("---")
                    st.markdown("**Anexos**")
                    for anexo in item_.get("anexos", []):
                        ac1, ac2 = st.columns([3, 1])
                        ac1.caption(f"📎 {anexo['nome_arquivo']} ({anexo['tamanho']//1000} KB) · {anexo.get('enviado_por','')}")
                        if ac2.button("baixar", key=f"dl_{anexo['id']}"):
                            dados = baixar_anexo_db(anexo["id"])
                            if dados:
                                st.download_button(
                                    "confirmar download", data=dados["bin"], file_name=dados["nome_arquivo"],
                                    mime=dados.get("tipo") or "application/octet-stream",
                                    key=f"dlconfirm_{anexo['id']}",
                                )
                        if ac2.button("excluir", key=f"delanexo_{anexo['id']}"):
                            excluir_anexo_item_db(iniciativa_id, fi, ii, anexo["id"])
                            st.rerun()

                    novo_arquivo = st.file_uploader("Anexar arquivo", key=f"upload_{iniciativa_id}_{fi}_{ii}")
                    if novo_arquivo is not None:
                        if st.button("Enviar anexo", key=f"btn_upload_{iniciativa_id}_{fi}_{ii}"):
                            tipo, _ = mimetypes.guess_type(novo_arquivo.name)
                            ok, msg = salvar_anexo_item_db(
                                iniciativa_id, fi, ii, novo_arquivo.getvalue(), novo_arquivo.name,
                                tipo or "application/octet-stream", login,
                            )
                            (st.success if ok else st.error)(msg)
                            if ok:
                                st.rerun()

    st.markdown(
        '<div class="pb-footer">As fases 11–14 (aviso formal, desativação e encerramento) só devem ser '
        'oficializadas depois da aprovação da Fase 7 — Estabilização. As fases 8–10 (revisão contratual, '
        'situação financeira, backup) podem ser adiantadas em paralelo à construção.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)
