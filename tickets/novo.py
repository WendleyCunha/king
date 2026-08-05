"""
KingStar — Módulo de Tickets — novo.py
─────────────────────────────────────────────────────────────────────────────
Tela de abertura de um novo chamado: escolha de Departamento + Motivo Pai
(que já carrega o SLA1 de triagem), dados do cliente (com aviso de
histórico já existente pra aquele código) e vínculo automático de
pendência de setor quando o Motivo tem "departamento_vinculado".

[v5] Desde a mudança para "ticket contêiner por cliente" (ver
tickets/common.py), esta tela passou a:
  • Usar `abrir_solicitacao_cliente` (em vez de `criar_ticket` direto), que
    aplica o bloqueio de motivo duplicado (Regra 2) de forma atômica.
  • Avisar PROATIVAMENTE, antes mesmo de tentar enviar, se o motivo
    escolhido já está em aberto para aquele cliente — e desabilita o botão
    de envio nesse caso, para poupar o clique (a checagem definitiva, à
    prova de corrida entre duas aberturas simultâneas, continua acontecendo
    no servidor dentro de `abrir_solicitacao_cliente`).
  • Não usa mais `vincular_ticket_relacionado` nem `tickets_relacionados`:
    como toda solicitação do mesmo cliente já vive no MESMO documento
    contêiner, não existe mais "ticket separado" para linkar.
"""
import time
import streamlit as st

from modulo.mod_motivos import motivos_pai_do_departamento
from .common import (
    STATUS_ABERTOS, STATUS_CFG, STATUS_ENCERRADOS_DUPLICIDADE, esc, _html,
    listar_departamentos, normalizar_codigo_cliente, tickets_do_cliente,
    abrir_solicitacao_cliente, registrar_solicitacao_setor,
    _render_bloco_historico_cliente,
)


def _solicitacao_conflitante(tickets_cliente: list, nome_motivo: str):
    """Verifica, ENTRE as solicitações já existentes do cliente, se alguma
    tem o MESMO Motivo Pai e ainda não está encerrada — mesma regra que
    `abrir_solicitacao_cliente` aplica no servidor, usada aqui só para
    avisar o atendente ANTES de ele tentar enviar."""
    alvo = (nome_motivo or "").strip().lower()
    if not alvo:
        return None
    for tc in tickets_cliente:
        if (tc.get("motivo_pai") or "").strip().lower() == alvo \
                and tc.get("status") not in STATUS_ENCERRADOS_DUPLICIDADE:
            return tc
    return None


