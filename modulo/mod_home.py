import streamlit as st
import pandas as pd
import time
from datetime import datetime, date, timezone, timedelta

from database import (
    listar_lembretes_pessoais, criar_lembrete_pessoal_db,
    atualizar_lembrete_pessoal_db, deletar_lembrete_pessoal_db,
    listar_raci_projetos, criar_raci_projeto_db,
    atualizar_raci_projeto_db, deletar_raci_projeto_db,
)

BRT = timezone(timedelta(hours=-3))

PAPEIS_RACI = ["", "R", "A", "C", "I"]
PRIORIDADES = ["Alto", "Médio", "Baixo"]
STATUS_ATIV = ["Não Iniciado", "Em Andamento", "Concluído", "Atrasado"]
LEGENDA_RACI = (
    "**R**=Responsável (executa) · **A**=Aprovador (decide/autoriza) · "
    "**C**=Consultado (opina antes) · **I**=Informado (avisado depois)"
)

_CSS_HOME = """
<style>
.home-item { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
    padding:10px 14px; margin-bottom:6px; border-left:4px solid #C9A84C; }
.home-item.atrasado { border-left-color:#e74c3c; }
.home-item.hoje { border-left-color:#C9A84C; }
.home-item.futuro { border-left-color:#95a5a6; }
.home-origem { font-size:0.72rem; color:#64778d; }
</style>
"""


def _parse_data(s):
    if not s:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except Exception:
            continue
    return None


