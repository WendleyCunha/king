"""
KingStar — Módulo de Tickets — detalhe.py
─────────────────────────────────────────────────────────────────────────────
Painel de detalhe do ticket (hoje renderizado na 3ª coluna, à direita, em
vez de popup): classificação Motivo Filho/Etapa (SLA1 congelado / SLA2
travado), pendências entre setores dentro do próprio ticket, tratativa
(status + comentário), registro de contato/observação avulsa, histórico de
comentários e histórico de classificação, e validação de "Resolvido".
"""
import time
import streamlit as st
from datetime import datetime, timedelta

from modulo.mod_motivos import listar_motivos_filho, listar_motivos_filho_de, listar_etapas_de
from .common import (
    BRT, COLECAO, get_db, STATUS_CFG, PRIO_CFG, GOLD_VENC, GREEN_OK,
    esc, pill, _html, agora_brt, sla_label, sla_restante, deadline_ativo,
    ticket_vencido_pendente, tem_interacao_nao_vista, _caminho_motivo,
    tickets_do_cliente, STATUS_ABERTOS, _atribuido_a, atualizar_ticket,
    adicionar_comentario, cor_departamento, solicitacoes_abertas,
    solicitacoes_abertas_para_setor, ticket_tem_pendencia_para_setor,
    registrar_solicitacao_setor, responder_solicitacao_setor,
    listar_departamentos, _render_bloco_historico_cliente,
)


