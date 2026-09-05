"""
KingStar — Módulo de Tickets — whats.py  [NOVO — v18]
─────────────────────────────────────────────────────────────────────────────
WhatsApp Atendimento ao vivo: uma tela cheia, separada das "Filas de
Trabalho", pra ver e responder conversas de WhatsApp que NÃO precisam
necessariamente já ter um ticket. Ver o changelog [18] completo em
mod_tickets.py — aqui só o essencial:

  • Lê a MESMA coleção que o WhatsApp de dentro do ticket já usa
    (`WHATSAPP_COLECAO` = "whatsapp_conversas", 1 documento por telefone).
    Nenhuma coleção nova, nenhum campo novo.
  • Cruza telefone → ticket já existente comparando `cliente_telefone`
    (normalizado) dos tickets já carregados (`todos_geral`, que o
    orquestrador já tinha em mãos) — não faz nenhuma consulta extra ao
    Firestore pra isso.
  • "Aguardando resposta" é CALCULADO (última mensagem da conversa com
    `direcao == "in"`), não é um campo armazenado.
  • Presença "quem está online" reaproveita `presenca_adm`/
    `listar_admins_online` de `database_chat.py` — a MESMA fonte que o
    chat motorista↔ADM já usa. Isso é o "consolidar tudo em um só".

⚠️ PREMISSAS ASSUMIDAS (não confirmadas por você ainda — ver aviso no chat):
  1. O botão "Abrir ticket" faz uma busca por CÓDIGO DO CLIENTE (igual
     tickets/novo.py já faz) — NÃO tenta casar automaticamente por
     telefone. Se preferir o casamento automático, é uma troca pequena
     aqui dentro, mas prefiro que você confirme antes.
  2. Se o código do cliente não tiver nenhum histórico ainda, o
     formulário abre vazio (mesmo comportamento de "Regra 0" que
     tickets/novo.py já tem pra cliente novo).
  3. Presença reaproveita `database_chat.py` (import direto). Se você
     preferir que o WhatsApp de atendimento NÃO dependa desse arquivo,
     me avisa que eu tiro essa dependência e deixo a presença só como
     "não sei", sem quebrar o resto.

Ainda NÃO recebido: conteúdo de `tickets/strip.py` e `tickets/filas.py`.
Por isso, este arquivo NÃO usa `_render_ticket_strip` nem os helpers de
paginação de lá — usa `_render_bloco_historico_cliente` (de
`tickets/common.py`, que eu já tenho de verdade) pra mostrar o histórico
do cliente ao lado da conversa. Se vocês têm um jeito melhor/já pronto
pra isso, é só apontar que eu troco.
"""
import os
import sys
import time
import streamlit as st
from datetime import datetime

from .common import (
    BRT, WHATSAPP_COLECAO, GOLD, GOLD_WARN, BLUE_INFO,
    esc, _html, agora_brt, get_db,
    normalizar_telefone, normalizar_codigo_cliente,
    listar_mensagens_whatsapp, minutos_desde_ultima_mensagem_cliente,
    whatsapp_configurado, enviar_whatsapp,
    tickets_do_cliente, _render_bloco_historico_cliente,
    abrir_solicitacao_cliente, STATUS_ABERTOS,
    listar_departamentos,
)
from modulo.mod_motivos import motivos_pai_do_departamento

# ── Import de database_chat.py (raiz do projeto), reaproveitando o mesmo
# truque de path que tickets/common.py já usa pra importar database.py ──
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _root not in sys.path:
    sys.path.insert(0, _root)
try:
    from database_chat import (
        marcar_presenca_adm, listar_admins_online,
        atualizar_status_presenca_adm, obter_status_presenca_adm,
    )
    _PRESENCA_DISPONIVEL = True
except Exception:
    # Se database_chat.py não existir nesse ambiente, ou o import falhar
    # por qualquer motivo, a tela de WhatsApp Atendimento continua
    # funcionando — só sem o indicador de "quem está online agora" nem
    # o widget de Status (Online/Offline/Pausa).
    _PRESENCA_DISPONIVEL = False