def renderizar_home(papel: str, user: dict = None):
    if user is None:
        user = {"role": papel, "nome": "Usuário", "usuario": "user"}
    uname = user.get("usuario", "")

    st.markdown(_CSS_HOME, unsafe_allow_html=True)
    st.subheader("🏠 Meu Dia")
    st.caption(f"Bem-vindo(a), {user.get('nome','Usuário').split()[0]} · "
               f"{datetime.now(BRT).strftime('%d/%m/%Y %H:%M')}")

    lembretes = listar_lembretes_pessoais(uname)
    raci_projetos = listar_raci_projetos()

    tabs = st.tabs(["📅 Meu Dia", "📊 Meus Projetos (RACI)", "🔔 Todos os Lembretes"])

    # ════════════════════════════════════════════════════════════
    # ABA 1 — MEU DIA
    # ════════════════════════════════════════════════════════════
    with tabs[0]:
        hoje = date.today()

        itens = []
        for l in lembretes:
            if l.get("status", "Pendente") != "Pendente":
                continue
            itens.append({
                "origem": "🗒️ Pessoal", "texto": l.get("texto", ""),
                "quando": l.get("data_hora", ""), "ref": l.get("id"),
            })

        for rp in raci_projetos:
            for et in rp.get("etapas", []):
                for at in et.get("atividades", []):
                    if at.get("status") == "Concluído":
                        continue
                    dp = at.get("data_prevista")
                    if not dp:
                        continue
                    eh_meu = uname and uname in (at.get("papeis", {}) or {}) \
                        and at["papeis"].get(uname) == "R"
                    if not eh_meu:
                        continue  # no "Meu Dia" só entra o que EU sou Responsável (R)
                    itens.append({
                        "origem": f"📊 {rp.get('nome','')} / {et.get('nome','')}",
                        "texto": at.get("atividade", ""), "quando": dp, "ref": None,
                    })

        atrasados, de_hoje, futuros = [], [], []
        for it in itens:
            dt_it = _parse_data(it["quando"])
            if dt_it is None:
                futuros.append(it)
            elif dt_it.date() < hoje:
                atrasados.append(it)
            elif dt_it.date() == hoje:
                de_hoje.append(it)
            else:
                futuros.append(it)

        c1, c2, c3 = st.columns(3)
        c1.markdown(f'<div class="kpi-card red"><div class="kpi-label">⚠️ Atrasados</div>'
                    f'<div class="kpi-value">{len(atrasados)}</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="kpi-card gold"><div class="kpi-label">📌 Hoje</div>'
                    f'<div class="kpi-value">{len(de_hoje)}</div></div>', unsafe_allow_html=True)
        c3.markdown(f'<div class="kpi-card gray"><div class="kpi-label">🔜 Próximos</div>'
                    f'<div class="kpi-value">{len(futuros)}</div></div>', unsafe_allow_html=True)

        st.write("")
        with st.popover("➕ Novo lembrete rápido", use_container_width=True):
            txt_l = st.text_input("O que precisa lembrar?", key="novo_lembrete_txt")
            cdl1, cdl2 = st.columns(2)
            dl = cdl1.date_input("Data", value=date.today(), key="novo_lembrete_data")
            hl = cdl2.time_input("Hora", value=None, key="novo_lembrete_hora")
            if st.button("Gravar Lembrete", type="primary", key="btn_novo_lembrete",
                         use_container_width=True):
                if txt_l.strip():
                    hora_txt = hl.strftime("%H:%M") if hl else "00:00"
                    criar_lembrete_pessoal_db(
                        uname, txt_l.strip(),
                        f"{dl.strftime('%d/%m/%Y')} {hora_txt}",
                    )
                    st.success("Lembrete criado!")
                    time.sleep(.4)
                    st.rerun()
                else:
                    st.warning("Descreva o lembrete.")

        st.divider()

        grupos = [
            ("⚠️ Atrasados", atrasados, "atrasado"),
            ("📌 Hoje", de_hoje, "hoje"),
            ("🔜 Próximos", futuros, "futuro"),
        ]
        algum = False
        for titulo, lista_g, classe in grupos:
            if not lista_g:
                continue
            algum = True
            st.markdown(f"##### {titulo}")
            for it in lista_g:
                cb1, cb2 = st.columns([5, 1])
                with cb1:
                    st.markdown(
                        f'<div class="home-item {classe}">'
                        f'<b>{it["texto"]}</b><br>'
                        f'<span class="home-origem">{it["origem"]} · {it["quando"]}</span>'
                        f'</div>', unsafe_allow_html=True)
                if it["ref"] is not None:
                    with cb2:
                        if st.button("✅ Concluir", key=f"done_{it['ref']}", use_container_width=True):
                            atualizar_lembrete_pessoal_db(it["ref"], status="Executado")
                            st.rerun()
        if not algum:
            st.info("🎉 Nenhuma tarefa pendente no momento.")

    # ════════════════════════════════════════════════════════════
    # ABA 2 — MEUS PROJETOS (RACI)
    # ════════════════════════════════════════════════════════════
    with tabs[1]:
        nomes_proj = [p["nome"] for p in raci_projetos]
        escolha = st.selectbox("Selecione um projeto:", ["+ CRIAR NOVO PROJETO"] + nomes_proj,
                               key="home_raci_escolha")

        if escolha == "+ CRIAR NOVO PROJETO":
            with st.form("form_novo_proj_raci", clear_on_submit=True):
                nome_np = st.text_input("Nome do Projeto *")
                pessoas_txt = st.text_area(
                    "Pessoas do projeto (uma por linha — ex: 'Wendley Cunha (Líder de CX)')",
                    height=100,
                )
                if st.form_submit_button("🚀 Criar Projeto", type="primary", use_container_width=True):
                    if nome_np.strip():
                        pessoas = [p.strip() for p in pessoas_txt.splitlines() if p.strip()]
                        criar_raci_projeto_db(nome_np.strip(), pessoas)
                        st.success("Projeto criado!")
                        time.sleep(.4)
                        st.rerun()
                    else:
                        st.warning("Informe o nome do projeto.")
        else:
            projeto = next(p for p in raci_projetos if p["nome"] == escolha)

            with st.expander("⚙️ Configurações do Projeto"):
                novas_pessoas = st.text_area(
                    "Pessoas do projeto (uma por linha)",
                    value="\n".join(projeto.get("pessoas", [])),
                    key=f"pessoas_{projeto['id']}", height=100,
                )
                cse1, cse2 = st.columns(2)
                if cse1.button("💾 Salvar Pessoas", use_container_width=True, key=f"svp_{projeto['id']}"):
                    pessoas = [p.strip() for p in novas_pessoas.splitlines() if p.strip()]
                    atualizar_raci_projeto_db(projeto["id"], pessoas=pessoas)
                    st.success("Atualizado!")
                    time.sleep(.4)
                    st.rerun()
                if cse2.button("🗑️ Excluir Projeto", use_container_width=True, key=f"delp_{projeto['id']}"):
                    deletar_raci_projeto_db(projeto["id"])
                    st.rerun()

            st.divider()
            ce1, ce2 = st.columns([3, 1])
            ce1.markdown("#### 🧭 Etapas do Projeto")
            with ce2:
                with st.popover("➕ Nova Etapa", use_container_width=True):
                    nome_etapa = st.text_input("Nome da Etapa", key=f"net_{projeto['id']}")
                    if st.button("Criar Etapa", type="primary", key=f"bnet_{projeto['id']}",
                                 use_container_width=True):
                        if nome_etapa.strip():
                            etapas = projeto.get("etapas", [])
                            etapas.append({
                                "id": datetime.now(BRT).timestamp(),
                                "nome": nome_etapa.strip(), "atividades": [],
                            })
                            atualizar_raci_projeto_db(projeto["id"], etapas=etapas)
                            st.rerun()
                        else:
                            st.warning("Informe o nome da etapa.")

            if not projeto.get("etapas"):
                st.info("Nenhuma etapa criada ainda. Use '➕ Nova Etapa' acima para começar.")
            else:
                nomes_etapas = [e["nome"] for e in projeto["etapas"]]
                aba_etapas = st.tabs(nomes_etapas)
                for i_et, etapa in enumerate(projeto["etapas"]):
                    with aba_etapas[i_et]:
                        _render_etapa_raci(projeto, etapa)

    # ════════════════════════════════════════════════════════════
    # ABA 3 — TODOS OS LEMBRETES
    # ════════════════════════════════════════════════════════════
    with tabs[2]:
        st.markdown("##### 🔔 Meus Lembretes")
        if not lembretes:
            st.info("Nenhum lembrete cadastrado ainda.")
        else:
            filtro = st.multiselect(
                "Filtrar por status:", ["Pendente", "Executado"],
                default=["Pendente"], key="filtro_lembretes_home",
            )
            for l in lembretes:
                status_l = l.get("status", "Pendente")
                if filtro and status_l not in filtro:
                    continue
                cols = st.columns([4, 2, 1, 1])
                icone = "✅" if status_l == "Executado" else "🔵"
                cols[0].write(f"{icone} {l.get('texto','')}")
                cols[1].caption(l.get("data_hora", ""))
                if status_l == "Pendente":
                    if cols[2].button("✅", key=f"lemb_ok_{l['id']}", use_container_width=True):
                        atualizar_lembrete_pessoal_db(l["id"], status="Executado")
                        st.rerun()
                if cols[3].button("🗑️", key=f"lemb_del_{l['id']}", use_container_width=True):
                    deletar_lembrete_pessoal_db(l["id"])
                    st.rerun()