# ── Classificação Motivo Filho / Etapa (SLA1 + SLA2) ───────────────
def _bloco_classificacao(t, tid, user, papel, pode_agir):
    motivo_pai_nome = t.get("motivo_pai")
    if not motivo_pai_nome:
        return  # ticket antigo/legado (sem árvore de motivos) — não se aplica

    st.markdown("---")
    st.markdown("#### 🗂️ Classificação (Motivo Filho / Etapa)")

    if t.get("etapa_travada"):
        st.markdown(_html(f"""
        <div style="background:#F3ECD9;border:1px solid #A98C3D;border-radius:10px;
                    padding:10px 14px;color:#6B5A2A;">
            🔒 <b>{esc(motivo_pai_nome)} › {esc(t.get('motivo_filho',''))} › {esc(t.get('etapa_atual',''))}</b><br>
            <span style="font-size:0.8rem;">Prazo desta etapa: <b>{esc(str(t.get('etapa_data_prevista','—')))}</b>
            &nbsp;·&nbsp; Definido em {esc(str(t.get('etapa_definida_em',''))[:16])} por
            {esc(t.get('etapa_definida_por',''))}. Esta trilha não pode mais ser alterada.</span>
        </div>"""), unsafe_allow_html=True)
        return

    if not pode_agir:
        if t.get("motivo_filho"):
            st.caption(f"📂 {esc(motivo_pai_nome)} › {esc(t.get('motivo_filho'))} › {esc(t.get('etapa_atual',''))}")
        else:
            st.caption(f"📂 {esc(motivo_pai_nome)} — aguardando classificação do atendente.")
        return

    filhos = listar_motivos_filho_de(t.get("motivo_pai_id",""))
    if not filhos:
        st.caption("Nenhum Motivo Filho cadastrado para este Motivo Pai ainda "
                   "(cadastre em Configurações → Motivos).")
        return

    filho_nomes = [f["nome"] for f in filhos]
    idx_f = filho_nomes.index(t["motivo_filho"]) if t.get("motivo_filho") in filho_nomes else 0
    filho_sel_nome = st.selectbox("Motivo Filho", filho_nomes, index=idx_f, key=f"mf_{tid}")
    filho_obj = next(f for f in filhos if f["nome"] == filho_sel_nome)

    caminho_salvo = t.get("etapa_atual","").split(" › ") if t.get("etapa_atual") else []
    caminho = []
    filho_atual = filho_obj
    etapa_final = None
    nivel = 0
    while True:
        etapas = listar_etapas_de(filho_atual["id"])
        if not etapas:
            break
        etapa_nomes = [e["nome"] for e in etapas]
        prev_nome = caminho_salvo[nivel] if nivel < len(caminho_salvo) else None
        idx_e = etapa_nomes.index(prev_nome) if prev_nome in etapa_nomes else 0
        label = "Etapa" if nivel == 0 else f"Etapa (nível {nivel+1})"
        etapa_sel_nome = st.selectbox(label, etapa_nomes, index=idx_e, key=f"et_{tid}_{nivel}")
        etapa_obj = next(e for e in etapas if e["nome"] == etapa_sel_nome)
        caminho.append(etapa_obj["nome"])
        if etapa_obj.get("reaproveita_motivo_filho_id"):
            alvo = next((f for f in listar_motivos_filho() if f["id"] == etapa_obj["reaproveita_motivo_filho_id"]), None)
            if not alvo:
                etapa_final = etapa_obj
                break
            filho_atual = alvo
            nivel += 1
            continue
        etapa_final = etapa_obj
        break

    if etapa_final is None:
        st.caption("Este Motivo Filho ainda não tem Etapas cadastradas.")
        return

    dep_proprio = t.get("departamento") or t.get("categoria") or ""
    dep_vinc_classificacao = etapa_final.get("departamento_vinculado") or filho_obj.get("departamento_vinculado")
    if dep_vinc_classificacao and dep_vinc_classificacao != dep_proprio \
            and not ticket_tem_pendencia_para_setor(t, dep_vinc_classificacao):
        st.markdown(_html(f"""
        <div class="tk-banner" style="animation:none;background:#EFF6FF;color:#1D4ED8;border-color:#60A5FA;">
            📨 Esta classificação é vinculada ao setor <b>{esc(dep_vinc_classificacao)}</b> —
            ao confirmar, uma pendência será criada automaticamente para eles.
        </div>"""), unsafe_allow_html=True)

    vermelha = bool(etapa_final.get("requer_data"))
    data_prevista = None
    if vermelha:
        st.markdown('<span class="tk-blink-warn">🔴 Esta etapa exige um prazo (2º SLA)</span>',
                    unsafe_allow_html=True)
        data_prevista = st.date_input(
            "Data prevista (obrigatória, futura) *",
            min_value=datetime.now(BRT).date() + timedelta(days=1),
            key=f"dt_{tid}"
        )
        st.caption("⚠️ Após confirmar, esta trilha (Motivo Filho + Etapa + Data) fica "
                   "TRAVADA — não será mais possível alterar. Só confirme se realmente "
                   "precisa desse prazo; caso contrário, resolva o ticket normalmente.")

    label_confirmar = "🔒 Confirmar etapa e travar prazo" if vermelha else "✅ Definir etapa"
    if st.button(label_confirmar, key=f"confirmar_etapa_{tid}", type="primary"):
        agora = agora_brt()
        updates = {
            "motivo_filho": filho_obj["nome"],
            "etapa_atual": " › ".join(caminho),
            "etapa_vermelha": vermelha,
        }
        if not t.get("sla1_definido"):
            limite_pai, _ = deadline_ativo({**t, "etapa_vermelha": False, "etapa_data_prevista": None})
            cumprido = (datetime.now(BRT) <= limite_pai) if limite_pai else True
            updates["sla1_definido"]    = True
            updates["sla1_cumprido"]    = cumprido
            updates["sla1_definido_em"] = agora
        if vermelha:
            updates["etapa_data_prevista"] = data_prevista.isoformat()
            updates["etapa_definida_em"]   = agora
            updates["etapa_definida_por"]  = user.get("nome","")
            updates["etapa_travada"]       = True
        if etapa_final.get("atendentes_vinculados"):
            updates["atendentes"]     = etapa_final["atendentes_vinculados"]
            updates["atribuido_para"] = etapa_final["atendentes_vinculados"][0]

        from google.cloud.firestore import ArrayUnion
        updates["historico_etapas"] = ArrayUnion([{
            "etapa": " › ".join(caminho), "quando": agora,
            "por": user.get("nome",""), "vermelha": vermelha,
            "data_prevista": data_prevista.isoformat() if vermelha else None,
        }])
        atualizar_ticket(tid, updates, interacao_de=user.get("usuario",""))

        msg_extra = ""
        if dep_vinc_classificacao and dep_vinc_classificacao != dep_proprio \
                and not ticket_tem_pendencia_para_setor(t, dep_vinc_classificacao):
            registrar_solicitacao_setor(
                tid, t, dep_vinc_classificacao,
                f"Pendência automática: a classificação '{' › '.join(caminho)}' exige "
                f"retorno do setor {dep_vinc_classificacao} para este chamado ser concluído.",
                user,
            )
            msg_extra = f" 📨 Pendência automática registrada para o setor **{dep_vinc_classificacao}**."

        st.success("Classificação registrada!" + (" Prazo travado." if vermelha else "") + msg_extra)
        time.sleep(.6); st.rerun()