# ═══════════════════════════════════════════════════════════════════
# Leitura da coleção whatsapp_conversas — SEM criar função nova em
# common.py de propósito, pra não mexer num arquivo que não é o foco
# deste pedido. Fica só aqui, local a este módulo.
# ═══════════════════════════════════════════════════════════════════
def _carregar_todas_conversas_whatsapp() -> list:
    """
    Lê TODOS os documentos de `whatsapp_conversas` (1 por telefone) e
    devolve uma lista resumida, mais recente primeiro:
        { telefone, ultima_msg_texto, ultima_msg_direcao, ultima_msg_em }

    Sem cache de propósito (mesmo raciocínio já usado em
    `listar_mensagens_whatsapp`, em common.py): esta tela é "ao vivo", e
    o volume de conversas tende a ser pequeno (1 doc por cliente que já
    escreveu), então uma leitura direta a cada abertura da tela é
    aceitável. Se o volume crescer muito, dá pra aplicar um
    `@st.cache_data(ttl=8)` depois, do mesmo jeito que outras listagens
    do sistema já fazem.
    """
    docs = get_db().collection(WHATSAPP_COLECAO).stream()
    out = []
    for d in docs:
        data = d.to_dict() or {}
        msgs = data.get("mensagens", [])
        if not msgs:
            continue
        ultima = max(msgs, key=lambda m: m.get("criado_em", ""))
        out.append({
            "telefone": data.get("telefone", d.id),
            "ultima_msg_texto": ultima.get("texto", ""),
            "ultima_msg_direcao": ultima.get("direcao", "in"),
            "ultima_msg_em": ultima.get("criado_em", data.get("atualizado_em", "")),
        })
    return sorted(out, key=lambda c: c.get("ultima_msg_em", ""), reverse=True)


def _minutos_desde(timestamp_str: str):
    """[Grupo 1 · item 5] Minutos desde um timestamp no formato de
    `agora_brt()` ("%Y-%m-%d %H:%M:%S"), ou None se não der pra converter.
    Usado só para CALCULAR a cor da conversa (vermelho/laranja/azul) — não
    lê nem grava nada novo no banco."""
    if not timestamp_str:
        return None
    try:
        dt = datetime.strptime(str(timestamp_str)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BRT)
        return (datetime.now(BRT) - dt).total_seconds() / 60.0
    except Exception:
        return None


def _estado_conversa(ultima_direcao: str, ultima_em: str) -> str:
    """
    [Grupo 1 · item 5] Reproduz a mesma régua de cor já usada na Concierge,
    calculada em cima do que já existe (direção + horário da última
    mensagem) — nenhum campo novo:

        'azul'    → cliente falou por último, há MENOS de 10 min (mensagem nova)
        'vermelho'→ cliente falou por último, há MAIS de 10 min (esperando)
        'laranja' → nós falamos por último, e o cliente não respondeu
                    depois de MAIS de 10 min
        'ok'      → nós falamos por último, dentro dos 10 min (nada a fazer)
    """
    minutos = _minutos_desde(ultima_em)
    if ultima_direcao == "in":
        return "azul" if (minutos is not None and minutos <= 10) else "vermelho"
    else:
        return "laranja" if (minutos is not None and minutos > 10) else "ok"


def _categoria_ver(ultima_direcao: str, tickets_vinculados: list) -> str:
    """
    [v20 — barra "Ver"] Classifica a conversa numa das 4 categorias da
    Concierge, aproximadas em cima do que este sistema JÁ tem (sem campo
    novo): direção da última mensagem + status dos tickets vinculados.

        'aguardando_equipe'   → cliente falou por último, ninguém respondeu
                                 ainda (é a categoria mais urgente).
        'aguardando_cliente'  → nós falamos por último, esperando ele
                                 responder.
        'tratamento_interno'  → existe ticket vinculado ainda ABERTO
                                 (aberto/em_andamento/aguardando), tratado
                                 por dentro do portal, independente de quem
                                 falou por último no WhatsApp.
        'concluido'           → todo ticket vinculado já está
                                 resolvido/finalizado/cancelado, ou não há
                                 nenhum ticket (conversa avulsa encerrada).

    ⚠️ Isto é uma APROXIMAÇÃO da definição da Concierge, não uma cópia
    exata — a Concierge tem um motor de fila próprio que este sistema não
    replica. Ajustar os critérios abaixo é rápido se a definição real for
    diferente na prática.
    """
    tem_aberto = any(t.get("status") in STATUS_ABERTOS for t in tickets_vinculados)
    if tem_aberto:
        return "tratamento_interno"
    if tickets_vinculados and not tem_aberto:
        return "concluido"
    # Sem ticket nenhum vinculado — classifica só pela conversa em si.
    return "aguardando_equipe" if ultima_direcao == "in" else "aguardando_cliente"


