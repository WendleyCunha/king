"""
KingStar — Módulo de Tickets  (v4 — Motivos Pai/Filho/Etapa + SLA em cascata)
─────────────────────────────────────────────────────────────────────────────
Este arquivo é o ORQUESTRADOR do módulo de tickets: monta a página (CSS
global, painéis redimensionáveis, roteamento entre modos) e delega cada
pedaço da UI para os arquivos dentro da pasta `tickets/`, que fica na RAIZ
do repositório (mesma pasta do main.py, não dentro de modulo/):

    tickets/common.py    → constantes, helpers, SLA, CRUD Firestore,
                            pendências entre setores, classificação de
                            filas, visibilidade, histórico do cliente
    tickets/strip.py      → componente único de card de ticket (tirinha)
    tickets/novo.py        → abertura de novo chamado
    tickets/filas.py       → Filas de Trabalho em abas + abas por setor
    tickets/detalhe.py     → painel de detalhe do ticket (3ª coluna)
    tickets/geral.py       → Visão Geral da Operação + Sync Zendesk

Histórico de versões (changelog) — mantido aqui por ser a porta de entrada
do módulo:

  [10] CLASSIFICAÇÃO EM ÁRVORE (Motivo Pai → Motivo Filho → Etapa):
       - Abertura do chamado escolhe Departamento + MOTIVO PAI (que carrega
         o SLA de triagem, ex.: 5 dias) — isso é o SLA1.
       - O atendente, ao tratar o ticket, define o MOTIVO FILHO e a ETAPA.
         Esse é o momento em que o SLA1 é congelado (cumprido/perdido) —
         serve pra saber se ele chegou a tempo de pelo menos analisar e
         direcionar o caso.
       - Etapa PRETA: não exige nada além disso; o prazo continua sendo o
         do Motivo Pai (SLA1), mesmo depois de classificada.
       - Etapa VERMELHA: exige que o atendente informe uma DATA FUTURA
         (SLA2). Ao confirmar, a trilha (Motivo Filho + Etapa + Data) fica
         TRAVADA PARA SEMPRE — evita "disfarçar" atraso mudando a etapa
         depois. A partir daí, o prazo mostrado no ticket passa a ser essa
         data (substitui o SLA do Pai enquanto essa etapa estiver vigente).
       - Etapas podem "reaproveitar" a árvore de outro Motivo Filho, e
         podem vincular atendentes específicos (reatribuição automática).

  [11] ALERTA DE INTERAÇÃO (🔵 piscante azul-claro): toda vez que alguém
       interage num ticket sem ser o(s) atendente(s) responsável(is), um
       badge azul piscante aparece pra eles até que ELES PRÓPRIOS interajam.

  [12] REGISTRO DE CONTATO/OBSERVAÇÃO: qualquer pessoa com visibilidade do
       ticket pode registrar uma observação avulsa, disparando o alerta [11].

  [13] PENDÊNCIAS ENTRE SETORES (v4.1): nasce automaticamente (via
       "Departamento vinculado" de um Motivo/Etapa) ou manualmente. NÃO cria
       ticket novo — fica tudo no MESMO ticket, com cor própria por setor e
       aba extra por Departamento em "Filas de Trabalho".

  [14] TIRINHA HORIZONTAL: todo lugar que mostra um ticket usa o mesmo
       componente `_render_ticket_strip` (ver tickets/strip.py).

  [15] PAINÉIS REDIMENSIONÁVEIS + DETALHE LATERAL (v4.2): o detalhe do
       ticket abre numa 3ª coluna à direita (estilo cliente de e-mail), com
       divisas arrastáveis (largura salva no sessionStorage do navegador).

  [16] SPLIT EM PACOTE (v4.3): o arquivo único mod_tickets.py foi
       desmembrado neste orquestrador + pacote `tickets/`, só para
       facilitar manutenção — nenhum comportamento mudou e a chamada
       externa (`renderizar_tickets`) continua idêntica.
"""
import streamlit as st

