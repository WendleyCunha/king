"""
KingStar — Módulo de Tickets — filas.py
─────────────────────────────────────────────────────────────────────────────
Painel de Tickets (topo, independente): busca global + botões clicáveis
("views") — Meus tickets, Abertos, Em andamento, Urgentes, SLA vencidos,
Todos — mais um botão por Departamento cadastrado (mostrando pra QUALQUER
atendente quais tickets aquele setor precisa responder: abertos direto pro
setor + pendências vindas de outro setor). É renderizado FORA dos 3 painéis
redimensionáveis (Ações/Lista/Detalhe) — como as colunas de baixo já rolam
por dentro de si mesmas (não a página toda), esse painel fica sempre
visível sem precisar de nenhum truque de CSS sticky.

A seleção de qual "view" está ativa fica em st.session_state.tk_fila_selecionada
e é lida por _render_conteudo_fila_selecionada, chamada de dentro da coluna
"Lista" (ver mod_tickets.py), que mostra só os tickets da fila escolhida.
"""
import time
import streamlit as st

from .common import (
    esc, _html, texto_busca, listar_departamentos, cor_departamento,
    _swatch_dept, tickets_pendentes_do_setor, solicitacoes_abertas_para_setor,
    solicitacoes_abertas, _paginar, _nav_paginas, responder_solicitacao_setor,
)
from .strip import _render_ticket_strip

# Views fixas do Painel de Tickets — (chave interna, rótulo mostrado no botão)
_FILA_DEFS = [
    ("meus",         "📌 Meus tickets"),
    ("aberto",       "Abertos"),
    ("em_andamento", "Em andamento"),
    ("urgente",      "Urgentes"),
    ("vencidos",     "SLA vencidos"),
    ("global",       "🌐 Todos"),
]


def _render_painel_tickets_topo(user, papel, meus, f_abertos, f_andam, f_urg, f_venc, f_global):
    """
    PAINEL DE TICKETS — cartão independente, renderizado ACIMA dos 3 painéis
    redimensionáveis, sem pertencer a nenhum deles. Reúne a busca global +
    os botões clicáveis de "view" (antes eram abas dentro da coluna Lista).
    Clicar num botão só troca st.session_state.tk_fila_selecionada e dá
    rerun — quem realmente desenha a lista de tickets é
    _render_conteudo_fila_selecionada, chamada separadamente de dentro da
    coluna Lista.
    """
    if "tk_fila_selecionada" not in st.session_state:
        st.session_state.tk_fila_selecionada = "meus"

    contagens = {
        "meus": len(meus), "aberto": len(f_abertos), "em_andamento": len(f_andam),
        "urgente": len(f_urg), "vencidos": len(f_venc), "global": len(f_global),
    }

    deps_cadastrados = [d.get("nome") for d in listar_departamentos() if d.get("nome")]
    setores_info = []
    for nome_dep in deps_cadastrados:
        qtd = len(tickets_pendentes_do_setor(f_global, nome_dep))
        setores_info.append((f"setor::{nome_dep}", nome_dep, qtd))

    with st.container(key="tk_painel_topo"):
        st.markdown(
            '<div class="tk-painel-topo-titulo">📋 Painel de Tickets</div>',
            unsafe_allow_html=True,
        )
        st.text_input(
            "", placeholder="Busca global: ID, assunto, cliente, código, descrição, comentário...",
            label_visibility="collapsed", key="tk_busca",
        )

        with st.container(key="tk_view_buttons"):
            for chave, label in _FILA_DEFS:
                ativo = st.session_state.tk_fila_selecionada == chave
                if st.button(f"{label} ({contagens[chave]})", key=f"tkview_{chave}",
                             type="primary" if ativo else "secondary"):
                    st.session_state.tk_fila_selecionada = chave
                    st.session_state.tk_modo = "lista"
                    st.rerun()
            for chave, nome_dep, qtd in setores_info:
                ativo = st.session_state.tk_fila_selecionada == chave
                if st.button(f"{_swatch_dept(nome_dep)} {nome_dep} ({qtd})", key=f"tkview_{chave}",
                             type="primary" if ativo else "secondary"):
                    st.session_state.tk_fila_selecionada = chave
                    st.session_state.tk_modo = "lista"
                    st.rerun()