def _render_novo(user):
    st.markdown("### ➕ Abrir Novo Chamado")
    if st.button("← Voltar"):
        st.session_state.tk_modo = "lista"; st.rerun()

    deps = listar_departamentos()
    dep_nomes = [d["nome"] for d in deps]
    if not dep_nomes:
        st.warning("⚠️ Nenhum departamento cadastrado. Peça ao administrador para criar em "
                   "Configurações → Departamentos.")
        return

    dep_sel = st.selectbox("Departamento *", dep_nomes, key="novo_dep")

    pais_dep = motivos_pai_do_departamento(dep_sel)
    if not pais_dep:
        st.info("Este departamento ainda não tem Motivos cadastrados. Peça ao administrador "
                "para cadastrar em Configurações → Motivos. Será usado um SLA padrão de 5 dias.")
        motivo_obj = None
        sla_dias = 5
    else:
        pai_nomes = [m["nome"] for m in pais_dep]
        pai_sel = st.selectbox("Motivo *", pai_nomes, key="novo_motivo_pai")
        motivo_obj = next(m for m in pais_dep if m["nome"] == pai_sel)
        sla_dias = int(motivo_obj.get("sla_dias", 5))

    st.caption(f"⏱ Prazo para triagem (1º SLA): **{sla_dias} dia(s)**. O atendente que "
               f"receber o chamado tem esse prazo para analisar e classificar a Etapa correta.")

    dep_vinculado_pai = motivo_obj.get("departamento_vinculado") if motivo_obj else None
    if dep_vinculado_pai and dep_vinculado_pai != dep_sel:
        st.markdown(_html(f"""
        <div class="tk-banner" style="animation:none;background:#EFF6FF;color:#1D4ED8;border-color:#60A5FA;">
            📨 Este motivo é vinculado ao setor <b>{esc(dep_vinculado_pai)}</b> — uma pendência
            será criada automaticamente para eles assim que o chamado for aberto (sem precisar
            solicitar manualmente).
        </div>"""), unsafe_allow_html=True)

    st.markdown("**Dados do cliente**")
    cl1, cl2 = st.columns([1, 2])
    cli_codigo = cl1.text_input("Código do cliente *", placeholder="Ex: 10234", key="novo_cli_codigo")
    cli_nome   = cl2.text_input("Nome do cliente *", placeholder="Ex: João da Silva", key="novo_cli_nome")

    cod_norm = normalizar_codigo_cliente(cli_codigo)
    tickets_cliente = tickets_do_cliente(cod_norm) if cod_norm else []

    conflito = None
    if tickets_cliente:
        abertos_cli = sum(1 for x in tickets_cliente if x.get("status") in STATUS_ABERTOS)
        st.markdown(_html(f"""
        <div class="tk-banner">
            🗂 Este código de cliente já possui <b>{len(tickets_cliente)}</b> solicitação(ões)
            anterior(es){f" ({abertos_cli} em aberto)" if abertos_cli else ""}.
            Uma nova solicitação com motivo diferente entra no MESMO ticket deste cliente,
            junto com todo o histórico — não abre um documento separado.
        </div>"""), unsafe_allow_html=True)
        with st.expander(f"📜 Ver histórico deste cliente ({len(tickets_cliente)} solicitação(ões))"):
            _render_bloco_historico_cliente(tickets_cliente)

        if motivo_obj:
            conflito = _solicitacao_conflitante(tickets_cliente, motivo_obj["nome"])
            if conflito:
                status_lbl = STATUS_CFG.get(conflito.get("status"), (conflito.get("status"),))[0]
                st.error(
                    f"🚫 Este cliente já tem uma solicitação em aberto para o motivo "
                    f"**\"{motivo_obj['nome']}\"** (status: **{status_lbl}**, aberta em "
                    f"{esc(str(conflito.get('criado_em',''))[:16])}). Trate ou encerre essa "
                    f"solicitação antes de abrir outra com o mesmo motivo."
                )
    elif cod_norm:
        st.caption("✅ Nenhuma solicitação anterior encontrada para este código de cliente — será a primeira dele.")

    with st.form("form_novo_ticket", clear_on_submit=True):
        assunto = st.text_input("Assunto *", placeholder="Descreva o problema")
        descricao  = st.text_area("Descrição *", height=120)

        st.caption(f"🙋 Solicitante (automático): **{user.get('nome','—')}**")

        enviar = st.form_submit_button(
            "🚀 Abrir Chamado", type="primary", use_container_width=True,
            disabled=bool(conflito),
        )
        if conflito:
            st.caption("⛔ Envio bloqueado enquanto houver uma solicitação em aberto com este mesmo motivo.")

        if enviar:
            if not assunto.strip() or not descricao.strip():
                st.error("Preencha Assunto e Descrição.")
            elif not cod_norm or not cli_nome.strip():
                st.error("Informe o Código e o Nome do cliente.")
            else:
                ok, msg_erro, novo_id = abrir_solicitacao_cliente({
                    "assunto": assunto.strip(), "descricao": descricao.strip(),
                    "departamento": dep_sel,
                    "categoria": dep_sel,
                    "motivo_pai": motivo_obj["nome"] if motivo_obj else "",
                    "motivo_pai_id": motivo_obj["id"] if motivo_obj else "",
                    "sla1_prazo_dias": sla_dias,
                    "prioridade": (motivo_obj.get("prioridade", "normal") if motivo_obj else "normal"),
                    "atendentes": [],
                    "cliente_codigo": cod_norm,
                    "cliente_nome": cli_nome.strip(),
                    "solicitante_nome": user.get("nome",""),
                    "aberto_por": user.get("usuario",""),
                })

                if not ok:
                    st.error(f"🚫 {msg_erro}")
                else:
                    aviso_pend = ""
                    dep_vinc = motivo_obj.get("departamento_vinculado") if motivo_obj else None
                    if dep_vinc and dep_vinc != dep_sel:
                        registrar_solicitacao_setor(
                            novo_id, {"departamento": dep_sel}, dep_vinc,
                            f"Pendência automática: o motivo '{motivo_obj['nome']}' exige retorno "
                            f"do setor {dep_vinc} para este chamado ser concluído.",
                            user,
                        )
                        aviso_pend = f" 📨 Pendência automática registrada para o setor **{dep_vinc}**."

                    aviso_hist = (f" 🗂 Adicionada ao histórico de {len(tickets_cliente)} "
                                  f"solicitação(ões) anterior(es) deste cliente."
                                  if tickets_cliente else "")
                    st.success(f"✅ Chamado **#{novo_id[:8]}** aberto em **{dep_sel}**! "
                               f"Aguardando triagem.{aviso_hist}{aviso_pend}")
                    st.balloons(); time.sleep(1.5)
                    st.session_state.tk_modo = "lista"; st.rerun()