# ═══════════════════════════════════════════════════════════════════
# [v20] Widget de Status — Online / Offline / Pausa (com motivo)
# ═══════════════════════════════════════════════════════════════════
_MOTIVOS_PAUSA = [
    ("Almoço", 60), ("Pausa 10", 10), ("Treinamento", None),
    ("Banheiro", None), ("Reunião", None), ("Particular", None),
]


def _minutos_desde_utc(dt):
    """Como `_minutos_desde`, mas para datetime timezone-aware (UTC) vindo
    direto do Firestore — usado só pelo widget de Status."""
    if not dt:
        return None
    try:
        from datetime import datetime as _dt, timezone as _tz
        return (_dt.now(_tz.utc) - dt).total_seconds() / 60.0
    except Exception:
        return None


def _render_widget_status(user):
    """
    Online / Offline / Pausa (com motivo), no topo da tela — mesmo padrão
    visual da Concierge. "Offline" aqui não é um clique: é o que acontece
    sozinho quando ninguém abre esta tela por mais de 60s (mesma regra que
    já existia em `listar_admins_online`). O clique em Pausa exige
    escolher um motivo da lista (com ou sem minutos sugeridos).
    """
    if not _PRESENCA_DISPONIVEL:
        return

    uname = user.get("usuario", "")
    nome = user.get("nome", "")
    atual = obter_status_presenca_adm(uname)

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("🟢 Online", use_container_width=True,
                     type="primary" if atual["status"] == "online" else "secondary"):
            atualizar_status_presenca_adm(uname, nome, "online")
            st.rerun()
    with c2:
        if atual["status"] == "pausa":
            minutos_em_pausa = _minutos_desde_utc(atual.get("pausa_desde"))
            txt_tempo = f" há {int(minutos_em_pausa)}min" if minutos_em_pausa is not None else ""
            st.button(f"🟠 Pausa: {atual.get('motivo_pausa','')}{txt_tempo}",
                     use_container_width=True, type="primary", disabled=True)
        else:
            with st.popover("🟠 Pausa", use_container_width=True):
                for motivo, minutos_sugeridos in _MOTIVOS_PAUSA:
                    label = f"{motivo}" + (f" · {minutos_sugeridos}min" if minutos_sugeridos else "")
                    if st.button(label, key=f"wa_pausa_{motivo}", use_container_width=True):
                        atualizar_status_presenca_adm(uname, nome, "pausa", motivo)
                        st.rerun()
    with c3:
        st.caption("⚪ Offline é automático — acontece sozinho se você ficar "
                   "mais de 1 minuto sem abrir esta tela.")


# ═══════════════════════════════════════════════════════════════════
# [Ficha do Cliente — v19] Card no formato da Concierge (Nome, E-mail,
# Telefone, Canal, Identificado, Código, Pedidos, Outros atendimentos).
#
# ⚠️ HONESTIDADE COM O DADO: este sistema NÃO tem integração com o ERP
# ainda. Por isso, os campos que dependeriam disso (E-mail, Pedidos deste
# cliente, Acesso ao Portal) aparecem marcados como "não conectado" em vez
# de mostrar informação fingida ou um zero enganoso. O que É real:
#   - Nome/Código: vêm de um ticket já existente vinculado a este telefone.
#   - Identificado: SIM se algum ticket já vinculou um cliente_codigo a
#     este telefone; NÃO (contato avulso) se nenhum vinculou ainda.
#   - Outros atendimentos: contagem real, de `_tickets_do_telefone`.
# ═══════════════════════════════════════════════════════════════════
def _bloco_ficha_cliente_completa(telefone: str, tickets_vinculados: list):
    st.markdown('<div class="tk-deck-card-title">📇 Ficha do Cliente</div>', unsafe_allow_html=True)

    identificado = bool(tickets_vinculados and any(t.get("cliente_codigo") for t in tickets_vinculados))
    nome = next((t.get("cliente_nome") for t in tickets_vinculados if t.get("cliente_nome")), "") or "—"
    codigo = next((t.get("cliente_codigo") for t in tickets_vinculados if t.get("cliente_codigo")), "") or "—"

    linhas = [
        ("Nome", nome if identificado else "—"),
        ("E-mail", "🚧 não conectado (requer integração ERP)"),
        ("Telefone", telefone),
        ("Canal", "whatsapp"),
        ("Identificado", "✅ Sim (cadastro interno)" if identificado else "❌ Não — contato avulso"),
        ("Código", codigo if identificado else "—"),
    ]
    for label, valor in linhas:
        st.markdown(_html(f"""
        <div style="display:flex;justify-content:space-between;padding:4px 0;
                    border-bottom:1px solid #f3f3f3;font-size:0.82rem;">
            <span style="color:#64778d;">{esc(label)}</span>
            <span style="color:#2c3e50;font-weight:600;">{esc(valor)}</span>
        </div>"""), unsafe_allow_html=True)

    st.markdown(_html("""
    <div style="background:#FBF3D9;border:1px solid #D4A12C;border-radius:8px;
                padding:8px 12px;margin-top:10px;font-size:0.76rem;color:#7A5C12;">
        🚧 <b>Pedidos deste cliente</b> e <b>Acesso ao Portal</b> ainda não
        aparecem aqui — dependem de integração com o ERP, que este sistema
        ainda não tem. Assim que a integração existir, entram nesta ficha
        sem precisar mudar o resto da tela.
    </div>"""), unsafe_allow_html=True)

    st.markdown(_html(f"""
    <div style="font-size:0.82rem;color:#2c3e50;margin-top:8px;">
        🗂 <b>Outros atendimentos:</b> {len(tickets_vinculados)}
    </div>"""), unsafe_allow_html=True)