# ─── Matriz RACI de uma etapa ───────────────────────────────────────
def _render_etapa_raci(projeto, etapa):
    pessoas = projeto.get("pessoas", [])
    atividades = etapa.get("atividades", [])

    def _salvar_etapas(novas_etapas):
        atualizar_raci_projeto_db(projeto["id"], etapas=novas_etapas)

    total = len(atividades)
    if total:
        concl = sum(1 for a in atividades if a.get("status") == "Concluído")
        st.progress(concl / total, text=f"{concl}/{total} atividades concluídas")

    with st.popover("➕ Adicionar Atividade", use_container_width=True):
        txt_at = st.text_input("Descrição da Atividade", key=f"at_txt_{etapa['id']}")
        cprio, cstat = st.columns(2)
        prio = cprio.selectbox("Prioridade", PRIORIDADES, key=f"at_prio_{etapa['id']}")
        stt = cstat.selectbox("Status", STATUS_ATIV, key=f"at_stt_{etapa['id']}")
        cdt1, cdt2 = st.columns(2)
        dt_prev = cdt1.date_input("Data Prevista", value=None, key=f"at_dtp_{etapa['id']}")
        dt_ent = cdt2.date_input("Data Entregue", value=None, key=f"at_dte_{etapa['id']}")
        if st.button("Adicionar", type="primary", key=f"badd_{etapa['id']}", use_container_width=True):
            if txt_at.strip():
                etapa.setdefault("atividades", []).append({
                    "id": datetime.now(BRT).timestamp(),
                    "atividade": txt_at.strip(), "prioridade": prio, "status": stt,
                    "data_prevista": dt_prev.strftime("%d/%m/%Y") if dt_prev else None,
                    "data_entregue": dt_ent.strftime("%d/%m/%Y") if dt_ent else None,
                    "papeis": {p: "" for p in pessoas},
                })
                _salvar_etapas(projeto["etapas"])
                st.rerun()
            else:
                st.warning("Informe a descrição da atividade.")

    if not pessoas:
        st.warning("⚠️ Cadastre as pessoas do projeto em '⚙️ Configurações do Projeto' "
                   "para montar a matriz RACI desta etapa.")
        return

    if not atividades:
        st.info("Nenhuma atividade cadastrada nesta etapa ainda.")
        return

    linhas = []
    for a in atividades:
        a.setdefault("papeis", {})
        linha = {
            "Prioridade": a.get("prioridade", "Médio"),
            "Status": a.get("status", "Não Iniciado"),
            "Atividade": a.get("atividade", ""),
            "Data Prevista": a.get("data_prevista") or "",
            "Data Entregue": a.get("data_entregue") or "",
        }
        for p in pessoas:
            linha[p] = a["papeis"].get(p, "")
        linhas.append(linha)
    df_matriz = pd.DataFrame(linhas)

    col_config = {
        "Prioridade": st.column_config.SelectboxColumn(options=PRIORIDADES, required=True),
        "Status": st.column_config.SelectboxColumn(options=STATUS_ATIV, required=True),
        "Atividade": st.column_config.TextColumn(width="large"),
        "Data Prevista": st.column_config.TextColumn(help="dd/mm/aaaa"),
        "Data Entregue": st.column_config.TextColumn(help="dd/mm/aaaa"),
    }
    for p in pessoas:
        col_config[p] = st.column_config.SelectboxColumn(
            options=PAPEIS_RACI, help="R=Responsável · A=Aprovador · C=Consultado · I=Informado",
        )

    editado = st.data_editor(
        df_matriz, column_config=col_config, use_container_width=True,
        hide_index=True, num_rows="fixed", key=f"editor_raci_{etapa['id']}",
    )

    cs1, _ = st.columns([1, 4])
    if cs1.button("💾 Salvar Matriz", type="primary", key=f"savemtx_{etapa['id']}",
                  use_container_width=True):
        novas = []
        for i, row in editado.iterrows():
            original = atividades[i] if i < len(atividades) else {}
            papeis = {p: row.get(p, "") or "" for p in pessoas}
            novas.append({
                "id": original.get("id", datetime.now(BRT).timestamp()),
                "atividade": row["Atividade"], "prioridade": row["Prioridade"],
                "status": row["Status"],
                "data_prevista": row["Data Prevista"] or None,
                "data_entregue": row["Data Entregue"] or None,
                "papeis": papeis,
            })
        etapa["atividades"] = novas
        _salvar_etapas(projeto["etapas"])
        st.success("Matriz salva!")
        st.rerun()

    st.caption(LEGENDA_RACI)

    with st.expander("🗑️ Excluir uma atividade"):
        for idx_a, a in enumerate(atividades):
            cdel1, cdel2 = st.columns([5, 1])
            cdel1.write(f"{a.get('atividade','')}")
            if cdel2.button("Excluir", key=f"delat_{etapa['id']}_{idx_a}", use_container_width=True):
                etapa["atividades"].pop(idx_a)
                _salvar_etapas(projeto["etapas"])
                st.rerun()
