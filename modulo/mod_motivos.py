"""
KingStar — Cadastro de Motivos (Motivo Pai → Motivo Filho → Etapa)
─────────────────────────────────────────────────────────────────────────────
Árvore de classificação usada pelo módulo de Tickets:

  Motivo Pai   → tem o SLA "de triagem" (ex.: 5 dias). Escolhido na ABERTURA
                 do chamado.
  Motivo Filho → agrupa Etapas. Escolhido pelo atendente durante a triagem.
  Etapa        → passo específico dentro do Motivo Filho.
                   - Etapa PRETA:    não exige data. Prazo continua sendo o
                                     do Motivo Pai (SLA1).
                   - Etapa VERMELHA: exige que o atendente informe uma data
                                     futura (SLA2). Uma vez confirmada, a
                                     trilha (Motivo Filho + Etapa + data)
                                     fica TRAVADA para sempre.
                   - Etapa pode "reaproveitar" a árvore de outro Motivo
                     Filho (ex.: "Bloqueio de estoque" dentro de "Troca
                     Adaptação" reaproveita a árvore de "Bloqueio de
                     estoque" cadastrada em Compras), evitando recadastro.
                   - Etapa pode vincular atendentes específicos; ao ser
                     escolhida, o ticket é reatribuído a eles. Sem vínculo,
                     o ticket continua aberto para todo o departamento.
"""
import streamlit as st
import sys
import os

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _root not in sys.path:
    sys.path.insert(0, _root)

from database import get_db, listar_departamentos

COL_PAI   = "motivos_pai"
COL_FILHO = "motivos_filho"
COL_ETAPA = "etapas"


# ── Motivo Pai ──────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def listar_motivos_pai() -> list:
    docs = get_db().collection(COL_PAI).stream()
    return sorted([d.to_dict() for d in docs], key=lambda x: x.get("nome", ""))


def motivos_pai_do_departamento(departamento: str) -> list:
    return [m for m in listar_motivos_pai() if m.get("departamento") == departamento]


def criar_motivo_pai(nome: str, departamento: str, sla_dias: int) -> str:
    ref = get_db().collection(COL_PAI).document()
    ref.set({"id": ref.id, "nome": nome, "departamento": departamento,
              "sla_dias": int(sla_dias)})
    listar_motivos_pai.clear()
    return ref.id


def atualizar_motivo_pai(mid: str, nome: str, departamento: str, sla_dias: int):
    get_db().collection(COL_PAI).document(mid).update(
        {"nome": nome, "departamento": departamento, "sla_dias": int(sla_dias)}
    )
    listar_motivos_pai.clear()


def excluir_motivo_pai(mid: str):
    for f in listar_motivos_filho_de(mid):
        excluir_motivo_filho(f["id"])
    get_db().collection(COL_PAI).document(mid).delete()
    listar_motivos_pai.clear()


# ── Motivo Filho ────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def listar_motivos_filho() -> list:
    docs = get_db().collection(COL_FILHO).stream()
    return sorted([d.to_dict() for d in docs], key=lambda x: x.get("nome", ""))


def listar_motivos_filho_de(motivo_pai_id: str) -> list:
    if not motivo_pai_id:
        return []
    return [m for m in listar_motivos_filho() if m.get("motivo_pai_id") == motivo_pai_id]


def criar_motivo_filho(nome: str, motivo_pai_id: str, motivo_pai_nome: str) -> str:
    ref = get_db().collection(COL_FILHO).document()
    ref.set({"id": ref.id, "nome": nome, "motivo_pai_id": motivo_pai_id,
              "motivo_pai_nome": motivo_pai_nome})
    listar_motivos_filho.clear()
    return ref.id


def excluir_motivo_filho(fid: str):
    for e in listar_etapas_de(fid):
        get_db().collection(COL_ETAPA).document(e["id"]).delete()
    get_db().collection(COL_FILHO).document(fid).delete()
    listar_motivos_filho.clear()
    listar_etapas.clear()