# ── Pendências entre Setores (dentro do ticket) ────────────────────
def _bloco_pendencias_setor(t, tid, user, papel):
    st.markdown("---")
    st.markdown("#### 📨 Pendências entre Setores")
    st.caption("Peça pra outro setor resolver algo sem abrir um chamado novo — fica "
               "tudo registrado aqui, dentro deste mesmo ticket.")

    todas = t.get("solicitacoes_setor", []) or []
    pedidos = {s["id"]: s for s in todas if s.get("tipo") == "pedido"}
    respostas_por_pedido = {}
    for s in todas:
        if s.get("tipo") == "resposta":
            respostas_por_pedido.setdefault(s.get("pedido_id"), []).append(s)

    if pedidos:
        for pid, pedido in sorted(pedidos.items(), key=lambda kv: kv[1].get("solicitado_em","")):
            cor_o = cor_departamento(pedido.get("setor_origem",""))
            cor_d = cor_departamento(pedido.get("setor_destino",""))
            aberto = pid not in respostas_por_pedido
            st.markdown(_html(f"""
            <div class="tk-setor-card" style="border-left:4px solid {cor_d};">
                <span class="tk-setor-pill" style="background:{cor_o};">{esc(pedido.get('setor_origem',''))}</span>
                ➜
                <span class="tk-setor-pill" style="background:{cor_d};">{esc(pedido.get('setor_destino',''))}</span>
                {"<span class='tk-blink-warn' style='margin-left:6px;'>⏳ aguardando resposta</span>" if aberto else ""}
                <div style="font-size:0.78rem;color:#64778d;margin-top:6px;">
                    Solicitado por {esc(pedido.get('solicitado_por_nome',''))} em
                    {esc(str(pedido.get('solicitado_em',''))[:16])}
                </div>
                <div style="font-size:0.88rem;color:#2c3e50;margin-top:4px;">{esc(pedido.get('mensagem',''))}</div>
            </div>"""), unsafe_allow_html=True)

            for resp in respostas_por_pedido.get(pid, []):
                cor_r = cor_departamento(resp.get("setor_origem",""))
                st.markdown(_html(f"""
                <div class="tk-setor-card" style="border-left:4px solid {cor_r};margin-left:22px;background:#fafafa;">
                    <span class="tk-setor-pill" style="background:{cor_r};">✅ {esc(resp.get('setor_origem',''))} respondeu</span>
                    <div style="font-size:0.78rem;color:#64778d;margin-top:6px;">
                        Por {esc(resp.get('respondido_por_nome',''))} em {esc(str(resp.get('respondido_em',''))[:16])}
                    </div>
                    <div style="font-size:0.88rem;color:#2c3e50;margin-top:4px;">{esc(resp.get('resposta',''))}</div>
                </div>"""), unsafe_allow_html=True)

            dep_user = user.get("departamento")
            pode_responder = aberto and ((papel in ("supervisor", "adm")) or (dep_user == pedido.get("setor_destino")))
            if pode_responder:
                with st.form(f"form_resp_det_{tid}_{pid}", clear_on_submit=True):
                    resp_txt = st.text_area("Responder esta pendência", height=70, key=f"respdet_{tid}_{pid}")
                    if st.form_submit_button(f"✅ Responder ({pedido.get('setor_destino')})",
                                             type="primary", use_container_width=True):
                        if resp_txt.strip():
                            responder_solicitacao_setor(tid, pedido, resp_txt.strip(), user)
                            st.success("Pendência respondida!"); time.sleep(.6); st.rerun()
                        else:
                            st.warning("Escreva uma resposta antes de concluir.")
    else:
        st.caption("Nenhuma pendência de setor registrada neste ticket ainda.")

    with st.expander("📨 Solicitar retorno de um setor"):
        deps_nomes = [d.get("nome") for d in listar_departamentos() if d.get("nome")]
        dep_proprio = t.get("departamento") or t.get("categoria") or ""
        opcoes = [d for d in deps_nomes if d != dep_proprio] or deps_nomes
        if not opcoes:
            st.caption("Cadastre Departamentos em Configurações para poder solicitar.")
        else:
            with st.form(f"form_solic_{tid}", clear_on_submit=True):
                setor_dest = st.selectbox("Setor que precisa responder", opcoes, key=f"setordest_{tid}")
                msg = st.text_area("O que você precisa deste setor?", height=80, key=f"msgsolic_{tid}")
                if st.form_submit_button("📨 Enviar solicitação", type="primary", use_container_width=True):
                    if msg.strip():
                        registrar_solicitacao_setor(tid, t, setor_dest, msg.strip(), user)
                        st.success(f"Solicitação enviada para {setor_dest}!"); time.sleep(.6); st.rerun()
                    else:
                        st.warning("Escreva o que você precisa antes de enviar.")