# ── Reexporta TUDO que o antigo mod_tickets.py monolítico expunha, para não
# quebrar nenhum outro arquivo do sistema (ex.: home.py) que faça
# `from modulo.mod_tickets import X` direto, sem passar por renderizar_tickets.
from tickets.common import (
    BRT, COLECAO, ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_TOKEN, ZENDESK_VIEW_ID,
    STATUS_CFG, PRIO_CFG, STATUS_ABERTOS,
    GOLD, GOLD_WARN, GOLD_VENC, GREEN_OK, BLUE_INFO, DEPT_PALETTE,
    agora_brt, _html, esc, texto_busca, transferir_tickets,
    deadline_ativo, sla_label, sla_restante, pill, sla_estado,
    ticket_vencido_pendente, sla_foi_perdido,
    tem_interacao_nao_vista,
    cor_departamento, solicitacoes_abertas, solicitacoes_abertas_para_setor,
    ticket_tem_pendencia_para_setor, registrar_solicitacao_setor,
    responder_solicitacao_setor, tickets_pendentes_do_setor, departamentos_com_pendencia,
    JANELA_VALIDACAO_H, classificar_fila,
    ticket_visivel,
    normalizar_codigo_cliente, tickets_do_cliente,
    listar_tickets, criar_ticket, atualizar_ticket, adicionar_comentario,
    vincular_ticket_relacionado, sync_zendesk, deletar_todos_tickets,
    _caminho_motivo, PAGE_SIZE_CARDS, _paginar, _nav_paginas,
    get_db, listar_departamentos, listar_tabulacoes, resolver_destinatario_ticket,
    listar_usuarios,
)
from .mod_motivos import (
    listar_motivos_pai, motivos_pai_do_departamento,
    listar_motivos_filho, listar_motivos_filho_de,
    listar_etapas, listar_etapas_de, resolver_etapa_final,
)
from tickets.strip import _render_ticket_strip, _badges_ticket
from tickets.novo import _render_novo
from tickets.filas import _render_filas_em_abas, _render_lista_em_grid, _render_lista_pendencias_setor
from tickets.detalhe import (
    _render_painel_lateral_detalhe, _carregar_e_render_detalhe, _detalhe_corpo,
    _bloco_classificacao, _bloco_pendencias_setor,
)
from tickets.geral import (
    _render_visao_geral_operacao, _render_sync,
    _gerar_excel_relatorio, _aba_dashboard, _aba_por_atendente,
    _aba_por_motivo, _aba_sla_perdido, _aba_exportar,
)