def _tickets_do_telefone(telefone_norm: str, todos_geral: list) -> list:
    """Tickets (já achatados, de `listar_tickets()`) cujo `cliente_telefone`
    normalizado bate com este telefone — cruzamento em memória, sem
    consulta nova ao Firestore (recebe `todos_geral` do orquestrador)."""
    out = []
    for t in todos_geral:
        tel_t = normalizar_telefone(t.get("cliente_telefone", ""))
        if tel_t and tel_t == telefone_norm:
            out.append(t)
    return out


# ═══════════════════════════════════════════════════════════════════
# Formulário "Abrir ticket para este cliente" — mesma lógica-núcleo de
# tickets/novo.py (Departamento + Motivo Pai + abrir_solicitacao_cliente),
# só que embutido aqui, ao lado da conversa, com o telefone já preenchido
# e SEM navegar pra outra tela (a conversa continua visível do lado).
# ═══════════════════════════════════════════════════════════════════
def _bloco_abrir_ticket_da_conversa(telefone: str, user):
    st.markdown('<div class="tk-deck-card-title">🎫 Abrir ticket para este cliente</div>',
                unsafe_allow_html=True)

    deps = listar_departamentos()
    dep_nomes = [d["nome"] for d in deps]
    if not dep_nomes:
        st.caption("⚠️ Nenhum departamento cadastrado ainda.")
        return

    dep_sel = st.selectbox("Departamento *", dep_nomes, key=f"wa_dep_{telefone}")
    pais_dep = motivos_pai_do_departamento(dep_sel)
    motivo_obj = None
    sla_dias = 5
    if pais_dep:
        pai_nomes = [m["nome"] for m in pais_dep]
        pai_sel = st.selectbox("Motivo *", pai_nomes, key=f"wa_motivo_{telefone}")
        motivo_obj = next(m for m in pais_dep if m["nome"] == pai_sel)
        sla_dias = int(motivo_obj.get("sla_dias", 5))
    else:
        st.caption("Este departamento ainda não tem Motivos cadastrados — será usado SLA padrão de 5 dias.")

    # ── PREMISSA 1: busca por código do cliente, sem tentar casar
    # automaticamente pelo telefone — igual tickets/novo.py já faz.
    # Se preferir casamento automático por telefone, é aqui que muda. ──
    cli_codigo = st.text_input("Código do cliente *", placeholder="Ex: 10234",
                                key=f"wa_cli_codigo_{telefone}")
    cli_nome = st.text_input("Nome do cliente *", placeholder="Ex: João da Silva",
                              key=f"wa_cli_nome_{telefone}")

    cod_norm = normalizar_codigo_cliente(cli_codigo)
    tickets_cliente = tickets_do_cliente(cod_norm) if cod_norm else []
    if tickets_cliente:
        abertos_cli = sum(1 for x in tickets_cliente if x.get("status") in STATUS_ABERTOS)
        st.caption(f"🗂 Este código já tem {len(tickets_cliente)} solicitação(ões) anterior(es)"
                   f"{f' ({abertos_cli} em aberto)' if abertos_cli else ''} — "
                   f"a nova entra no MESMO histórico deste cliente.")
    elif cod_norm:
        # PREMISSA 2: cliente novo (sem histórico) → formulário segue
        # normalmente, mesmo comportamento de "Regra 0" da Concierge.
        st.caption("✅ Nenhuma solicitação anterior — será a primeira dele.")

    with st.form(f"form_wa_ticket_{telefone}", clear_on_submit=True):
        assunto = st.text_input("Assunto *", placeholder="Descreva o problema")
        descricao = st.text_area("Descrição *", height=90)
        enviar = st.form_submit_button("🚀 Abrir Chamado", type="primary", use_container_width=True)

        if enviar:
            if not assunto.strip() or not descricao.strip():
                st.error("Preencha Assunto e Descrição.")
            elif not cod_norm or not cli_nome.strip():
                st.error("Informe o Código e o Nome do cliente.")
            else:
                ok, msg_erro, novo_id = abrir_solicitacao_cliente({
                    "assunto": assunto.strip(), "descricao": descricao.strip(),
                    "departamento": dep_sel, "categoria": dep_sel,
                    "motivo_pai": motivo_obj["nome"] if motivo_obj else "",
                    "motivo_pai_id": motivo_obj["id"] if motivo_obj else "",
                    "sla1_prazo_dias": sla_dias,
                    "prioridade": (motivo_obj.get("prioridade", "normal") if motivo_obj else "normal"),
                    "atendentes": [],
                    "cliente_codigo": cod_norm,
                    "cliente_nome": cli_nome.strip(),
                    "cliente_telefone": telefone,  # já vem preenchido da conversa
                    "solicitante_nome": user.get("nome", ""),
                    "aberto_por": user.get("usuario", ""),
                })
                if not ok:
                    st.error(f"🚫 {msg_erro}")
                else:
                    st.success(f"✅ Chamado **#{novo_id[:8]}** aberto! A conversa continua aberta "
                               f"aqui do lado — nada foi fechado.")
                    time.sleep(1.2)
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════
# Painel da conversa em foco (direita) — histórico de mensagens +
# campo de envio + ficha/histórico do cliente + abrir ticket, tudo
# visível ao mesmo tempo (não em pop-up, não em aba separada).
# ═══════════════════════════════════════════════════════════════════
def _render_conversa_foco(telefone: str, user, papel, todos_geral: list):
    tel_norm = normalizar_telefone(telefone)
    tickets_vinculados = _tickets_do_telefone(tel_norm, todos_geral)

    st.markdown(_html(f"""
    <div class="tk-jobbar">
        <h3 style="margin:0 0 4px;color:#2c3e50;">📱 {esc(telefone)}</h3>
        <div style="font-size:0.8rem;color:#64778d;">
            {"🎫 " + str(len(tickets_vinculados)) + " ticket(s) já vinculado(s) a este telefone"
             if tickets_vinculados else "Nenhum ticket vinculado a este telefone ainda — contato avulso."}
        </div>
    </div>"""), unsafe_allow_html=True)

    col_conversa, col_ficha = st.columns([1.1, 1])

    # ── Coluna esquerda: a conversa de WhatsApp em si (mesmo componente
    # visual de bolha que já existe em tickets/detalhe.py::_bloco_whatsapp,
    # reescrito aqui porque esta tela não depende de haver um ticket). ──
    with col_conversa:
        st.markdown('<div class="tk-deck-title">💬 Conversa</div>', unsafe_allow_html=True)

        if not whatsapp_configurado():
            st.info("WhatsApp ainda não configurado (faltam as chaves da Twilio em Secrets).")
            return

        with st.container(key=f"tk_deck_card_wa_msgs_{telefone}"):
            mensagens = listar_mensagens_whatsapp(telefone)
            with st.container(height=420):
                if not mensagens:
                    st.caption("Nenhuma mensagem ainda.")
                else:
                    for m in mensagens[-60:]:
                        saida = m.get("direcao") == "out"
                        alinha = "right" if saida else "left"
                        bg = "#DCF8C6" if saida else "#ffffff"
                        rodape = esc(str(m.get("criado_em",""))[11:16])
                        if saida and m.get("autor"):
                            rodape += f" · {esc(m['autor'])}"
                        st.markdown(_html(f"""
                        <div style="text-align:{alinha};margin:4px 0;">
                            <div style="display:inline-block;background:{bg};border:1px solid #e2e8f0;
                                        padding:7px 11px;border-radius:9px;max-width:82%;text-align:left;
                                        font-size:0.85rem;">
                                {esc(m.get("texto",""))}
                                <div style="font-size:0.64rem;color:#8a8a8a;margin-top:3px;text-align:right;">
                                    {rodape}
                                </div>
                            </div>
                        </div>"""), unsafe_allow_html=True)

            minutos = minutos_desde_ultima_mensagem_cliente(telefone)
            dentro_da_janela = minutos is not None and minutos < (24 * 60)
            if not dentro_da_janela:
                st.caption("⚠️ Fora da janela de 24h da última mensagem do cliente — só um "
                           "template aprovado pelo Meta funciona agora.")

            with st.form(f"form_wa_msg_{telefone}", clear_on_submit=True):
                texto_novo = st.text_area("Mensagem", height=68, key=f"wa_txt_{telefone}",
                                          placeholder="Escrever mensagem de WhatsApp...",
                                          label_visibility="collapsed")
                enviar_click = st.form_submit_button(
                    "📤 Enviar", type="primary", use_container_width=True,
                    disabled=not dentro_da_janela,
                )
            if enviar_click:
                if texto_novo.strip():
                    ok, msg = enviar_whatsapp(telefone, texto_novo.strip(), user.get("nome",""))
                    (st.success if ok else st.error)(msg)
                    if ok:
                        time.sleep(.4); st.rerun()
                else:
                    st.warning("Escreva algo antes de enviar.")

    # ── Coluna direita: ficha/histórico do cliente (se algum ticket já
    # vincula este telefone a um cliente) + abrir ticket. O histórico
    # fica VISÍVEL ao lado da conversa o tempo todo — nunca escondido
    # atrás de navegação, exatamente como pedido. ──
    with col_ficha:
        st.markdown('<div class="tk-deck-title">🗂️ Ficha &amp; Ticket</div>', unsafe_allow_html=True)

        # [v19] Ficha do Cliente sempre aparece — identificado ou avulso.
        with st.container(key=f"tk_deck_card_wa_ficha_{telefone}"):
            _bloco_ficha_cliente_completa(telefone, tickets_vinculados)

        if tickets_vinculados:
            with st.container(key=f"tk_deck_card_wa_hist_{telefone}"):
                st.markdown('<div class="tk-deck-card-title">📜 Histórico deste cliente</div>',
                            unsafe_allow_html=True)
                _render_bloco_historico_cliente(tickets_vinculados)

        with st.container(key=f"tk_deck_card_wa_abrir_{telefone}"):
            _bloco_abrir_ticket_da_conversa(telefone, user)


