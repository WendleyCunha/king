"""
Portal Gestão — views/home.py
─────────────────────────────────────────────────────────────────────────────
Painel pessoal do usuário logado. Três frentes, em abas:

  📅 Meu Dia              → tarefas/lembretes de hoje e atrasados, de TODAS as
                            origens (lembretes pessoais, lembretes de projetos
                            PQI e atividades RACI com data prevista), num só
                            lugar. Permite criar um lembrete rápido.

  📊 Meus Projetos (RACI) → "tocar" projetos: criar projetos, criar etapas
                            livremente (não é um roadmap fixo), cadastrar as
                            pessoas envolvidas, e montar a matriz RACI de cada
                            etapa (Atividade x Pessoa = R/A/C/I), com
                            Prioridade, Status, Data Prevista e Data Entregue
                            — no mesmo formato da planilha RACI usada hoje.

  🔔 Todos os Lembretes   → lista consolidada de lembretes pessoais, com
                            filtro por status e exclusão.

Persistência: usa modulos/database.py. Esta versão assume o MESMO padrão de
carregar_projetos()/salvar_projetos() já usado em mod_processos.py (um
documento Firestore guardando uma lista). Foram adicionadas 4 funções novas
que precisam existir em modulos/database.py (snippet enviado junto):
    carregar_raci_projetos() / salvar_raci_projetos(lista)
    carregar_lembretes_pessoais() / salvar_lembretes_pessoais(lista)
Se o padrão real do seu database.py for diferente, envie o arquivo para eu
ajustar essas 4 funções com exatidão.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, date
from modulos import database as db

PAPEIS_RACI  = ["", "R", "A", "C", "I"]
PRIORIDADES  = ["Alto", "Médio", "Baixo"]
STATUS_ATIV  = ["Não Iniciado", "Em Andamento", "Concluído", "Atrasado"]

LEGENDA_RACI = (
    "**R**=Responsável (executa) · **A**=Aprovador (decide/autoriza) · "
    "**C**=Consultado (opina antes) · **I**=Informado (avisado depois)"
)


# ─── Helpers ──────────────────────────────────────────────────────
def _carregar_seguro(func):
    try:
        dados = func()
        return dados if isinstance(dados, list) else []
    except Exception:
        return []


def _parse_data(s):
    """Aceita 'dd/mm/aaaa' ou 'dd/mm/aaaa HH:MM'. Retorna datetime ou None."""
    if not s:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except Exception:
            continue
    return None


def _css():
    st.markdown("""
    <style>
    .metric-card { background-color: #ffffff; padding: 15px; border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #ececec; text-align: center; }
    .metric-value { font-size: 24px; font-weight: 800; color: #0a1628; }
    .metric-label { font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; }
    .home-item { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:10px 14px; margin-bottom:6px; border-left:4px solid #0d2145; }
    .home-item.atrasado { border-left-color:#dc2626; }
    .home-item.hoje { border-left-color:#FFD700; }
    .home-item.futuro { border-left-color:#94a3b8; }
    .home-origem { font-size:0.72rem; color:#64748b; }
    </style>
    """, unsafe_allow_html=True)


# ─── Função principal ─────────────────────────────────────────────
def exibir(user_info):
    _css()
    nome_usuario = (user_info or {}).get("nome", "Usuário")
    st.title("🏠 Meu Dia")
    st.caption(f"Bem-vindo(a), {nome_usuario.split()[0]} · {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # ── Estado / dados ────────────────────────────────────────────
    if "home_raci" not in st.session_state:
        st.session_state.home_raci = _carregar_seguro(db.carregar_raci_projetos)
    if "home_lembretes" not in st.session_state:
        st.session_state.home_lembretes = _carregar_seguro(db.carregar_lembretes_pessoais)

    projetos_pqi = _carregar_seguro(db.carregar_projetos)  # só leitura aqui (cross-módulo)

    def salvar_raci():
        try:
            db.salvar_raci_projetos(st.session_state.home_raci)
        except Exception as e:
            st.error(f"Erro ao salvar projetos RACI: {e}")

    def salvar_lembretes():
        try:
            db.salvar_lembretes_pessoais(st.session_state.home_lembretes)
        except Exception as e:
            st.error(f"Erro ao salvar lembretes: {e}")

    tabs = st.tabs(["📅 Meu Dia", "📊 Meus Projetos (RACI)", "🔔 Todos os Lembretes"])

    # ════════════════════════════════════════════════════════════
    # ABA 1 — MEU DIA
    # ════════════════════════════════════════════════════════════
    with tabs[0]:
        hoje = date.today()

        itens = []
        for l in st.session_state.home_lembretes:
            if l.get("status", "Pendente") != "Pendente":
                continue
            itens.append({
                "origem": "🗒️ Pessoal", "texto": l.get("texto", ""),
                "quando": l.get("data_hora", ""), "ref_pessoal": l.get("id"),
            })

        for proj in projetos_pqi:
            for l in proj.get("lembretes", []):
                itens.append({
                    "origem": f"🚀 {proj.get('titulo','Projeto')}",
                    "texto": l.get("texto", ""), "quando": l.get("data_hora", ""),
                    "ref_pessoal": None,
                })

        for rp in st.session_state.home_raci:
            for et in rp.get("etapas", []):
                for at in et.get("atividades", []):
                    if at.get("status") == "Concluído":
                        continue
                    dp = at.get("data_prevista")
                    if not dp:
                        continue
                    itens.append({
                        "origem": f"📊 {rp.get('nome','')} / {et.get('nome','')}",
                        "texto": at.get("atividade", ""), "quando": dp,
                        "ref_pessoal": None,
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
        c1.markdown(f'<div class="metric-card"><div class="metric-label">⚠️ Atrasados</div>'
                    f'<div class="metric-value" style="color:#dc2626;">{len(atrasados)}</div></div>',
                    unsafe_allow_html=True)
        c2.markdown(f'<div class="metric-card"><div class="metric-label">📌 Hoje</div>'
                    f'<div class="metric-value">{len(de_hoje)}</div></div>', unsafe_allow_html=True)
        c3.markdown(f'<div class="metric-card"><div class="metric-label">🔜 Próximos</div>'
                    f'<div class="metric-value">{len(futuros)}</div></div>', unsafe_allow_html=True)

        st.write("")
        with st.popover("➕ Novo lembrete rápido", use_container_width=True):
            txt_l = st.text_input("O que precisa lembrar?", key="novo_lembrete_txt")
            cdl1, cdl2 = st.columns(2)
            dl = cdl1.date_input("Data", value=date.today(), key="novo_lembrete_data")
            hl = cdl2.time_input("Hora", value=None, key="novo_lembrete_hora")
            if st.button("Gravar Lembrete", type="primary", key="btn_novo_lembrete"):
                if txt_l:
                    hora_txt = hl.strftime("%H:%M") if hl else "00:00"
                    st.session_state.home_lembretes.append({
                        "id": datetime.now().timestamp(),
                        "texto": txt_l,
                        "data_hora": f"{dl.strftime('%d/%m/%Y')} {hora_txt}",
                        "status": "Pendente",
                        "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    })
                    salvar_lembretes()
                    st.success("Lembrete criado!")
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
                if it["ref_pessoal"] is not None:
                    with cb2:
                        if st.button("✅ Concluir", key=f"done_{it['ref_pessoal']}", use_container_width=True):
                            for l in st.session_state.home_lembretes:
                                if l["id"] == it["ref_pessoal"]:
                                    l["status"] = "Executado"
                            salvar_lembretes()
                            st.rerun()
        if not algum:
            st.info("🎉 Nenhuma tarefa pendente no momento.")

    # ════════════════════════════════════════════════════════════
    # ABA 2 — MEUS PROJETOS (RACI)
    # ════════════════════════════════════════════════════════════
    with tabs[1]:
        nomes_proj = [p["nome"] for p in st.session_state.home_raci]
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
                        st.session_state.home_raci.append({
                            "id": datetime.now().timestamp(),
                            "nome": nome_np.strip(),
                            "data_criacao": datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "pessoas": [p.strip() for p in pessoas_txt.splitlines() if p.strip()],
                            "etapas": [],
                        })
                        salvar_raci()
                        st.success("Projeto criado!")
                        st.rerun()
                    else:
                        st.warning("Informe o nome do projeto.")
        else:
            projeto = next(p for p in st.session_state.home_raci if p["nome"] == escolha)

            with st.expander("⚙️ Configurações do Projeto"):
                novas_pessoas = st.text_area(
                    "Pessoas do projeto (uma por linha)",
                    value="\n".join(projeto.get("pessoas", [])),
                    key=f"pessoas_{projeto['id']}",
                    height=100,
                )
                cse1, cse2 = st.columns(2)
                if cse1.button("💾 Salvar Pessoas", use_container_width=True, key=f"svp_{projeto['id']}"):
                    projeto["pessoas"] = [p.strip() for p in novas_pessoas.splitlines() if p.strip()]
                    salvar_raci()
                    st.success("Atualizado!")
                    st.rerun()
                if cse2.button("🗑️ Excluir Projeto", use_container_width=True, key=f"delp_{projeto['id']}"):
                    st.session_state.home_raci.remove(projeto)
                    salvar_raci()
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
                            projeto.setdefault("etapas", []).append({
                                "id": datetime.now().timestamp(),
                                "nome": nome_etapa.strip(),
                                "atividades": [],
                            })
                            salvar_raci()
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
                        _render_etapa_raci(projeto, etapa, salvar_raci)

    # ════════════════════════════════════════════════════════════
    # ABA 3 — TODOS OS LEMBRETES (visão consolidada, pessoais)
    # ════════════════════════════════════════════════════════════
    with tabs[2]:
        st.markdown("##### 🔔 Lembretes Pessoais")
        if not st.session_state.home_lembretes:
            st.info("Nenhum lembrete pessoal cadastrado ainda.")
        else:
            filtro = st.multiselect(
                "Filtrar por status:", ["Pendente", "Executado"],
                default=["Pendente"], key="filtro_lembretes_home",
            )
            for idx, l in enumerate(st.session_state.home_lembretes):
                status_l = l.get("status", "Pendente")
                if filtro and status_l not in filtro:
                    continue
                cols = st.columns([4, 2, 1, 1])
                icone = "✅" if status_l == "Executado" else "🔵"
                cols[0].write(f"{icone} {l.get('texto','')}")
                cols[1].caption(l.get("data_hora", ""))
                if status_l == "Pendente":
                    if cols[2].button("✅", key=f"lemb_ok_{idx}", use_container_width=True):
                        st.session_state.home_lembretes[idx]["status"] = "Executado"
                        salvar_lembretes()
                        st.rerun()
                if cols[3].button("🗑️", key=f"lemb_del_{idx}", use_container_width=True):
                    st.session_state.home_lembretes.pop(idx)
                    salvar_lembretes()
                    st.rerun()


# ─── Matriz RACI de uma etapa ───────────────────────────────────────
def _render_etapa_raci(projeto, etapa, salvar_fn):
    pessoas = projeto.get("pessoas", [])
    atividades = etapa.get("atividades", [])

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
                    "id": datetime.now().timestamp(),
                    "atividade": txt_at.strip(),
                    "prioridade": prio,
                    "status": stt,
                    "data_prevista": dt_prev.strftime("%d/%m/%Y") if dt_prev else None,
                    "data_entregue": dt_ent.strftime("%d/%m/%Y") if dt_ent else None,
                    "papeis": {p: "" for p in pessoas},
                })
                salvar_fn()
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
            options=PAPEIS_RACI,
            help="R=Responsável · A=Aprovador · C=Consultado · I=Informado",
        )

    editado = st.data_editor(
        df_matriz, column_config=col_config, use_container_width=True,
        hide_index=True, num_rows="fixed", key=f"editor_raci_{etapa['id']}",
    )

    cs1, cs2 = st.columns([1, 4])
    if cs1.button("💾 Salvar Matriz", type="primary", key=f"savemtx_{etapa['id']}",
                  use_container_width=True):
        novas = []
        for i, row in editado.iterrows():
            original = atividades[i] if i < len(atividades) else {}
            papeis = {p: row.get(p, "") or "" for p in pessoas}
            novas.append({
                "id": original.get("id", datetime.now().timestamp()),
                "atividade": row["Atividade"],
                "prioridade": row["Prioridade"],
                "status": row["Status"],
                "data_prevista": row["Data Prevista"] or None,
                "data_entregue": row["Data Entregue"] or None,
                "papeis": papeis,
            })
        etapa["atividades"] = novas
        salvar_fn()
        st.success("Matriz salva!")
        st.rerun()

    st.caption(LEGENDA_RACI)

    with st.expander("🗑️ Excluir uma atividade"):
        for idx_a, a in enumerate(atividades):
            cdel1, cdel2 = st.columns([5, 1])
            cdel1.write(f"{a.get('atividade','')}")
            if cdel2.button("Excluir", key=f"delat_{etapa['id']}_{idx_a}", use_container_width=True):
                etapa["atividades"].pop(idx_a)
                salvar_fn()
                st.rerun()