# ═══════════════════════════════════════════════════════════════════
# PAINÉIS REDIMENSIONÁVEIS (Filas ↔ Lista ↔ Detalhe) — arrasto client-side
# ═══════════════════════════════════════════════════════════════════
def _render_estilo_paineis_redimensionaveis():
    """CSS + JS que transforma a divisa entre as colunas de 'Filas' / 'Lista'
    / 'Detalhe do ticket' em barras arrastáveis (mesmo padrão de painéis
    redimensionáveis de clientes de e-mail tipo Outlook/Gmail, e do mesmo
    jeito que a barra lateral NATIVA do Streamlit já se comporta). Puramente
    client-side: a largura escolhida fica salva no sessionStorage do
    navegador (por aba) e é reaplicada a cada rerun do Streamlit, então o
    ajuste "sobrevive" a cliques/reruns normais (mas não a um F5).

    IMPORTANTE: o CSS é injetado via st.markdown normalmente (funciona sem
    problema, `<style>` inserido via innerHTML é aplicado pelo navegador).
    Mas o <script> NÃO pode ir por st.markdown: por especificação do HTML,
    tags <script> inseridas via innerHTML (que é como o Streamlit renderiza
    st.markdown) simplesmente NUNCA executam — não é bug do Streamlit, é
    proteção do próprio navegador. Por isso o script roda dentro de um
    componente de verdade (`st.components.v1.html`, que cria um iframe onde
    scripts executam normalmente) e, de dentro dele, usa
    `window.parent.document` para enxergar e arrastar os elementos da
    página principal (funciona porque o iframe é same-origin).

    Depende de atributos internos do Streamlit (data-testid="stColumn" /
    "stHorizontalBlock") que não são API pública — se uma futura versão do
    Streamlit renomear esses atributos, o arrasto simplesmente para de
    funcionar (sem quebrar a tela, só volta pras proporções padrão).
    """
    st.markdown(_html("""
    <style>
    div[class*="st-key-tk_paineis"] div[data-testid="stHorizontalBlock"] {
        position: relative;
        align-items: flex-start;
    }
    .tk-resizer {
        position: absolute; top: 0; bottom: 0; width: 10px; margin-left: -5px;
        cursor: col-resize; z-index: 999;
        display: flex; align-items: center; justify-content: center;
    }
    .tk-resizer::after {
        content: ""; width: 4px; height: 42px; border-radius: 3px;
        background: #D8CBA0; transition: background .15s, height .15s;
    }
    .tk-resizer:hover::after, .tk-resizer.tk-ativo::after {
        background: #C9A84C; height: 70px;
    }

    /* ═══════════════════════════════════════════════════════════
       ROLAGEM INTERNA INDEPENDENTE — cada coluna ("Ações", "Lista",
       "Detalhe") rola por dentro, sem empurrar as outras, igual ao
       painel de e-mail / WhatsApp Web. Cada coluna vira sua própria
       "janelinha" com altura travada relativa à tela e overflow
       próprio. Pura CSS, sem depender de JS ou de posições internas
       do Streamlit — só a altura em si (calc(100vh - Npx)) é uma
       estimativa do espaço ocupado pelo cabeçalho acima; ajuste o
       valor abaixo se sobrar/faltar espaço no seu layout.
       ═══════════════════════════════════════════════════════════ */
    div[class*="st-key-tk_paineis"] div[data-testid="stColumn"] {
        max-height: calc(100vh - 230px);
        overflow-y: auto;
        overflow-x: hidden;
        padding-right: 6px;
    }
    div[class*="st-key-tk_paineis"] div[data-testid="stColumn"]::-webkit-scrollbar {
        width: 8px;
    }
    div[class*="st-key-tk_paineis"] div[data-testid="stColumn"]::-webkit-scrollbar-track {
        background: transparent;
    }
    div[class*="st-key-tk_paineis"] div[data-testid="stColumn"]::-webkit-scrollbar-thumb {
        background: #D8CBA0; border-radius: 4px;
    }
    div[class*="st-key-tk_paineis"] div[data-testid="stColumn"]::-webkit-scrollbar-thumb:hover {
        background: #C9A84C;
    }

    /* ═══════════════════════════════════════════════════════════
       CABEÇALHO DE ABAS FIXO ("Meus tickets" / "Abertos" / ... /
       "CX" / "Logística" / etc.) — fica "grudado" no topo da coluna
       de Lista, sempre visível e clicável, igual um cabeçalho de
       card fixo, enquanto só os cards de ticket abaixo rolam.

       PAINEL DE DEMANDAS: a busca global (container "tk_busca_wrap") e a
       barra de abas (data-baseweb="tab-list") são DOIS elementos sticky
       empilhados um sobre o outro (cada um com seu próprio `top`), que
       juntos formam a aparência de um único cartão fixo no topo — como um
       painel de demandas — enquanto a lista de tickets abaixo rola
       normalmente. O `top: 54px` da barra de abas é a altura estimada do
       cartão da busca acima dela; se sobrar/faltar uma folguinha entre os
       dois ao rolar, ajuste esse valor (e o padding do tk_busca_wrap logo
       abaixo) até encostarem perfeitamente.
       ═══════════════════════════════════════════════════════════ */
    div[class*="st-key-tk_paineis"] div[class*="st-key-tk_busca_wrap"] {
        position: sticky;
        top: 0;
        z-index: 41;
        background: #FFFFFF;
        padding: 10px 12px 8px;
        margin: 0 -6px 0;
        border-radius: 10px 10px 0 0;
        box-shadow: 0 3px 6px rgba(0,0,0,0.07);
    }
    div[class*="st-key-tk_paineis"] div[data-baseweb="tab-list"] {
        position: sticky;
        top: 54px;
        z-index: 40;
        background: #FFFFFF;
        padding: 8px 6px 0;
        margin: 0 -6px 8px;
        border-radius: 0 0 10px 10px;
        box-shadow: 0 3px 6px rgba(0,0,0,0.07);
    }
    </style>
    """), unsafe_allow_html=True)

    import streamlit.components.v1 as components
    components.html("""
    <script>
    (function() {
        const doc = window.parent.document;

        function montarResizers() {
            const wrap = doc.querySelector('div[class*="st-key-tk_paineis"]');
            if (!wrap) return false;
            const row = wrap.querySelector('div[data-testid="stHorizontalBlock"]');
            if (!row) return false;
            const cols = Array.from(row.querySelectorAll(':scope > div[data-testid="stColumn"]'));
            if (cols.length < 2) return false;

            row.querySelectorAll('.tk-resizer').forEach(function(el) { el.remove(); });

            function aplicarLarguraSalva(chave, col) {
                const salva = sessionStorage.getItem(chave);
                if (salva) {
                    col.style.flex = '0 0 ' + salva + 'px';
                    col.style.width = salva + 'px';
                }
            }
            aplicarLarguraSalva('tk_larg_filas', cols[0]);
            cols[1].style.flex = '1 1 0';
            cols[1].style.minWidth = '0';
            if (cols.length >= 3) aplicarLarguraSalva('tk_larg_detalhe', cols[2]);

            function criarResizer(colAlvo, chave, cresceParaDireita, referencia, min, max) {
                const barra = doc.createElement('div');
                barra.className = 'tk-resizer';
                function posicionar() {
                    barra.style.left = (referencia.getBoundingClientRect().right
                                         - row.getBoundingClientRect().left) + 'px';
                }
                posicionar();
                row.appendChild(barra);

                barra.addEventListener('mousedown', function(e) {
                    e.preventDefault();
                    barra.classList.add('tk-ativo');
                    const larguraInicial = colAlvo.getBoundingClientRect().width;
                    const xInicial = e.clientX;
                    function mover(ev) {
                        const delta = cresceParaDireita ? (ev.clientX - xInicial) : -(ev.clientX - xInicial);
                        const nova = Math.max(min, Math.min(max, larguraInicial + delta));
                        colAlvo.style.flex = '0 0 ' + nova + 'px';
                        colAlvo.style.width = nova + 'px';
                        posicionar();
                    }
                    function soltar() {
                        barra.classList.remove('tk-ativo');
                        sessionStorage.setItem(chave, Math.round(colAlvo.getBoundingClientRect().width));
                        doc.removeEventListener('mousemove', mover);
                        doc.removeEventListener('mouseup', soltar);
                    }
                    doc.addEventListener('mousemove', mover);
                    doc.addEventListener('mouseup', soltar);
                });
            }

            // resizer 1: entre "Filas" (cols[0]) e "Lista" (cols[1])
            criarResizer(cols[0], 'tk_larg_filas', true, cols[0], 160, 420);
            // resizer 2 (só existe quando o Detalhe está aberto): entre
            // "Lista" (cols[1]) e "Detalhe" (cols[2])
            if (cols.length >= 3) {
                criarResizer(cols[2], 'tk_larg_detalhe', false, cols[1], 320, 900);
            }
            return true;
        }

        const tentativa = setInterval(function() {
            if (montarResizers()) clearInterval(tentativa);
        }, 120);
        setTimeout(function() { clearInterval(tentativa); }, 6000);
    })();
    </script>
    """, height=0, width=0)