def _detalhe_corpo(t, tid, user, papel):
    sl, spct, svenc = sla_restante(t)
    sv, sbg, sc, _  = STATUS_CFG.get(t.get("status","aberto"),("—","#fff","#000","#000"))
    pv, pbg, pc     = PRIO_CFG.get(t.get("prioridade","normal"),("—","#fff","#000"))
    sla_cor = GOLD_VENC if svenc else ("#CA8A04" if spct>70 else GREEN_OK)
    pendente_vencido = ticket_vencido_pendente(t)

    if pendente_vencido:
        st.markdown(_html('<div class="tk-banner">⚠️ Este ticket está com o prazo VENCIDO!</div>'),
                    unsafe_allow_html=True)

    if tem_interacao_nao_vista(t, user):
        st.markdown(
            '<span class="tk-blink-info">🔵 Houve uma nova interação neste ticket que você '
            'ainda não respondeu</span>', unsafe_allow_html=True
        )

    id_vis = esc(t.get("id_zendesk", tid[:8]))
    titulo = esc(t.get("assunto","—"))
    dep    = esc(t.get("departamento") or t.get("categoria") or "—")
    caminho_mot = esc(_caminho_motivo(t)) or esc(t.get("motivo_pai") or "—")
    criado = esc(t.get("criado_em","")[:16])
    atend  = t.get("atendentes", [])
    atend_str = esc(", ".join(atend)) if atend else "🌐 Todo o departamento"
    cli_cod  = esc(t.get("cliente_codigo") or "—")
    cli_nome = esc(t.get("cliente_nome") or "—")
    solicit  = esc(t.get("solicitante_nome") or "—")

    sla1_badge = ""
    if t.get("sla1_definido"):
        if t.get("sla1_cumprido"):
            sla1_badge = '<span class="tk-badge-sla1-ok">🎯 Triagem: dentro do prazo</span>'
        else:
            sla1_badge = '<span class="tk-badge-sla1-perd">🎯 Triagem: prazo perdido</span>'

    pendencias_badges = ""
    for pend in solicitacoes_abertas(t):
        cor_pend = cor_departamento(pend.get("setor_destino",""))
        pendencias_badges += (f' <span class="tk-setor-pill" style="background:{cor_pend};">'
                              f'📨 aguarda {esc(pend.get("setor_destino",""))}</span>')

    st.markdown(_html(f"""
    <div style="background:#fff;border:1px solid #e2e8f0;border-left:6px solid {sla_cor if pendente_vencido else '#C9A84C'};
                border-radius:12px;padding:18px 20px;margin-bottom:16px;">
        <h3 style="margin:0 0 6px;color:#2c3e50;">#{id_vis} — {titulo}</h3>
        <div style="margin-bottom:10px;">
            {pill(sv,sbg,sc)} {pill(pv,pbg,pc)} {sla1_badge}{pendencias_badges}
            <span style="font-size:0.78rem;color:#64778d;margin-left:8px;">
                🏢 {dep} &nbsp;·&nbsp; 📂 {caminho_mot} &nbsp;·&nbsp; {criado}
            </span>
        </div>
        <div style="font-size:0.8rem;color:#2c3e50;margin-bottom:6px;">
            🧾 Cliente: <b>{cli_nome}</b> &nbsp;·&nbsp; Código: <b>{cli_cod}</b>
        </div>
        <div style="font-size:0.78rem;color:#64778d;margin-bottom:8px;">
            🙋 Solicitante: {solicit} &nbsp;·&nbsp; 👥 Atendentes: {atend_str}
            &nbsp;·&nbsp; ⏱ {esc(sla_label(t))}: <b style="color:{sla_cor};">{esc(sl)}</b>
        </div>
    </div>"""), unsafe_allow_html=True)

    relacionados = tickets_do_cliente(t.get("cliente_codigo"), excluir_id=tid)
    if relacionados:
        abertos_rel = sum(1 for x in relacionados if x.get("status") in STATUS_ABERTOS)
        with st.expander(
            f"🗂 Histórico do cliente — {len(relacionados)} outro(s) chamado(s)"
            + (f" ({abertos_rel} em aberto)" if abertos_rel else ""),
            expanded=False
        ):
            _render_bloco_historico_cliente(relacionados)

    st.markdown("**📝 Descrição**")
    st.text_area("Descrição", value=str(t.get("descricao") or t.get("assunto","—")),
                 height=140, disabled=True, label_visibility="collapsed",
                 key=f"desc_{tid}")

    status_atual = t.get("status", "aberto")
    terminal     = status_atual in ("finalizado", "cancelado")
    finalizado   = status_atual == "finalizado"
    pode_agir    = (papel in ("supervisor", "adm")) or _atribuido_a(t, user)
    status_edit  = pode_agir and not terminal
    STATUS_OPC   = [k for k in STATUS_CFG.keys() if k != "finalizado"]

    # ── Classificação Motivo Filho / Etapa (SLA1 congelado / SLA2 travado) ──
    _bloco_classificacao(t, tid, user, papel, pode_agir and not terminal)

    # ── Pendências entre Setores (não cria ticket novo, mesmo histórico) ──
    if not terminal:
        _bloco_pendencias_setor(t, tid, user, papel)

    st.markdown("---")
    if finalizado:
        st.info("🔒 Este chamado está **finalizado** e foi encerrado definitivamente. "
                 "Não é mais possível comentar ou alterar o status — consulte o "
                 "histórico abaixo.")
    else:
        with st.form(f"form_trat_{tid}", clear_on_submit=True):
            cs1, cs2 = st.columns(2)
            with cs1:
                if status_edit:
                    idx = STATUS_OPC.index(status_atual) if status_atual in STATUS_OPC else 0
                    novo_status = st.selectbox("Status", STATUS_OPC, index=idx,
                                               format_func=lambda k: STATUS_CFG[k][0],
                                               key=f"det_status_{tid}")
                else:
                    novo_status = status_atual
                    st.markdown("**Status**")
                    st.markdown(pill(sv, sbg, sc), unsafe_allow_html=True)
            with cs2:
                st.markdown("**Prioridade**")
                st.markdown(pill(pv, pbg, pc), unsafe_allow_html=True)

            novo_com = st.text_area("Escrever resposta / comentário", height=90,
                                    placeholder="Digite a tratativa...", key=f"com_{tid}")
            enviar = st.form_submit_button("Enviar", type="primary", use_container_width=True)

            if enviar:
                updates = {}
                if status_edit and novo_status != status_atual:
                    updates["status"] = novo_status
                tem_com = bool(novo_com and novo_com.strip())
                if tem_com:
                    adicionar_comentario(tid, user.get("nome",""), user.get("usuario",""),
                                          novo_com.strip())
                if updates:
                    atualizar_ticket(tid, updates, interacao_de=user.get("usuario",""))
                if tem_com or updates:
                    msg = "Enviado!"
                    if updates.get("status") == "resolvido":
                        msg = ("✅ Ticket marcado como Resolvido! Saiu das suas tratativas e "
                               "permanece em 'Todos os tickets'.")
                    st.success(msg); time.sleep(.5)
                    if updates.get("status") in ("resolvido", "cancelado"):
                        st.session_state.tk_ticket_aberto = None
                    st.rerun()
                else:
                    st.warning("Escreva uma resposta ou altere o status antes de enviar.")

    # ── Registro de contato/observação avulsa (qualquer pessoa com acesso) ──
    if not finalizado:
        with st.expander("💬 Registrar um contato/observação (visível ao responsável)"):
            st.caption("Use isto se você teve contato com o cliente sobre este caso mas "
                       "não é o responsável formal pela tratativa. O responsável vai ver "
                       "um alerta 🔵 de nova interação até responder.")
            nota = st.text_area("O que você conversou ou observou?", key=f"nota_{tid}")
            if st.button("Registrar observação", key=f"btnnota_{tid}"):
                if nota.strip():
                    adicionar_comentario(tid, user.get("nome",""), user.get("usuario",""),
                                          f"📎 {nota.strip()}")
                    st.success("Registrado!"); time.sleep(.5); st.rerun()
                else:
                    st.warning("Escreva algo antes de registrar.")

    st.markdown("#### 💬 Histórico")
    comentarios = t.get("comentarios", [])
    if not comentarios:
        st.caption("Nenhum comentário ainda.")
    else:
        for c in comentarios:
            alinha = "right" if c.get("autor") == user.get("nome") else "left"
            bg_com = "#EFF6FF" if alinha == "right" else "#f8f9fa"
            bord   = "#2563EB" if alinha == "right" else "#C9A84C"
            st.markdown(_html(
                f'<div style="text-align:{alinha};margin:6px 0;">'
                f'<div style="display:inline-block;background:{bg_com};'
                f'border-left:3px solid {bord};padding:8px 12px;'
                f'border-radius:8px;max-width:80%;text-align:left;">'
                f'<b style="font-size:0.8rem;">{esc(c.get("autor",""))}</b>'
                f'<span style="color:#64778d;font-size:0.72rem;margin-left:6px;">{esc(c.get("data","")[:16])}</span>'
                f'<br><span style="font-size:0.88rem;">{esc(c.get("texto",""))}</span>'
                f'</div></div>'), unsafe_allow_html=True)

    if t.get("historico_etapas"):
        with st.expander("🗂️ Histórico de classificação (Motivo Filho / Etapa)"):
            for h in t["historico_etapas"]:
                marca = "🔴" if h.get("vermelha") else "⚫"
                prazo = f" · prazo: {h.get('data_prevista')}" if h.get("vermelha") else ""
                st.caption(f"{marca} {h.get('etapa','')} — por {h.get('por','')} "
                           f"em {str(h.get('quando',''))[:16]}{prazo}")

    if status_atual == "resolvido" and t.get("aberto_por") == user.get("usuario"):
        st.markdown("---")
        st.markdown(_html(
            '<div style="background:#F3ECD9;border:1px solid #A98C3D;border-radius:10px;'
            'padding:12px 14px;margin:6px 0 10px;color:#6B5A2A;font-weight:600;">'
            '✔ Este chamado foi marcado como <b>Resolvido</b>. Valide para encerrar '
            'definitivamente, ou reabra se não foi resolvido.<br>'
            '<span style="font-weight:500;font-size:0.82rem;">Sem ação em 24h, ele é '
            'encerrado automaticamente.</span></div>'), unsafe_allow_html=True)
        cva, cvb = st.columns(2)
        if cva.button("✅ Validar e encerrar", key=f"val_{tid}", type="primary",
                      use_container_width=True):
            atualizar_ticket(tid, {"status": "finalizado"}, interacao_de=user.get("usuario",""))
            st.success("Chamado encerrado!"); time.sleep(.5)
            st.session_state.tk_ticket_aberto = None; st.rerun()
        if cvb.button("↩️ Reabrir chamado", key=f"reab_{tid}", use_container_width=True):
            atualizar_ticket(tid, {"status": "em_andamento"}, interacao_de=user.get("usuario",""))
            st.success("Chamado reaberto!"); time.sleep(.5); st.rerun()


def _carregar_e_render_detalhe(tid, user, papel, modal=False):
    if not tid:
        return
    doc = get_db().collection(COLECAO).document(tid).get()
    if not doc.exists:
        st.error("Ticket não encontrado.")
        return
    _detalhe_corpo(doc.to_dict(), tid, user, papel)


def _render_painel_lateral_detalhe(user, papel):
    """Coluna da direita (3ª coluna) com o detalhe do ticket clicado — em
    vez do antigo popup/st.dialog. Só é chamada quando há um ticket aberto
    no estado da sessão (tk_ticket_aberto)."""
    tid = st.session_state.get("tk_ticket_aberto")
    if not tid:
        return
    c_tit, c_fechar = st.columns([5, 1])
    with c_tit:
        st.markdown("### 📄 Detalhe do Ticket")
    with c_fechar:
        if st.button("✕", key="tk_fechar_detalhe", help="Fechar", use_container_width=True):
            st.session_state.tk_ticket_aberto = None
            st.rerun()
    _carregar_e_render_detalhe(tid, user, papel, modal=True)