# ═══════════════════════════════════════════════════════════════════
# Tela principal — lista de conversas (esquerda) + conversa em foco
# ═══════════════════════════════════════════════════════════════════
def _render_whatsapp_atendimento(user, papel, todos_geral: list):
    st.markdown("### 💬 WhatsApp Atendimento")

    # Marca presença de quem abriu esta tela — mesma fonte que o chat
    # motorista↔ADM já usa (ver changelog [18] no topo do arquivo).
    if _PRESENCA_DISPONIVEL:
        try:
            marcar_presenca_adm(user.get("usuario",""), user.get("nome",""))
        except Exception:
            pass

    # [v20] Widget de Status — Online / Offline / Pausa (com motivo).
    _render_widget_status(user)
    st.markdown('<div style="border-top:1px solid #e2e8f0;margin:8px 0 14px;"></div>',
                unsafe_allow_html=True)

    busca = st.text_input("🔎 Buscar por telefone", key="wa_busca",
                          placeholder="Digite parte do número...")

    conversas = _carregar_todas_conversas_whatsapp()
    if busca.strip():
        termo = busca.strip()
        conversas = [c for c in conversas if termo in c["telefone"]]

    # [v20] Pré-calcula tickets vinculados + categoria "Ver" de cada
    # conversa UMA vez (evita repetir a mesma consulta em memória duas
    # vezes: uma pro filtro, outra pro card da lista).
    info_por_conversa = {}
    for c in conversas:
        tel_norm = normalizar_telefone(c["telefone"])
        tks = _tickets_do_telefone(tel_norm, todos_geral)
        info_por_conversa[c["telefone"]] = {
            "tickets": tks,
            "categoria": _categoria_ver(c["ultima_msg_direcao"], tks),
        }

    contagem = {"aguardando_equipe": 0, "aguardando_cliente": 0, "tratamento_interno": 0, "concluido": 0}
    for info in info_por_conversa.values():
        contagem[info["categoria"]] += 1

    # [v20] Barra "Ver" — mesmas 4 categorias + "Todos", filtrando a lista
    # abaixo. Guarda a escolha em session_state pra sobreviver ao rerun.
    if "wa_ver_filtro" not in st.session_state:
        st.session_state.wa_ver_filtro = "todos"

    st.markdown("**Ver**")
    vc1, vc2, vc3, vc4, vc5 = st.columns(5)
    botoes_ver = [
        (vc1, "aguardando_equipe", f"Aguardando equipe {contagem['aguardando_equipe']}"),
        (vc2, "aguardando_cliente", f"Aguardando cliente {contagem['aguardando_cliente']}"),
        (vc3, "tratamento_interno", f"Em tratamento interno {contagem['tratamento_interno']}"),
        (vc4, "concluido", f"Concluído {contagem['concluido']}"),
        (vc5, "todos", f"Todos {len(conversas)}"),
    ]
    for col, valor, label in botoes_ver:
        with col:
            if st.button(label, key=f"wa_ver_{valor}", use_container_width=True,
                         type="primary" if st.session_state.wa_ver_filtro == valor else "secondary"):
                st.session_state.wa_ver_filtro = valor
                st.rerun()

    filtro_atual = st.session_state.wa_ver_filtro
    if filtro_atual != "todos":
        conversas = [c for c in conversas if info_por_conversa[c["telefone"]]["categoria"] == filtro_atual]

    col_lista, col_foco = st.columns([1, 2.2])

    with col_lista:
        st.markdown(f"**{len(conversas)} conversa(s)**")

        if _PRESENCA_DISPONIVEL:
            try:
                online = listar_admins_online()
                if online:
                    partes = []
                    for o in online:
                        if o.get("status") == "pausa":
                            partes.append(f"{o['nome']} (🟠 {o.get('motivo_pausa','Pausa')})")
                        else:
                            partes.append(o["nome"])
                    st.markdown(_html(
                        f'<div style="font-size:0.75rem;color:#16A34A;margin-bottom:8px;">'
                        f'<span class="wa-online-dot"></span>Online agora: {esc(", ".join(partes))}</div>'
                    ), unsafe_allow_html=True)
            except Exception:
                pass

        if not conversas:
            st.caption("Nenhuma conversa encontrada.")

        for c in conversas:
            tel = c["telefone"]
            estado = _estado_conversa(c["ultima_msg_direcao"], c["ultima_msg_em"])
            tem_ticket = bool(info_por_conversa[tel]["tickets"])

            # [Grupo 1 · item 5] chave da linha carrega o estado calculado
            # (vermelho/laranja/azul) pro CSS já definido em mod_tickets.py
            # pintar a borda certa — reaproveita as MESMAS classes CSS que
            # já existiam (wa_row_aguardando_ = vermelho/laranja piscando,
            # wa_row_semticket_ = azul), só a condição que decide qual usar
            # ficou mais precisa (calculada por tempo, não só por direção).
            if estado in ("vermelho", "laranja"):
                key_row = f"wa_row_aguardando_{tel}"
            elif estado == "azul" or not tem_ticket:
                key_row = f"wa_row_semticket_{tel}"
            else:
                key_row = f"wa_row_{tel}"

            icone = {"vermelho": "🔴 ", "laranja": "🟠 ", "azul": "🔵 ", "ok": ""}[estado]
            preview = (c["ultima_msg_texto"] or "")[:44]
            hora = str(c["ultima_msg_em"])[11:16] if c["ultima_msg_em"] else ""
            rotulo = f"{icone}{tel}\n{preview} · {hora}"

            with st.container(key=key_row):
                if st.button(rotulo, key=f"wa_btn_{tel}", use_container_width=True):
                    st.session_state.tk_whats_foco = tel
                    st.rerun()

    with col_foco:
        foco = st.session_state.get("tk_whats_foco")
        if not foco:
            st.info("Selecione uma conversa à esquerda.")
        else:
            _render_conversa_foco(foco, user, papel, todos_geral)