# ── Etapa ───────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def listar_etapas() -> list:
    docs = get_db().collection(COL_ETAPA).stream()
    return sorted([d.to_dict() for d in docs], key=lambda x: x.get("ordem", 0))


def listar_etapas_de(motivo_filho_id: str) -> list:
    if not motivo_filho_id:
        return []
    return [e for e in listar_etapas() if e.get("motivo_filho_id") == motivo_filho_id]


def criar_etapa(nome: str, motivo_filho_id: str, requer_data: bool,
                 reaproveita_motivo_filho_id: str, atendentes_vinculados: list,
                 ordem: int) -> str:
    ref = get_db().collection(COL_ETAPA).document()
    ref.set({
        "id": ref.id, "nome": nome, "motivo_filho_id": motivo_filho_id,
        "requer_data": bool(requer_data),
        "reaproveita_motivo_filho_id": reaproveita_motivo_filho_id or "",
        "atendentes_vinculados": atendentes_vinculados or [],
        "ordem": int(ordem),
    })
    listar_etapas.clear()
    return ref.id


def excluir_etapa(eid: str):
    get_db().collection(COL_ETAPA).document(eid).delete()
    listar_etapas.clear()


def resolver_etapa_final(motivo_filho_id: str, caminho_nomes: list):
    """Segue a cadeia de reaproveitamentos a partir de um Motivo Filho e de
    uma lista de nomes de etapa (um por nível) e retorna (etapa_obj_final,
    motivo_filho_final) ou (None, None) se não encontrar."""
    filho_id = motivo_filho_id
    etapa_final = None
    for nome_etapa in caminho_nomes:
        etapas = listar_etapas_de(filho_id)
        etapa = next((e for e in etapas if e["nome"] == nome_etapa), None)
        if not etapa:
            return None, None
        etapa_final = etapa
        if etapa.get("reaproveita_motivo_filho_id"):
            filho_id = etapa["reaproveita_motivo_filho_id"]
        else:
            break
    return etapa_final, filho_id