def _render_conteudo_fila_selecionada(user, papel, meus, f_abertos, f_andam, f_urg, f_venc, f_global):
    """Mostra a lista de tickets da view/departamento selecionado no Painel
    de Tickets (topo), já aplicando o filtro de busca global. Chamada de
    dentro da coluna "Lista", que é quem tem a rolagem própria."""
    busca = st.session_state.get("tk_busca", "")
    b = busca.strip().lower() if busca else ""

    def _filtra(lista):
        return [t for t in lista if b in texto_busca(t)] if b else lista

    fila_sel = st.session_state.get("tk_fila_selecionada", "meus")

    mapa_filas = {
        "meus": meus, "aberto": f_abertos, "em_andamento": f_andam,
        "urgente": f_urg, "vencidos": f_venc, "global": f_global,
    }

    if fila_sel.startswith("setor::"):
        nome_dep = fila_sel.split("setor::", 1)[1]
        filtrados = _filtra(tickets_pendentes_do_setor(f_global, nome_dep))
        cor = cor_departamento(nome_dep)
        st.markdown(_html(f"""
        <div style="font-size:0.82rem;color:#64778d;margin-bottom:8px;">
            Tickets que o setor <span class="tk-setor-pill" style="background:{cor};">{esc(nome_dep)}</span>
            precisa tratar: os abertos diretamente para ele + os que outro setor pediu
            retorno. Qualquer atendente pode ver esta fila — é uma visão de
            transparência entre equipes, o ticket continua único.
        </div>"""), unsafe_allow_html=True)
        st.markdown(f"**{len(filtrados)} ticket(s) pendente(s) com {nome_dep}**")
        if not filtrados:
            st.info(f"Nenhuma pendência aberta para {nome_dep} no momento.")
        else:
            _render_lista_pendencias_setor(filtrados, nome_dep, user, papel, fila_sel)
        return

    lista = mapa_filas.get(fila_sel, meus)
    filtrados = _filtra(lista)
    st.markdown(f"**{len(filtrados)} ticket(s)**")
    if not filtrados:
        st.info("Nenhum ticket nesta fila.")
    else:
        _render_lista_em_grid(filtrados, user, papel, fila_sel)


