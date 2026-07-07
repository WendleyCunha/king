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


def criar_motivo_pai(nome: str, departamento: str, sla_dias: int, prioridade: str = "normal") -> str:
    ref = get_db().collection(COL_PAI).document()
    ref.set({"id": ref.id, "nome": nome, "departamento": departamento,
              "sla_dias": int(sla_dias), "prioridade": prioridade})
    listar_motivos_pai.clear()
    return ref.id


def atualizar_motivo_pai(mid: str, nome: str, departamento: str, sla_dias: int, prioridade: str = "normal"):
    get_db().collection(COL_PAI).document(mid).update(
        {"nome": nome, "departamento": departamento, "sla_dias": int(sla_dias),
         "prioridade": prioridade}
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


def atualizar_motivo_filho(fid: str, nome: str):
    get_db().collection(COL_FILHO).document(fid).update({"nome": nome})
    listar_motivos_filho.clear()


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


def atualizar_etapa(eid: str, nome: str, requer_data: bool,
                     reaproveita_motivo_filho_id: str, atendentes_vinculados: list):
    get_db().collection(COL_ETAPA).document(eid).update({
        "nome": nome,
        "requer_data": bool(requer_data),
        "reaproveita_motivo_filho_id": reaproveita_motivo_filho_id or "",
        "atendentes_vinculados": atendentes_vinculados or [],
    })
    listar_etapas.clear()


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
        "Motivo Pai carrega o SLA de triagem (ex.: 5 dias) e a Prioridade do chamado. "
        "Motivo Filho e Etapa são escolhidos pelo atendente durante o atendimento. "
        "Etapas em 🔴 exigem uma data futura (2º SLA) e, ao serem confirmadas, travam "
        "a trilha do ticket."
    )

    aba_pai, aba_filho, aba_etapa = st.tabs(
        ["🅰️ Motivo Pai", "🅱️ Motivo Filho", "🔤 Etapas"]
    )

    deps = [d["nome"] for d in listar_departamentos()]
    prio_opts = ["urgente", "alta", "normal", "baixa"]
    prio_labels = {"urgente": "Urgente", "alta": "Alta", "normal": "Normal", "baixa": "Baixa"}

    # ── Motivo Pai ──
    with aba_pai:
        st.markdown("#### Novo Motivo Pai")
        if not deps:
            st.warning("Cadastre um Departamento antes.")
        else:
            with st.form("form_novo_pai", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                nome = c1.text_input("Nome *", placeholder="Ex: Pedido")
                dep = c2.selectbox("Departamento *", deps)
                sla = c3.number_input("SLA (dias)", min_value=1, value=5)
                prio = c4.selectbox("Prioridade", prio_opts, index=2,
                                    format_func=lambda x: prio_labels[x])
                if st.form_submit_button("➕ Adicionar", type="primary"):
                    if not nome.strip():
                        st.error("Informe o nome.")
                    else:
                        criar_motivo_pai(nome.strip(), dep, sla, prio)
                        st.success("Motivo Pai criado!"); st.rerun()
        st.markdown("---")
        for m in listar_motivos_pai():
            with st.expander(
                f"**{m['nome']}** · 🏢 {m.get('departamento','—')} · "
                f"⏱ {m.get('sla_dias', 5)}d · 🎯 {prio_labels.get(m.get('prioridade','normal'), 'Normal')}"
            ):
                with st.form(f"edit_pai_{m['id']}"):
                    e1, e2, e3, e4 = st.columns([2, 1, 1, 1])
                    novo_nome = e1.text_input("Nome", value=m["nome"], key=f"pnome_{m['id']}")
                    novo_dep = e2.selectbox(
                        "Departamento", deps,
                        index=deps.index(m["departamento"]) if m.get("departamento") in deps else 0,
                        key=f"pdep_{m['id']}"
                    )
                    novo_sla = e3.number_input("SLA (dias)", min_value=1,
                                               value=int(m.get("sla_dias", 5)), key=f"psla_{m['id']}")
                    novo_prio = e4.selectbox(
                        "Prioridade", prio_opts,
                        index=prio_opts.index(m.get("prioridade", "normal")) if m.get("prioridade") in prio_opts else 2,
                        format_func=lambda x: prio_labels[x], key=f"pprio_{m['id']}"
                    )
                    b1, b2 = st.columns(2)
                    if b1.form_submit_button("💾 Salvar", type="primary", use_container_width=True):
                        atualizar_motivo_pai(m["id"], novo_nome.strip(), novo_dep, novo_sla, novo_prio)
                        st.success("Atualizado!"); st.rerun()
                    if b2.form_submit_button("🗑️ Excluir", use_container_width=True):
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
                        with st.expander(f"↳ {f['nome']}"):
                            with st.form(f"edit_filho_{f['id']}"):
                                novo_nome_f = st.text_input("Nome", value=f["nome"], key=f"fnome_{f['id']}")
                                b1, b2 = st.columns(2)
                                if b1.form_submit_button("💾 Salvar", type="primary", use_container_width=True):
                                    atualizar_motivo_filho(f["id"], novo_nome_f.strip())
                                    st.success("Atualizado!"); st.rerun()
                                if b2.form_submit_button("🗑️ Excluir", use_container_width=True):
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
                        reap_atual = e.get("reaproveita_motivo_filho_id") or ""
                        reap_nome = ""
                        if reap_atual:
                            alvo = next((x for x in filhos if x["id"] == reap_atual), None)
                            if alvo:
                                reap_nome = f" ↪️ reaproveita **{alvo['nome']}**"
                        vinc = (f" · 👤 {', '.join(e['atendentes_vinculados'])}"
                                if e.get("atendentes_vinculados") else "")
                        with st.expander(f"{cor} {e['nome']}{reap_nome}{vinc}"):
                            with st.form(f"edit_etapa_{e['id']}"):
                                novo_nome_e = st.text_input("Nome", value=e["nome"], key=f"enome_{e['id']}")
                                novo_requer = st.checkbox(
                                    "🔴 Etapa vermelha (exige data futura / 2º SLA)",
                                    value=bool(e.get("requer_data")), key=f"ereq_{e['id']}"
                                )
                                opcoes_reap_e = ["— nenhum —"] + [x["id"] for x in filhos if x["id"] != f["id"]]
                                idx_reap = opcoes_reap_e.index(reap_atual) if reap_atual in opcoes_reap_e else 0
                                novo_reap = st.selectbox(
                                    "Reaproveitar árvore de outro Motivo Filho", opcoes_reap_e,
                                    index=idx_reap,
                                    format_func=lambda x: "— nenhum —" if x == "— nenhum —" else filho_labels.get(x, x),
                                    key=f"ereap_{e['id']}"
                                )
                                novo_vinc = st.multiselect(
                                    "Vincular a atendentes específicos (vazio = todo o departamento)",
                                    atend_opts, default=e.get("atendentes_vinculados", []),
                                    key=f"evinc_{e['id']}"
                                )
                                b1, b2 = st.columns(2)
                                if b1.form_submit_button("💾 Salvar", type="primary", use_container_width=True):
                                    atualizar_etapa(
                                        e["id"], novo_nome_e.strip(), novo_requer,
                                        None if novo_reap == "— nenhum —" else novo_reap,
                                        novo_vinc
                                    )
                                    st.success("Atualizado!"); st.rerun()
                                if b2.form_submit_button("🗑️ Excluir", use_container_width=True):
                                    excluir_etapa(e["id"]); st.rerun()