# ── UI de cadastro (somente ADM) ─────────────────────────────────────
def renderizar_motivos(papel: str, usuarios_disponiveis: list = None):
    if papel != "adm":
        st.warning("🔒 Acesso restrito a Administradores.")
        return

    st.markdown("## 🗂️ Motivos, Motivos Filho e Etapas")
    st.caption(
        "Motivo Pai carrega o SLA de triagem (ex.: 5 dias). Motivo Filho e Etapa são "
        "escolhidos pelo atendente durante o atendimento. Etapas em 🔴 exigem uma data "
        "futura (2º SLA) e, ao serem confirmadas, travam a trilha do ticket."
    )

    aba_pai, aba_filho, aba_etapa = st.tabs(
        ["🅰️ Motivo Pai", "🅱️ Motivo Filho", "🔤 Etapas"]
    )

    deps = [d["nome"] for d in listar_departamentos()]

    # ── Motivo Pai ──
    with aba_pai:
        st.markdown("#### Novo Motivo Pai")
        if not deps:
            st.warning("Cadastre um Departamento antes.")
        else:
            with st.form("form_novo_pai", clear_on_submit=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                nome = c1.text_input("Nome *", placeholder="Ex: Pedido")
                dep = c2.selectbox("Departamento *", deps)
                sla = c3.number_input("SLA (dias)", min_value=1, value=5)
                if st.form_submit_button("➕ Adicionar", type="primary"):
                    if not nome.strip():
                        st.error("Informe o nome.")
                    else:
                        criar_motivo_pai(nome.strip(), dep, sla)
                        st.success("Motivo Pai criado!"); st.rerun()
        st.markdown("---")
        for m in listar_motivos_pai():
            c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
            c1.markdown(f"**{m['nome']}**")
            c2.caption(f"🏢 {m.get('departamento', '—')}")
            c3.caption(f"⏱ {m.get('sla_dias', 5)}d")
            if c4.button("🗑️", key=f"delpai_{m['id']}"):
                excluir_motivo_pai(m["id"]); st.rerun()

    # ── Motivo Filho ──
    with aba_filho:
        st.markdown("#### Novo Motivo Filho")
        pais = listar_motivos_pai()
        if not pais:
            st.info("Cadastre um Motivo Pai primeiro.")
        else:
            with st.form("form_novo_filho", clear_on_submit=True):
                pai_nomes = [p["nome"] for p in pais]
                pai_sel = st.selectbox("Motivo Pai *", pai_nomes)
                nome_f = st.text_input("Nome do Motivo Filho *")
                if st.form_submit_button("➕ Adicionar", type="primary"):
                    pai_obj = next(p for p in pais if p["nome"] == pai_sel)
                    if not nome_f.strip():
                        st.error("Informe o nome.")
                    else:
                        criar_motivo_filho(nome_f.strip(), pai_obj["id"], pai_obj["nome"])
                        st.success("Motivo Filho criado!"); st.rerun()
            st.markdown("---")
            for p in pais:
                filhos = listar_motivos_filho_de(p["id"])
                if filhos:
                    st.markdown(f"**{p['nome']}**")
                    for f in filhos:
                        c1, c2 = st.columns([5, 1])
                        c1.caption(f"↳ {f['nome']}")
                        if c2.button("🗑️", key=f"delfilho_{f['id']}"):
                            excluir_motivo_filho(f["id"]); st.rerun()

    # ── Etapas ──
    with aba_etapa:
        st.markdown("#### Nova Etapa")
        filhos = listar_motivos_filho()
        if not filhos:
            st.info("Cadastre um Motivo Filho primeiro.")
        else:
            with st.form("form_nova_etapa", clear_on_submit=True):
                filho_labels = {f["id"]: f"{f['motivo_pai_nome']} → {f['nome']}" for f in filhos}
                filho_sel = st.selectbox(
                    "Motivo Filho *", list(filho_labels.keys()),
                    format_func=lambda x: filho_labels[x]
                )
                nome_e = st.text_input("Nome da Etapa *")
                requer_data = st.checkbox(
                    "🔴 Etapa vermelha (exige data futura / abre 2º SLA e trava o ticket)"
                )
                opcoes_reap = ["— nenhum —"] + [f["id"] for f in filhos if f["id"] != filho_sel]
                reaproveita = st.selectbox(
                    "Reaproveitar a árvore de outro Motivo Filho (opcional)",
                    opcoes_reap,
                    format_func=lambda x: "— nenhum —" if x == "— nenhum —" else filho_labels[x]
                )
                atend_opts = [u.get("usuario", "") for u in (usuarios_disponiveis or [])]
                atend_vinc = st.multiselect(
                    "Vincular a atendentes específicos (opcional — vazio = todo o departamento)",
                    atend_opts
                )
                if st.form_submit_button("➕ Adicionar", type="primary"):
                    if not nome_e.strip():
                        st.error("Informe o nome da etapa.")
                    else:
                        criar_etapa(
                            nome_e.strip(), filho_sel, requer_data,
                            None if reaproveita == "— nenhum —" else reaproveita,
                            atend_vinc, ordem=len(listar_etapas_de(filho_sel))
                        )
                        st.success("Etapa criada!"); st.rerun()
            st.markdown("---")
            for f in filhos:
                etapas = listar_etapas_de(f["id"])
                if etapas:
                    st.markdown(f"**{f['motivo_pai_nome']} → {f['nome']}**")
                    for e in etapas:
                        cor = "🔴" if e.get("requer_data") else "⚫"
                        reap = ""
                        if e.get("reaproveita_motivo_filho_id"):
                            alvo = next((x for x in filhos if x["id"] == e["reaproveita_motivo_filho_id"]), None)
                            if alvo:
                                reap = f" ↪️ reaproveita **{alvo['nome']}**"
                        vinc = (f" · 👤 {', '.join(e['atendentes_vinculados'])}"
                                if e.get("atendentes_vinculados") else "")
                        c1, c2 = st.columns([6, 1])
                        c1.caption(f"{cor} {e['nome']}{reap}{vinc}")
                        if c2.button("🗑️", key=f"deletapa_{e['id']}"):
                            excluir_etapa(e["id"]); st.rerun()