def _render_lista_pendencias_setor(lista, nome_dep, user, papel, chave):
    pagina_itens, pag_atual, total_paginas, pag_key, total = _paginar(lista, f"pend_{chave}")
    for t in pagina_itens:
        tid = t.get("id","")
        dep_origem = t.get("departamento") or t.get("categoria") or "—"
        eh_dono = dep_origem == nome_dep
        pedidos_abertos = solicitacoes_abertas_para_setor(t, nome_dep)

        # Tag de origem — mesma tirinha padrão do resto do sistema, só que
        # com esta tag extra pra deixar claro se o chamado nasceu neste
        # setor ou veio pedido de outro.
        cor = cor_departamento(nome_dep)
        if eh_dono:
            tag_origem = f'<span class="tk-setor-pill" style="background:{cor};">🏠 aberto aqui</span> '
        else:
            cor_o = cor_departamento(dep_origem)
            tag_origem = (f'<span class="tk-setor-pill" style="background:{cor_o};">'
                          f'↩ vindo de {esc(dep_origem)}</span> ')

        _render_ticket_strip(t, user, papel, key_ctx=f"setor_{chave}_{tid}",
                             extra_badge_html=tag_origem)

        if eh_dono and not pedidos_abertos:
            st.caption("🏠 Chamado aberto diretamente neste setor — aguardando tratativa/classificação.")

        for pedido in pedidos_abertos:
            st.markdown(_html(f"""
            <div style="border-left:3px solid {cor};background:#fafafa;border-radius:6px;
                        padding:8px 10px;margin:6px 0;">
                <span class="tk-setor-pill" style="background:{cor_departamento(pedido.get('setor_origem',''))};">
                    {esc(pedido.get('setor_origem',''))}
                </span>
                <span style="font-size:0.78rem;color:#64778d;"> pediu em
                {esc(str(pedido.get('solicitado_em',''))[:16])} ({esc(pedido.get('solicitado_por_nome',''))}):</span>
                <div style="font-size:0.85rem;color:#2c3e50;margin-top:2px;">{esc(pedido.get('mensagem',''))}</div>
            </div>"""), unsafe_allow_html=True)

            dep_user = user.get("departamento")
            pode_responder = (papel in ("supervisor", "adm")) or (dep_user == nome_dep)
            if pode_responder:
                with st.form(f"form_resp_{chave}_{tid}_{pedido.get('id')}", clear_on_submit=True):
                    resp_txt = st.text_area("Resposta", height=70, key=f"resp_txt_{tid}_{pedido.get('id')}",
                                            placeholder="Escreva a resposta pro setor solicitante...")
                    if st.form_submit_button(f"✅ Responder e concluir pendência ({nome_dep})",
                                             type="primary", use_container_width=True):
                        if resp_txt.strip():
                            responder_solicitacao_setor(tid, pedido, resp_txt.strip(), user)
                            st.success("Pendência respondida!"); time.sleep(.6); st.rerun()
                        else:
                            st.warning("Escreva uma resposta antes de concluir.")
    _nav_paginas(pag_atual, total_paginas, pag_key, total)


def _render_lista_em_grid(filtrados, user, papel, fila):
    modo_agrupar = st.selectbox(
        "🗂️ Organizar por",
        ["Motivo Pai", "Departamento", "Sem agrupamento"],
        index=0, key=f"tk_agrupar_{fila}"
    )

    from collections import defaultdict
    from .common import solicitacoes_abertas as _sols_abertas
    from .common import ticket_vencido_pendente as _venc_pend

    grupos = defaultdict(list)
    if modo_agrupar == "Departamento":
        for t in filtrados:
            grupos[t.get("departamento") or t.get("categoria") or "—"].append(t)
    elif modo_agrupar == "Motivo Pai":
        for t in filtrados:
            grupos[t.get("motivo_pai") or t.get("tabulacao") or "Sem motivo"].append(t)
    else:
        grupos["__todos__"] = filtrados

    for chave in sorted(grupos.keys()):
        lst = grupos[chave]
        n_venc = sum(1 for t in lst if _venc_pend(t))
        n_pend_setor = sum(1 for t in lst if _sols_abertas(t))
        extra = (f' · <span style="color:#8A6D1F;font-weight:700;">⏳ {n_venc} com prazo '
                 f'estourado</span>') if n_venc else ""
        extra += (f' · <span style="color:#2563EB;font-weight:700;">📨 {n_pend_setor} com '
                  f'pendência de setor</span>') if n_pend_setor else ""

        if modo_agrupar != "Sem agrupamento":
            icone = "📋" if modo_agrupar == "Motivo Pai" else "🏢"
            st.markdown(_html(
                f'<div style="margin:14px 0 6px;font-weight:700;color:#2c3e50;">'
                f'{icone} {esc(chave)} <span style="color:#64778d;font-weight:500;">— '
                f'{len(lst)} ticket(s)</span>{extra}</div>'), unsafe_allow_html=True)

        pagina_itens, pag_atual, total_paginas, pag_key, total = _paginar(
            lst, f"lista_{fila}_{chave}"
        )
        for t in pagina_itens:
            _render_ticket_strip(t, user, papel, key_ctx=f"{fila}_{chave}_{t.get('id','')}")
        _nav_paginas(pag_atual, total_paginas, pag_key, total)