# ═══════════════════════════════════════════════════════════════════
# RENDERIZAÇÃO
# ═══════════════════════════════════════════════════════════════════
def renderizar_tickets(papel: str, user: dict = None):
    if user is None:
        user = {"role": papel, "nome": "Usuário", "usuario": "user", "departamento": ""}

    todos_geral = listar_tickets()
    todos = [t for t in todos_geral if ticket_visivel(t, user, papel)]

    ct = {
        "todos":       len(todos),
        "aberto":      sum(1 for t in todos if t.get("status")=="aberto"),
        "em_andamento":sum(1 for t in todos if t.get("status")=="em_andamento"),
        "aguardando":  sum(1 for t in todos if t.get("status")=="aguardando"),
        "resolvido":   sum(1 for t in todos if t.get("status")=="resolvido"),
        "urgente":     sum(1 for t in todos if t.get("prioridade")=="urgente"),
        "zendesk":     sum(1 for t in todos if "zendesk" in t.get("origem","")),
    }

    _render_estilo_paineis_redimensionaveis()

    st.markdown(_html("""
    <style>
    .tk-badge { background:#e2e8f0; color:#475569; padding:2px 8px;
        border-radius:10px; font-size:0.72rem; font-weight:700; }
    .tk-badge-red { background:#FBF3D9; color:#8A6D1F; }
    .tk-banner { animation: tkpiscar 1.2s infinite;
        background:#FBF3D9; color:#7A5C12; border:2px solid #8A6D1F;
        border-radius:10px; padding:12px 16px; margin-bottom:14px;
        font-weight:800; font-size:0.95rem; }
    @keyframes tkpiscar { 0%,100%{opacity:1;} 50%{opacity:.30;} }
    .tk-blink { animation: tkpiscar 1s infinite;
        background:#8A6D1F; color:#fff; padding:2px 10px; border-radius:12px;
        font-size:0.72rem; font-weight:800; display:inline-block; }
    .tk-equipe-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:14px 16px; margin-bottom:8px; border-top:4px solid #C9A84C; }
    .tk-blink-venc { animation:tkpiscar 1s infinite; background:#8A6D1F; color:#fff;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:800; }
    .tk-blink-warn { animation:tkpiscar 1.6s infinite; background:#FBF3D9; color:#7A5C12;
        border:1px solid #D4A12C; padding:1px 8px; border-radius:10px;
        font-size:0.7rem; font-weight:700; }
    .tk-blink-info { animation:tkpiscar 1.3s infinite; background:#DBEAFE; color:#1D4ED8;
        border:1px solid #60A5FA; padding:1px 8px; border-radius:10px;
        font-size:0.7rem; font-weight:800; }
    .tk-badge-val { background:#F3ECD9; color:#6B5A2A; border:1px solid #A98C3D;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:700; }
    .tk-badge-sla1-ok { background:#DCFCE7; color:#15803D; border:1px solid #16A34A;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:700; }
    .tk-badge-sla1-perd { background:#F3ECD9; color:#8A6D1F; border:1px solid #A98C3D;
        padding:1px 8px; border-radius:10px; font-size:0.7rem; font-weight:700; }
    .tk-setor-pill { padding:1px 9px; border-radius:10px; font-size:0.7rem;
        font-weight:800; color:#fff; display:inline-block; }
    .tk-setor-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:12px 14px; margin-bottom:10px; }

    /* ═══════════════════════════════════════════════════════════
       TIRINHA HORIZONTAL — padrão ÚNICO de card de ticket, usado em
       TODO lugar do sistema que mostra um ticket (Filas de Trabalho,
       abas por Departamento, Visão Geral por Atendente, SLA vencidos).
       O clique é um BOTÃO DE VERDADE (visível), não mais um botão
       invisível sobreposto — mais robusto e sempre clicável. O botão
       forma a "linha de cima" (ícone + ID + título) e o restante das
       informações (badges, cliente, SLA) fica colado visualmente
       embaixo, no mesmo estilo de card conectado do padrão antigo.
       ═══════════════════════════════════════════════════════════ */
    div[class*="st-key-tkwrap_"] {
        margin-bottom: 10px;
    }
    div[class*="st-key-tkwrap_"] button {
        text-align:left !important; justify-content:flex-start !important;
        background:#fff !important; border:1px solid #e2e8f0 !important;
        border-bottom:none !important; border-left:5px solid #C9A84C !important;
        border-radius:10px 10px 0 0 !important; color:#2c3e50 !important;
        font-weight:700 !important; font-size:0.92rem !important;
        padding:10px 16px 6px !important; margin-bottom:0 !important;
        height:auto !important; white-space:normal !important;
        transition:background .15s, box-shadow .15s;
    }
    div[class*="st-key-tkwrap_"] button:hover {
        background:#FBF6E6 !important; border-color:#C9A84C !important;
    }
    div[class*="st-key-tkwrap_venc_"] button {
        border-left-color:#8A6D1F !important; animation: tkbordapiscar 1s infinite;
    }
    div[class*="st-key-tkwrap_warn_"] button {
        border-left-color:#D4A12C !important; animation: tkbordapiscarsuave 1.6s infinite;
    }
    @keyframes tkbordapiscar { 0%,100%{box-shadow:0 0 0 0 rgba(138,109,31,0);} 50%{box-shadow:0 0 0 3px rgba(138,109,31,.35);} }
    @keyframes tkbordapiscarsuave { 0%,100%{box-shadow:0 0 0 0 rgba(212,161,44,0);} 50%{box-shadow:0 0 0 3px rgba(212,161,44,.30);} }

    .tk-stripbody {
        background:#fff; border:1px solid #e2e8f0; border-top:none;
        border-left:5px solid #C9A84C; border-radius:0 0 10px 10px;
        padding:6px 16px 10px; margin-top:-1px;
    }
    .tk-stripbody.aberto-agora { box-shadow:0 0 0 2px #2563EB inset; }
    .tk-strip-meta { font-size:0.76rem; color:#64778d; margin-top:2px; line-height:1.6; }
    .tk-strip-pills { white-space:nowrap; margin-bottom:2px; display:block; }
    .tk-strip-bottom { display:flex; align-items:center; gap:10px; margin-top:7px; }
    .tk-strip-slabar { flex:1; background:#e8ecf0; border-radius:4px; height:5px; }
    .tk-strip-slafill { height:5px; border-radius:4px; }
    .tk-strip-slatext { font-size:0.72rem; color:#64778d; white-space:nowrap; }

    button[kind="primary"], button[kind="primaryFormSubmit"],

    button[data-testid="baseButton-primary"], button[data-testid="baseButton-primaryFormSubmit"],
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
        background-color:#C9A84C !important; border-color:#C9A84C !important;
        color:#fff !important; }
    button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover,
    button[data-testid="baseButton-primary"]:hover, button[data-testid="baseButton-primaryFormSubmit"]:hover,
    [data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background-color:#b8973f !important; border-color:#b8973f !important;
        color:#fff !important; }
    [data-testid="stFormSubmitButton"] button {
        background-color:#C9A84C !important; border-color:#C9A84C !important; color:#fff !important; }
    [data-testid="stFormSubmitButton"] button:hover {
        background-color:#b8973f !important; border-color:#b8973f !important; color:#fff !important; }
    .stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
        border-color:#C9A84C !important; box-shadow:0 0 0 1px #C9A84C !important; }
    div[data-baseweb="select"] > div:focus-within,
    div[data-baseweb="select"] > div[aria-expanded="true"],
    div[data-baseweb="input"]:focus-within {
        border-color:#C9A84C !important; box-shadow:0 0 0 1px #C9A84C !important; }
    div[data-baseweb="base-input"] input { caret-color:#C9A84C !important; }
    </style>
    """), unsafe_allow_html=True)

    if "tk_fila"          not in st.session_state: st.session_state.tk_fila          = "meus"
    if "tk_ticket_aberto" not in st.session_state: st.session_state.tk_ticket_aberto  = None
    if "tk_modo"          not in st.session_state: st.session_state.tk_modo          = "lista"

    uname = user.get("usuario","")

    buckets = {"meus": [], "aberto": [], "em_andamento": [], "urgente": [], "vencidos": []}
    for t in todos:
        f = classificar_fila(t, user)
        if f:
            buckets[f].append(t)
    meus      = buckets["meus"]
    f_abertos = buckets["aberto"]
    f_andam   = buckets["em_andamento"]
    f_urg     = buckets["urgente"]
    f_venc    = buckets["vencidos"]
    f_global  = todos_geral

    modo = st.session_state.tk_modo
    mostra_detalhe = bool(st.session_state.tk_ticket_aberto) and modo in ("lista", None)

    with st.container(key="tk_paineis"):
        if mostra_detalhe:
            col_filas, col_main, col_detalhe = st.columns([1, 2, 1.4])
        else:
            col_filas, col_main = st.columns([1, 3])
            col_detalhe = None

        with col_filas:
            st.markdown("**Ações**")
            if st.button("➕ Novo Ticket", use_container_width=True, type="primary"):
                st.session_state.tk_modo = "novo"; st.session_state.tk_ticket_aberto = None; st.rerun()

            if papel in ("supervisor", "adm"):
                if st.button("📊 Visão Geral da Operação", use_container_width=True,
                             type="primary" if st.session_state.tk_modo == "equipe" else "secondary"):
                    st.session_state.tk_modo = "equipe"; st.session_state.tk_ticket_aberto = None; st.rerun()

            if papel == "adm":
                if st.button("🔄 Sync Zendesk", use_container_width=True):
                    st.session_state.tk_modo = "sync"; st.session_state.tk_ticket_aberto = None; st.rerun()

            st.markdown('<div style="border-top:1px dashed #cbd5e1;margin:14px 0 6px;"></div>',
                        unsafe_allow_html=True)
            if st.button("📋 Ver Filas de Trabalho", use_container_width=True,
                         type="primary" if st.session_state.tk_modo in ("lista", None) else "secondary"):
                st.session_state.tk_modo = "lista"; st.rerun()

        with col_main:
            if f_venc:
                st.markdown(_html(
                    f'<div class="tk-banner">⏳ {len(f_venc)} ticket(s) com prazo ESTOURADO '
                    f'aguardando tratativa! Verifique a aba "SLA vencidos".</div>'
                ), unsafe_allow_html=True)

            if modo in ("lista", None):
                _render_filas_em_abas(user, papel, meus, f_abertos, f_andam, f_urg, f_venc, f_global)
            elif modo == "novo":
                _render_novo(user)
            elif modo == "equipe":
                if papel not in ("supervisor", "adm"):
                    st.warning("🔒 Acesso restrito a Supervisores e Administradores.")
                    st.session_state.tk_modo = "lista"
                else:
                    _render_visao_geral_operacao(user, papel, todos_geral)
            elif modo == "sync":
                _render_sync()

        if col_detalhe is not None:
            with col_detalhe:
                _render_painel_lateral_detalhe(user, papel)
