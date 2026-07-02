import streamlit as st
import pandas as pd
import time
from datetime import datetime, date, timezone, timedelta

import plotly.express as px

from database import (
    listar_lembretes_pessoais, criar_lembrete_pessoal_db,
    atualizar_lembrete_pessoal_db, deletar_lembrete_pessoal_db,
    adiar_lembrete_pessoal_db,
    listar_raci_projetos, criar_raci_projeto_db,
    atualizar_raci_projeto_db, deletar_raci_projeto_db,
    salvar_arquivo_raci_db, baixar_arquivo_raci_db, deletar_arquivo_raci_db,
    criar_registro_diario_db, listar_diario_bordo_db, deletar_registro_diario_db,
)

# Import isolado: se o seu database.py ainda não tiver as 3 funções novas
# do cronômetro (iniciar/finalizar/obter atividade em andamento), o Meu Dia
# continua funcionando normalmente — só o cronômetro fica indisponível com
# um aviso, em vez de derrubar a tela inteira.
try:
    from database import (
        iniciar_atividade_diario_db, finalizar_atividade_diario_db,
        obter_atividade_em_andamento_db,
    )
    _CRONOMETRO_OK = True
except Exception:
    _CRONOMETRO_OK = False
    def iniciar_atividade_diario_db(*a, **k):
        raise RuntimeError("Cronômetro indisponível — faltam funções novas no database.py.")
    def finalizar_atividade_diario_db(*a, **k):
        return False, "Cronômetro indisponível — faltam funções novas no database.py."
    def obter_atividade_em_andamento_db(*a, **k):
        return None

BRT = timezone(timedelta(hours=-3))

PAPEIS_RACI = ["", "R", "A", "C", "I"]
PRIORIDADES = ["Alto", "Médio", "Baixo"]
STATUS_ATIV = ["Não Iniciado", "Em Andamento", "Concluído", "Atrasado"]
LEGENDA_RACI = (
    "**R**=Responsável (executa) · **A**=Aprovador (decide/autoriza) · "
    "**C**=Consultado (opina antes) · **I**=Informado (avisado depois)"
)
TAG_PRIORIDADE = {"Alto": "tr", "Médio": "tg", "Baixo": "tn"}
TAG_STATUS = {"Não Iniciado": "tb", "Em Andamento": "tg", "Concluído": "tn", "Atrasado": "tr"}

_CSS_HOME = """
<style>
.home-item { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
    padding:10px 14px; margin-bottom:6px; border-left:4px solid #C9A84C; }
.home-item.atrasado { border-left-color:#e74c3c; }
.home-item.hoje { border-left-color:#C9A84C; }
.home-item.futuro { border-left-color:#95a5a6; }
.home-origem { font-size:0.72rem; color:#64778d; }
.home-motivo { font-size:0.75rem; color:#a93226; background:rgba(231,76,60,.08);
    border-radius:6px; padding:4px 8px; margin-top:4px; display:inline-block; }
.home-execucao { font-size:0.75rem; color:#7a5f1a; background:rgba(201,168,76,.12);
    border-radius:6px; padding:4px 8px; margin-top:4px; display:inline-block; }
.ponto-regua { width: 30px; height: 30px; border-radius: 50%; background: #e2e8f0;
    display: flex; align-items: center; justify-content: center; font-weight: bold;
    color: #64778d; margin: 0 auto; border: 2px solid #cbd5e1; font-size: 12px; }
.ponto-check { background: #27ae60; color: white; border-color: #27ae60; }
.ponto-atual { background: #C9A84C; color: white; border-color: #C9A84C;
    box-shadow: 0 0 8px rgba(201,168,76,0.5); }
.label-regua { font-size: 9px; text-align: center; font-weight: bold; margin-top: 5px;
    color: #475569; height: 28px; line-height: 1.1; }
</style>
"""


# ─── Helpers ──────────────────────────────────────────────────────
def _html(s: str) -> str:
    return "\n".join(linha.lstrip() for linha in s.splitlines())


def _parse_data(s):
    if not s:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except Exception:
            continue
    return None


def _formatar_duracao(segundos):
    if not segundos:
        return "—"
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _salvar(projeto):
    atualizar_raci_projeto_db(
        projeto["id"],
        pessoas=projeto.get("pessoas", []),
        etapas=projeto.get("etapas", []),
        lembretes=projeto.get("lembretes", []),
        pastas_virtuais=projeto.get("pastas_virtuais", {}),
        etapa_atual=projeto.get("etapa_atual", 0),
    )


# ─── Cronômetro (compartilhado entre "Meu Dia" e "Diário de Bordo") ──
# Atualização parcial via st.fragment (nativo do Streamlit) em vez de
# streamlit-autorefresh: esse componente externo tem um bug conhecido de
# deixar o timer JS "vivo" no navegador mesmo depois de trocar de aba,
# travando OUTRAS telas do sistema sem relação nenhuma com o cronômetro.
_FRAGMENT_DECORATOR = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
_TEM_FRAGMENT = _FRAGMENT_DECORATOR is not None


def _widget_cronometro_corpo(uname, key_prefix=""):
    """
    Mostra a atividade em andamento com cronômetro ao vivo + botão Finalizar,
    ou o campo para iniciar uma nova, se não houver nenhuma rodando agora.
    Só existe UMA atividade em andamento por vez (regra simples: você só
    trabalha em uma coisa de cada vez, o cronômetro reflete isso).
    """
    if not _CRONOMETRO_OK:
        st.warning("⚠️ Cronômetro indisponível no momento — peça para atualizar o database.py.")
        return

    atual = obter_atividade_em_andamento_db(uname)

    if atual:
        inicio = atual.get("inicio")
        try:
            decorrido = (datetime.now(BRT) - inicio).total_seconds()
        except Exception:
            decorrido = 0
        h, resto = divmod(max(int(decorrido), 0), 3600)
        m, s = divmod(resto, 60)
        tempo_fmt = f"{h:02d}:{m:02d}:{s:02d}"

        try:
            hora_inicio = inicio.astimezone(BRT).strftime("%H:%M")
        except Exception:
            hora_inicio = "—"

        origem_txt = " 🔔 (a partir de um lembrete)" if atual.get("origem") == "lembrete" else ""

        st.markdown(_html(f"""
        <div class="home-item hoje" style="display:flex;justify-content:space-between;
                    align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
                <b>⏱️ Em andamento:</b> {atual.get('atividade','')}{origem_txt}<br>
                <span class="home-origem">Iniciado às {hora_inicio}</span>
            </div>
            <div style="font-size:1.5rem;font-weight:800;color:#C9A84C;">{tempo_fmt}</div>
        </div>
        """), unsafe_allow_html=True)

        if st.button("🛑 Finalizar atividade", type="primary", use_container_width=True,
                     key=f"{key_prefix}finalizar_cron"):
            ok, msg = finalizar_atividade_diario_db(atual["id"])
            if ok and atual.get("origem") == "lembrete" and atual.get("origem_ref"):
                try:
                    atualizar_lembrete_pessoal_db(atual["origem_ref"], status="Executado")
                except Exception:
                    pass
            (st.success if ok else st.error)(msg)
            time.sleep(.4)
            st.rerun()

        if not _TEM_FRAGMENT:
            st.caption(
                "⚠️ Seu Streamlit é muito antigo para o relógio atualizar sozinho. "
                "Atualize `streamlit>=1.35.0` no requirements.txt, ou clique abaixo."
            )
            if st.button("🔄 Atualizar relógio", key=f"{key_prefix}refresh_cron"):
                st.rerun()

    else:
        with st.form(f"{key_prefix}form_iniciar_cron", clear_on_submit=True):
            col_txt, col_btn = st.columns([5, 1])
            atividade_agora = col_txt.text_input(
                "Atividade atual", label_visibility="collapsed",
                placeholder="Ex: Tratando ticket #199791 da loja Campinas...",
                key=f"{key_prefix}cron_txt",
            )
            iniciar = col_btn.form_submit_button(
                "▶️ Iniciar", type="primary", use_container_width=True
            )
            if iniciar:
                if atividade_agora.strip():
                    try:
                        iniciar_atividade_diario_db(uname, atividade_agora.strip(), origem="diario")
                        st.success("Cronômetro iniciado!")
                        time.sleep(.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Não foi possível iniciar. Detalhe técnico: {e}")
                else:
                    st.warning("Descreva o que você está fazendo antes de iniciar.")


# Duas versões do mesmo cronômetro:
# - "vivo" (usado no Meu Dia): relógio atualiza sozinho a cada 1s via
#   st.fragment — sem o bug de "timer fantasma" do streamlit-autorefresh.
# - "estático" (usado no Diário de Bordo): não fica se auto-atualizando,
#   evita rodar dois relógios/fragmentos independentes ao mesmo tempo.
if _TEM_FRAGMENT:
    _widget_cronometro_vivo = _FRAGMENT_DECORATOR(run_every=1)(_widget_cronometro_corpo)
else:
    _widget_cronometro_vivo = _widget_cronometro_corpo


def _widget_cronometro(uname, key_prefix="", autorefresh=True):
    """Mantido com essa assinatura por compatibilidade com o resto do arquivo."""
    if autorefresh:
        _widget_cronometro_vivo(uname, key_prefix=key_prefix)
    else:
        _widget_cronometro_corpo(uname, key_prefix=key_prefix)


def _linhas_produtividade(uname, data_ini, data_fim, lembretes):
    """
    Junta num só lugar:
    - Registros do Diário de Bordo finalizados (cronometrados), sejam eles
      iniciados diretamente ou a partir de um lembrete.
    - Lembretes marcados como Executado que NUNCA tiveram cronômetro
      (pra não sumir do relatório, só aparecem sem duração).
    """
    linhas = []
    refs_com_timer = set()

    diario_periodo = listar_diario_bordo_db(usuario=uname, data_ini=data_ini, data_fim=data_fim)
    for r in diario_periodo:
        if r.get("status") != "finalizado":
            continue
        origem = "🔔 Lembrete" if r.get("origem") == "lembrete" else "📔 Diário"
        if r.get("origem") == "lembrete" and r.get("origem_ref"):
            refs_com_timer.add(r.get("origem_ref"))
        linhas.append({
            "Data": r.get("data", ""),
            "Atividade": r.get("atividade", ""),
            "Origem": origem,
            "Duração": _formatar_duracao(r.get("duracao_segundos")),
            "_segundos": r.get("duracao_segundos") or 0,
        })

    for l in lembretes:
        if l.get("status") != "Executado":
            continue
        if l.get("id") in refs_com_timer:
            continue  # já contabilizado via o registro cronometrado do diário
        dt_l = _parse_data(l.get("data_hora", ""))
        if dt_l is None or not (data_ini <= dt_l.date() <= data_fim):
            continue
        linhas.append({
            "Data": dt_l.strftime("%d/%m/%Y"),
            "Atividade": l.get("texto", ""),
            "Origem": "🔔 Lembrete",
            "Duração": "— (sem cronômetro)",
            "_segundos": 0,
        })

    return linhas


# ─── Função principal ─────────────────────────────────────────────
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

    tabs = st.tabs([
        "📅 Meu Dia", "📔 Diário de Bordo",
        "📊 Meus Projetos (RACI)", "🔔 Lembretes & Produtividade",
    ])

    with tabs[0]:
        _render_meu_dia(uname, lembretes, raci_projetos)

    with tabs[1]:
        _render_diario_bordo(uname)

    with tabs[2]:
        _render_aba_raci(raci_projetos)

    with tabs[3]:
        _render_todos_lembretes(uname, lembretes, raci_projetos)


# ════════════════════════════════════════════════════════════════
# ABA 1 — MEU DIA
# ════════════════════════════════════════════════════════════════
def _render_meu_dia(uname, lembretes, raci_projetos):
    hoje = date.today()

    # ── Cronômetro: o que estou fazendo agora ──────────────────────
    st.markdown("##### 📝 O que você está fazendo agora?")
    _widget_cronometro(uname, key_prefix="md_", autorefresh=True)

    # Mostra os últimos registros de hoje, para conferência imediata
    registros_hoje = listar_diario_bordo_db(usuario=uname, data_ini=hoje, data_fim=hoje)
    if registros_hoje:
        with st.expander(f"📔 Registros de hoje ({len(registros_hoje)})", expanded=False):
            for r in registros_hoje:
                dur = _formatar_duracao(r.get("duracao_segundos")) if r.get("status") == "finalizado" else "⏱️ em andamento"
                st.caption(f"⏱ {r.get('hora','')} — {r.get('atividade','')} · {dur}")

    st.divider()

    tem_ativa = _CRONOMETRO_OK and obter_atividade_em_andamento_db(uname) is not None

    itens = []
    for l in lembretes:
        status_atual = l.get("status", "Pendente")
        if status_atual not in ("Pendente", "Em Execução"):
            continue
        itens.append({
            "origem": "🗒️ Pessoal", "texto": l.get("texto", ""),
            "quando": l.get("data_hora", ""), "ref": l.get("id"),
            "historico": l.get("historico_adiamentos", []),
            "em_execucao": status_atual == "Em Execução",
        })

    for rp in raci_projetos:
        for et in rp.get("etapas", []):
            for at in et.get("atividades", []):
                if at.get("status") == "Concluído":
                    continue
                dp = at.get("data_prevista")
                if not dp:
                    continue
                papeis = at.get("papeis", {}) or {}
                if uname not in papeis or papeis.get(uname) != "R":
                    continue  # no "Meu Dia" só entra o que EU sou Responsável (R)
                itens.append({
                    "origem": f"📊 {rp.get('nome','')} / {et.get('nome','')}",
                    "texto": at.get("atividade", ""), "quando": dp, "ref": None,
                    "historico": [], "em_execucao": False,
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
        nomes_proj_v = [p["nome"] for p in raci_projetos]
        vinc_sel = st.selectbox(
            "Vincular a:", ["Pontual (fora de projetos)"] + nomes_proj_v,
            key="novo_lembrete_vinculo",
        )
        if st.button("Gravar Lembrete", type="primary", key="btn_novo_lembrete",
                     use_container_width=True):
            if txt_l.strip():
                try:
                    hora_txt = hl.strftime("%H:%M") if hl else "00:00"
                    vinculo_final = "" if vinc_sel == "Pontual (fora de projetos)" else vinc_sel
                    criar_lembrete_pessoal_db(
                        uname, txt_l.strip(), f"{dl.strftime('%d/%m/%Y')} {hora_txt}",
                        vinculo=vinculo_final,
                    )
                    st.success("Lembrete criado!")
                    time.sleep(.4)
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível gravar o lembrete. Detalhe técnico: {e}")
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
            em_exec = it.get("em_execucao", False)
            cb1, cb2, cb3, cb4 = st.columns([3, 1, 1, 1.2])
            with cb1:
                ultimo_motivo_html = ""
                if it["historico"]:
                    ultimo = it["historico"][-1]
                    ultimo_motivo_html = (
                        f'<div class="home-motivo">⏳ Adiado — motivo: '
                        f'{ultimo.get("motivo","")}</div>'
                    )
                execucao_html = '<div class="home-execucao">⏱️ Em execução</div>' if em_exec else ""
                st.markdown(
                    f'<div class="home-item {classe}">'
                    f'<b>{it["texto"]}</b><br>'
                    f'<span class="home-origem">{it["origem"]} · {it["quando"]}</span>'
                    f'{ultimo_motivo_html}{execucao_html}'
                    f'</div>', unsafe_allow_html=True)
            if it["ref"] is not None:
                with cb2:
                    if st.button("✅ Concluir", key=f"done_{it['ref']}", use_container_width=True):
                        atualizar_lembrete_pessoal_db(it["ref"], status="Executado")
                        st.rerun()
                with cb3:
                    with st.popover("⏳ Adiar", use_container_width=True):
                        st.caption("Use quando a tarefa depende de terceiros e ainda não pode ser concluída.")
                        nova_data = st.date_input(
                            "Nova data", value=date.today(), key=f"adiar_data_{it['ref']}"
                        )
                        nova_hora = st.time_input(
                            "Nova hora", value=None, key=f"adiar_hora_{it['ref']}"
                        )
                        motivo_atraso = st.text_area(
                            "Motivo do atraso *", key=f"adiar_motivo_{it['ref']}",
                            placeholder="Ex: Aguardando retorno do setor de Compras sobre liberação de estoque.",
                        )
                        if st.button("Confirmar adiamento", key=f"adiar_btn_{it['ref']}",
                                     type="primary", use_container_width=True):
                            if not motivo_atraso.strip():
                                st.warning("Informe o motivo do atraso para registrar.")
                            else:
                                hora_txt2 = nova_hora.strftime("%H:%M") if nova_hora else "00:00"
                                nova_dh = f"{nova_data.strftime('%d/%m/%Y')} {hora_txt2}"
                                ok, msg = adiar_lembrete_pessoal_db(
                                    it["ref"], nova_dh, motivo_atraso.strip()
                                )
                                (st.success if ok else st.error)(msg)
                                if ok:
                                    time.sleep(.4)
                                    st.rerun()
                with cb4:
                    if em_exec:
                        st.caption("⏱️ Rodando")
                    elif tem_ativa:
                        st.caption("🔒 Finalize a atual")
                    elif _CRONOMETRO_OK:
                        if st.button("▶️ Iniciar", key=f"iniciar_lemb_{it['ref']}",
                                     use_container_width=True):
                            try:
                                iniciar_atividade_diario_db(
                                    uname, it["texto"], origem="lembrete", origem_ref=it["ref"]
                                )
                                atualizar_lembrete_pessoal_db(it["ref"], status="Em Execução")
                                st.success("Cronômetro iniciado!")
                                time.sleep(.3)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Não foi possível iniciar: {e}")
    if not algum:
        st.info("🎉 Nenhuma tarefa pendente no momento.")


# ════════════════════════════════════════════════════════════════
# ABA 2 — DIÁRIO DE BORDO (histórico consultável do que foi feito)
# ════════════════════════════════════════════════════════════════
def _render_diario_bordo(uname):
    st.markdown("##### 📔 Diário de Bordo")
    st.caption(
        "Inicie o cronômetro com o que você está trabalhando agora. Ao finalizar, "
        "o tempo gasto fica gravado no histórico abaixo."
    )

    _widget_cronometro(uname, key_prefix="db_", autorefresh=False)

    st.divider()
    st.markdown("###### 🔎 Consultar histórico")

    hoje = date.today()
    fc1, fc2 = st.columns(2)
    data_ini = fc1.date_input("De", value=hoje - timedelta(days=7), key="diario_ini")
    data_fim = fc2.date_input("Até", value=hoje, key="diario_fim")

    if data_ini > data_fim:
        st.warning("A data inicial não pode ser depois da data final.")
        return

    registros = listar_diario_bordo_db(usuario=uname, data_ini=data_ini, data_fim=data_fim)

    if not registros:
        st.info("Nenhum registro no período selecionado.")
        return

    st.caption(f"{len(registros)} registro(s) encontrado(s).")

    from collections import defaultdict
    por_dia = defaultdict(list)
    for r in registros:
        por_dia[r.get("data", "—")].append(r)

    dias_ordenados = sorted(
        por_dia.keys(),
        key=lambda d: _parse_data(d) or datetime.min,
        reverse=True,
    )

    for dia in dias_ordenados:
        st.markdown(f"**🗓️ {dia}**")
        registros_dia = sorted(por_dia[dia], key=lambda x: x.get("hora", ""), reverse=True)
        for r in registros_dia:
            c1, c2 = st.columns([6, 1])
            with c1:
                if r.get("status") == "em_andamento":
                    dur_txt = "⏱️ em andamento"
                else:
                    dur_txt = _formatar_duracao(r.get("duracao_segundos"))
                origem_txt = " · 🔔 via lembrete" if r.get("origem") == "lembrete" else ""
                st.markdown(
                    f'<div class="home-item">⏱ <b>{r.get("hora","")}</b> — {r.get("atividade","")} '
                    f'<span class="home-origem">({dur_txt}{origem_txt})</span></div>',
                    unsafe_allow_html=True,
                )
            with c2:
                if st.button("🗑️", key=f"del_diario_{r.get('id')}", use_container_width=True):
                    deletar_registro_diario_db(r.get("id"))
                    st.rerun()
        st.write("")

    df_exp = pd.DataFrame([{
        "Data": r.get("data", ""), "Hora": r.get("hora", ""),
        "Atividade": r.get("atividade", ""),
        "Duração": _formatar_duracao(r.get("duracao_segundos")) if r.get("status") == "finalizado" else "em andamento",
        "Origem": "Lembrete" if r.get("origem") == "lembrete" else "Diário",
    } for r in registros])

    from io import BytesIO
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df_exp.to_excel(writer, index=False, sheet_name="Diario")
        ws = writer.sheets["Diario"]
        for i, col in enumerate(df_exp.columns):
            largura = max(df_exp[col].astype(str).map(len).max(), len(col)) + 2
            ws.set_column(i, i, largura)
    buf.seek(0)
    st.download_button(
        "📥 Baixar Diário do Período (.xlsx)", data=buf.getvalue(),
        file_name=f"Diario_Bordo_{uname}_{data_ini.strftime('%Y%m%d')}_a_{data_fim.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# ════════════════════════════════════════════════════════════════
# ABA 3 — MEUS PROJETOS (RACI), estilo PQI
# ════════════════════════════════════════════════════════════════
def _render_aba_raci(raci_projetos):
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
        return  # seguro: só sai desta função, não da renderizar_home

    projeto = next(p for p in raci_projetos if p["nome"] == escolha)
    projeto.setdefault("etapas", [])
    projeto.setdefault("lembretes", [])
    projeto.setdefault("pastas_virtuais", {})
    projeto.setdefault("etapa_atual", 0)

    with st.expander("⚙️ Configurações do Projeto"):
        novas_pessoas = st.text_area(
            "Pessoas do projeto (uma por linha)",
            value="\n".join(projeto.get("pessoas", [])),
            key=f"pessoas_{projeto['id']}", height=100,
        )
        cse1, cse2 = st.columns(2)
        if cse1.button("💾 Salvar Pessoas", use_container_width=True, key=f"svp_{projeto['id']}"):
            projeto["pessoas"] = [p.strip() for p in novas_pessoas.splitlines() if p.strip()]
            _salvar(projeto)
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
                    projeto["etapas"].append({
                        "id": datetime.now(BRT).timestamp(),
                        "nome": nome_etapa.strip(), "atividades": [], "notas": [],
                    })
                    _salvar(projeto)
                    st.rerun()
                else:
                    st.warning("Informe o nome da etapa.")

    if not projeto["etapas"]:
        st.info("Nenhuma etapa criada ainda. Use '➕ Nova Etapa' acima para começar.")
        return

    # ── Régua visual das etapas (estilo PQI) ──────────────────
    idx_atual = min(projeto.get("etapa_atual", 0), len(projeto["etapas"]) - 1)
    cols_r = st.columns(len(projeto["etapas"]))
    for i, et in enumerate(projeto["etapas"]):
        cl, txt = "ponto-regua", str(i + 1)
        if i < idx_atual:
            cl += " ponto-check"; txt = "✔"
        elif i == idx_atual:
            cl += " ponto-atual"
        cols_r[i].markdown(
            f'<div class="{cl}">{txt}</div><div class="label-regua">{et["nome"]}</div>',
            unsafe_allow_html=True)

    etapa = projeto["etapas"][idx_atual]
    etapa.setdefault("atividades", [])
    etapa.setdefault("notas", [])

    t_exec, t_dossie, t_analise = st.tabs(["📝 Execução Diária", "📁 Dossiê", "📊 Análise"])

    with t_exec:
        _render_execucao_etapa(projeto, etapa, idx_atual)

    with t_dossie:
        _render_dossie_projeto(projeto)

    with t_analise:
        _render_analise_projeto(projeto)


def _render_execucao_etapa(projeto, etapa, idx_atual):
    col_e1, col_e2 = st.columns([2, 1])

    with col_e1:
        st.markdown(f"### Etapa {idx_atual + 1}: {etapa['nome']}")

        with st.popover("➕ Adicionar Registro", use_container_width=True):
            txt_reg = st.text_area("Descrição do registro", key=f"reg_txt_{etapa['id']}")
            dlr = st.date_input("Lembrete (opcional)", value=None, key=f"reg_d_{etapa['id']}")
            hlr = st.time_input("Hora", value=None, key=f"reg_h_{etapa['id']}")
            if st.button("Gravar no Banco", type="primary", key=f"reg_btn_{etapa['id']}",
                         use_container_width=True):
                if txt_reg.strip():
                    etapa["notas"].append({
                        "texto": txt_reg.strip(),
                        "data": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"),
                    })
                    if dlr and hlr:
                        projeto["lembretes"].append({
                            "id": datetime.now(BRT).timestamp(),
                            "data_hora": f"{dlr.strftime('%d/%m/%Y')} {hlr.strftime('%H:%M')}",
                            "texto": f"{projeto['nome']} / {etapa['nome']}: {txt_reg.strip()[:60]}",
                        })
                    _salvar(projeto)
                    st.rerun()
                else:
                    st.warning("Descreva o registro.")

        notas_recentes = list(reversed(etapa.get("notas", [])))[:5]
        if notas_recentes:
            with st.expander(f"📌 Últimos registros ({len(etapa['notas'])} no total)"):
                for n in notas_recentes:
                    st.caption(f"🗓️ {n.get('data','')}")
                    st.write(n.get("texto", ""))
                    st.markdown("---")

        st.divider()
        st.markdown("#### 📋 Atividades RACI da Etapa")

        with st.popover("➕ Nova Atividade", use_container_width=True):
            txt_at = st.text_input("Descrição da Atividade", key=f"at_txt_{etapa['id']}")
            cprio, cstat = st.columns(2)
            prio = cprio.selectbox("Prioridade", PRIORIDADES, key=f"at_prio_{etapa['id']}")
            stt = cstat.selectbox("Status", STATUS_ATIV, key=f"at_stt_{etapa['id']}")
            dt_prev = st.date_input("Data Prevista", value=None, key=f"at_dtp_{etapa['id']}")
            if st.button("Adicionar", type="primary", key=f"badd_{etapa['id']}",
                         use_container_width=True):
                if txt_at.strip():
                    nova_ativ = {
                        "id": datetime.now(BRT).timestamp(),
                        "atividade": txt_at.strip(), "prioridade": prio, "status": stt,
                        "data_prevista": dt_prev.strftime("%d/%m/%Y") if dt_prev else None,
                        "data_entregue": None,
                        "papeis": {p: "" for p in projeto.get("pessoas", [])},
                        "prorrogacoes": 0, "historico_prazos": [],
                    }
                    etapa["atividades"].append(nova_ativ)
                    if dt_prev:
                        projeto["lembretes"].append({
                            "id": datetime.now(BRT).timestamp(),
                            "data_hora": f"{dt_prev.strftime('%d/%m/%Y')} 09:00",
                            "texto": f"Atividade: {txt_at.strip()} ({etapa['nome']})",
                        })
                    _salvar(projeto)
                    st.rerun()
                else:
                    st.warning("Informe a descrição da atividade.")

        atividades = etapa["atividades"]
        if atividades:
            total_at = len(atividades)
            concl_at = sum(1 for a in atividades if a.get("status") == "Concluído")
            st.progress(concl_at / total_at, text=f"{concl_at}/{total_at} atividades concluídas")

            for idx_a, ativ in enumerate(atividades):
                with st.container(border=True):
                    col_a, col_b, col_c = st.columns([0.08, 0.52, 0.4])
                    is_concl = ativ.get("status") == "Concluído"

                    chk = col_a.checkbox("", key=f"chk_{ativ['id']}_{idx_a}", value=is_concl)
                    if chk and not is_concl:
                        ativ["status"] = "Concluído"
                        ativ["data_entregue"] = datetime.now(BRT).strftime("%d/%m/%Y")
                        _salvar(projeto); st.rerun()
                    elif not chk and is_concl:
                        ativ["status"] = "Não Iniciado"
                        ativ["data_entregue"] = None
                        _salvar(projeto); st.rerun()

                    risco = "~~" if is_concl else ""
                    qtd_p = ativ.get("prorrogacoes", 0)
                    badge_p = f" ⚠️ *({qtd_p}x prorrogada)*" if qtd_p > 0 else ""
                    tag_prio = TAG_PRIORIDADE.get(ativ.get("prioridade", "Médio"), "tg")
                    col_b.markdown(
                        f'{risco}**{ativ["atividade"]}**{risco}{badge_p}<br>'
                        f'<span class="tag {tag_prio}">{ativ.get("prioridade","—")}</span>',
                        unsafe_allow_html=True)

                    col_c.caption(f"📅 Previsto: {ativ.get('data_prevista') or '—'}")
                    if ativ.get("data_entregue"):
                        col_c.caption(f"✅ Entregue: {ativ['data_entregue']}")

                    with col_c.popover("👥 Papéis (RACI)", use_container_width=True):
                        pessoas = projeto.get("pessoas", [])
                        if not pessoas:
                            st.caption("Cadastre pessoas em Configurações do Projeto.")
                        else:
                            ativ.setdefault("papeis", {})
                            mudou = False
                            for p in pessoas:
                                atual = ativ["papeis"].get(p, "")
                                novo = st.selectbox(
                                    p, PAPEIS_RACI,
                                    index=PAPEIS_RACI.index(atual) if atual in PAPEIS_RACI else 0,
                                    key=f"papel_{ativ['id']}_{p}_{idx_a}")
                                if novo != atual:
                                    ativ["papeis"][p] = novo
                                    mudou = True
                            if mudou and st.button("💾 Salvar Papéis", key=f"svpap_{ativ['id']}_{idx_a}",
                                                   type="primary", use_container_width=True):
                                _salvar(projeto); st.rerun()
                            st.caption(LEGENDA_RACI)

                    if not is_concl:
                        with col_c.popover("⏳ Prorrogar", use_container_width=True):
                            nova_dt = st.date_input("Nova Data", key=f"ndt_{ativ['id']}_{idx_a}")
                            motivo_p = st.text_input("Motivo (opcional)", key=f"mot_{ativ['id']}_{idx_a}")
                            if st.button("Confirmar Nova Data", key=f"cnfp_{ativ['id']}_{idx_a}",
                                         use_container_width=True):
                                prazo_antigo = ativ.get("data_prevista") or "—"
                                ativ.setdefault("historico_prazos", []).append({
                                    "de": prazo_antigo, "motivo": motivo_p,
                                    "data_alteracao": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"),
                                })
                                ativ["data_prevista"] = nova_dt.strftime("%d/%m/%Y")
                                ativ["prorrogacoes"] = ativ.get("prorrogacoes", 0) + 1
                                etapa["notas"].append({
                                    "texto": f"Atividade '{ativ['atividade']}' adiada de "
                                             f"{prazo_antigo} para {ativ['data_prevista']}. "
                                             f"Motivo: {motivo_p or '—'}",
                                    "data": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"),
                                })
                                _salvar(projeto)
                                st.success("Prazo prorrogado!")
                                st.rerun()

                    if col_c.button("🗑️", key=f"delat_{ativ['id']}_{idx_a}", use_container_width=True):
                        etapa["atividades"].pop(idx_a)
                        _salvar(projeto)
                        st.rerun()
        else:
            st.info("Nenhuma atividade cadastrada para esta etapa.")

    with col_e2:
        st.markdown("#### ⚙️ Controle")

        pendentes_etapa = [a for a in etapa["atividades"] if a.get("status") != "Concluído"]
        if pendentes_etapa:
            st.warning(f"⚠️ {len(pendentes_etapa)} atividade(s) pendente(s) nesta etapa.")

        cav1, cav2 = st.columns(2)
        if cav1.button("▶️ AVANÇAR", use_container_width=True, type="primary",
                       key=f"avanca_{projeto['id']}") and idx_atual < len(projeto["etapas"]) - 1:
            projeto["etapa_atual"] = idx_atual + 1
            _salvar(projeto)
            st.rerun()
        if cav2.button("⏪ RECUAR", use_container_width=True,
                       key=f"recua_{projeto['id']}") and idx_atual > 0:
            projeto["etapa_atual"] = idx_atual - 1
            _salvar(projeto)
            st.rerun()

        st.markdown("#### ⏰ Lembretes do Projeto")
        if not projeto["lembretes"]:
            st.caption("Nenhum lembrete agendado.")
        for l_idx, l in enumerate(projeto["lembretes"]):
            with st.container(border=True):
                st.caption(f"📅 {l['data_hora']}")
                st.write(l["texto"])
                if st.button("Concluir", key=f"done_proj_lemb_{l.get('id', l_idx)}"):
                    projeto["lembretes"].pop(l_idx)
                    _salvar(projeto)
                    st.rerun()


def _render_dossie_projeto(projeto):
    sub_dos1, sub_dos2 = st.tabs(["📂 Pastas", "📜 Histórico"])

    with sub_dos1:
        with st.popover("➕ Criar Pasta", use_container_width=True):
            nome_pasta = st.text_input("Nome da Pasta", key=f"np_{projeto['id']}")
            if st.button("Salvar Pasta", key=f"svnp_{projeto['id']}"):
                if nome_pasta.strip():
                    projeto["pastas_virtuais"].setdefault(nome_pasta.strip(), [])
                    _salvar(projeto)
                    st.rerun()
                else:
                    st.warning("Informe um nome para a pasta.")

        pastas = projeto["pastas_virtuais"]
        for p_nome in list(pastas.keys()):
            with st.expander(f"📁 {p_nome}"):
                col_p1, col_p2 = st.columns([3, 1])
                if col_p2.button("🗑️ Excluir Pasta", key=f"delpasta_{projeto['id']}_{p_nome}"):
                    for arq in pastas[p_nome]:
                        deletar_arquivo_raci_db(arq["file_id"])
                    del pastas[p_nome]
                    _salvar(projeto)
                    st.rerun()

                up_files = st.file_uploader("Anexar (Máx 1MB)", accept_multiple_files=True,
                                            key=f"up_{projeto['id']}_{p_nome}")
                if st.button("Subir para o Banco", key=f"upbtn_{projeto['id']}_{p_nome}"):
                    for a in up_files or []:
                        tamanho_mb = a.size / (1024 * 1024)
                        if tamanho_mb > 1.0:
                            st.error(f"Arquivo {a.name} é muito grande ({tamanho_mb:.2f}MB). Limite: 1MB.")
                            continue
                        file_id = f"{datetime.now(BRT).timestamp()}_{a.name}"
                        if salvar_arquivo_raci_db(file_id, a.getvalue()):
                            pastas[p_nome].append({
                                "nome": a.name, "file_id": file_id,
                                "data": datetime.now(BRT).strftime("%d/%m/%Y"),
                            })
                    _salvar(projeto)
                    st.success("Arquivos sincronizados!")
                    st.rerun()

                st.write("---")
                for idx_f, arq in enumerate(pastas[p_nome]):
                    c_arq1, c_arq2 = st.columns([4, 1])
                    c_arq1.write(f"📄 {arq['nome']} ({arq['data']})")
                    if c_arq2.button("📥 Preparar", key=f"prep_{p_nome}_{idx_f}"):
                        conteudo = baixar_arquivo_raci_db(arq["file_id"])
                        if conteudo:
                            st.download_button(
                                "Baixar Agora", data=conteudo, file_name=arq["nome"],
                                mime="application/octet-stream",
                                key=f"final_dl_{p_nome}_{idx_f}")
                        else:
                            st.error("Arquivo não encontrado no banco.")

    with sub_dos2:
        todas_notas = []
        for et in projeto["etapas"]:
            for n in et.get("notas", []):
                todas_notas.append({"Etapa": et["nome"], "Data": n.get("data", ""),
                                    "Registro": n.get("texto", "")})
        if todas_notas:
            df_hist = pd.DataFrame(todas_notas).sort_values("Data", ascending=False)
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum registro histórico encontrado.")


def _render_analise_projeto(projeto):
    linhas_at = []
    for et in projeto["etapas"]:
        for a in et.get("atividades", []):
            linhas_at.append({"Etapa": et["nome"], "Status": a.get("status", "—"),
                              "Prioridade": a.get("prioridade", "—")})
    if not linhas_at:
        st.info("Nenhum dado de esforço registrado ainda.")
        return

    df_esf = pd.DataFrame(linhas_at)
    st.markdown(f"### Análise: {projeto['nome']}")
    cga, cgb = st.columns(2)
    with cga:
        st.markdown("##### Atividades por Etapa")
        fig = px.pie(df_esf, names="Etapa", hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Prism)
        fig.update_layout(margin=dict(l=20, r=20, t=20, b=20), height=300)
        st.plotly_chart(fig, use_container_width=True)
    with cgb:
        st.markdown("##### Atividades por Status")
        fig2 = px.bar(df_esf["Status"].value_counts().reset_index(),
                      x="Status", y="count", color_discrete_sequence=["#C9A84C"])
        st.plotly_chart(fig2, use_container_width=True)


# ════════════════════════════════════════════════════════════════
# ABA 4 — LEMBRETES & PRODUTIVIDADE
# ════════════════════════════════════════════════════════════════
def _periodo_por_preset(preset):
    hoje = date.today()
    if preset == "Esta Semana":
        ini = hoje - timedelta(days=hoje.weekday())  # segunda-feira desta semana
        return ini, hoje
    if preset == "Este Mês":
        return hoje.replace(day=1), hoje
    return None, None  # Personalizado: tratado fora


def _render_todos_lembretes(uname, lembretes, raci_projetos):
    st.markdown("##### 📊 Dossiê de Atividades")
    st.caption("Filtre por período para apresentar o que foi executado — útil para repasse a gestores.")

    nomes_proj_v = [p["nome"] for p in raci_projetos]

    fc1, fc2 = st.columns([1.2, 2])
    with fc1:
        preset = st.selectbox("Período", ["Esta Semana", "Este Mês", "Personalizado"],
                              key="dossie_periodo_preset")
    if preset == "Personalizado":
        with fc2:
            periodo = st.date_input(
                "Intervalo", value=(date.today() - timedelta(days=7), date.today()),
                format="DD/MM/YYYY", key="dossie_periodo_custom",
            )
        if isinstance(periodo, (tuple, list)) and len(periodo) == 2:
            data_ini, data_fim = periodo
        else:
            data_ini, data_fim = None, None
    else:
        data_ini, data_fim = _periodo_por_preset(preset)

    if not data_ini or not data_fim:
        st.info("Selecione um período completo (data inicial e final) para gerar o dossiê.")
    else:
        executados_periodo = []
        for l in lembretes:
            if l.get("status") != "Executado":
                continue
            dt_l = _parse_data(l.get("data_hora", ""))
            if dt_l is None or not (data_ini <= dt_l.date() <= data_fim):
                continue
            executados_periodo.append(l)

        total = len(executados_periodo)
        vinculados = [l for l in executados_periodo if l.get("vinculo")]
        pontuais = [l for l in executados_periodo if not l.get("vinculo")]

        st.caption(f"Período: **{data_ini.strftime('%d/%m/%Y')}** a **{data_fim.strftime('%d/%m/%Y')}**")
        k1, k2, k3 = st.columns(3)
        k1.markdown(f'<div class="kpi-card gold"><div class="kpi-label">Total Executado</div>'
                    f'<div class="kpi-value">{total}</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card blue"><div class="kpi-label">Vinculado a Projeto</div>'
                    f'<div class="kpi-value">{len(vinculados)}</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card gray"><div class="kpi-label">Pontual</div>'
                    f'<div class="kpi-value">{len(pontuais)}</div></div>', unsafe_allow_html=True)

        if total:
            st.markdown("")
            from collections import Counter
            cont_proj = Counter(l.get("vinculo") or "Pontual (fora de projetos)" for l in executados_periodo)
            df_resumo = pd.DataFrame(cont_proj.most_common(), columns=["Vínculo", "Qtd."])
            st.dataframe(df_resumo, use_container_width=True, hide_index=True)

            st.markdown("**Detalhamento do período:**")
            df_det = pd.DataFrame([{
                "Data": l.get("data_hora", ""),
                "Atividade": l.get("texto", ""),
                "Vínculo": l.get("vinculo") or "Pontual (fora de projetos)",
            } for l in sorted(executados_periodo, key=lambda x: x.get("data_hora", ""))])
            st.dataframe(df_det, use_container_width=True, hide_index=True)

            from io import BytesIO
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                df_det.to_excel(writer, index=False, sheet_name="Detalhamento")
                df_resumo.to_excel(writer, index=False, sheet_name="Resumo")
                for nome_aba, df in [("Detalhamento", df_det), ("Resumo", df_resumo)]:
                    ws = writer.sheets[nome_aba]
                    for i, col in enumerate(df.columns):
                        largura = max(df[col].astype(str).map(len).max(), len(col)) + 2
                        ws.set_column(i, i, largura)
            buf.seek(0)
            st.download_button(
                "📥 Baixar Dossiê do Período (.xlsx)", data=buf.getvalue(),
                file_name=f"Dossie_Atividades_{data_ini.strftime('%Y%m%d')}_a_{data_fim.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary", use_container_width=True,
            )
        else:
            st.info("Nenhuma atividade executada nesse período ainda.")

        # ── PRODUTIVIDADE CONSOLIDADA (Diário + Lembretes, com tempo) ──
        st.divider()
        st.markdown("##### ⏱️ Produtividade Consolidada (Diário + Lembretes)")
        st.caption(
            "Une os registros do Diário de Bordo (cronometrados) com os lembretes "
            "concluídos no mesmo período — inclusive os que viraram cronômetro a "
            "partir de um lembrete. Tudo num relatório só."
        )

        linhas_prod = _linhas_produtividade(uname, data_ini, data_fim, lembretes)
        if not linhas_prod:
            st.info("Nenhuma atividade (com ou sem cronômetro) registrada nesse período.")
        else:
            segundos_totais = sum(l["_segundos"] for l in linhas_prod)
            st.markdown(f"**⏱️ Tempo total cronometrado no período:** {_formatar_duracao(segundos_totais)}")

            df_prod = pd.DataFrame([
                {"Data": l["Data"], "Atividade": l["Atividade"], "Origem": l["Origem"], "Duração": l["Duração"]}
                for l in sorted(linhas_prod, key=lambda x: x["Data"])
            ])
            st.dataframe(df_prod, use_container_width=True, hide_index=True)

            from io import BytesIO
            buf_p = BytesIO()
            with pd.ExcelWriter(buf_p, engine="xlsxwriter") as writer:
                df_prod.to_excel(writer, index=False, sheet_name="Produtividade")
                ws = writer.sheets["Produtividade"]
                for i, col in enumerate(df_prod.columns):
                    largura = max(df_prod[col].astype(str).map(len).max(), len(col)) + 2
                    ws.set_column(i, i, largura)
            buf_p.seek(0)
            st.download_button(
                "📥 Baixar Produtividade Consolidada (.xlsx)", data=buf_p.getvalue(),
                file_name=f"Produtividade_{uname}_{data_ini.strftime('%Y%m%d')}_a_{data_fim.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.divider()
    st.markdown("##### 🔔 Gerenciar Meus Lembretes")
    if not lembretes:
        st.info("Nenhum lembrete cadastrado ainda.")
        return

    filtro = st.multiselect(
        "Filtrar por status:", ["Pendente", "Em Execução", "Executado"],
        default=["Pendente", "Em Execução"], key="filtro_lembretes_home",
    )
    opcoes_vinculo = ["Pontual (fora de projetos)"] + nomes_proj_v
    for l in lembretes:
        status_l = l.get("status", "Pendente")
        if filtro and status_l not in filtro:
            continue
        with st.container(border=True):
            cols = st.columns([3, 1.4, 1.6, 1, 1])
            icone = {"Executado": "✅", "Em Execução": "⏱️"}.get(status_l, "🔵")
            cols[0].write(f"{icone} {l.get('texto','')}")
            cols[1].caption(l.get("data_hora", ""))

            vinc_atual = l.get("vinculo") or "Pontual (fora de projetos)"
            idx_vinc = opcoes_vinculo.index(vinc_atual) if vinc_atual in opcoes_vinculo else 0
            novo_vinc = cols[2].selectbox(
                "Vínculo", opcoes_vinculo, index=idx_vinc,
                key=f"vinc_{l['id']}", label_visibility="collapsed",
            )
            if novo_vinc != vinc_atual:
                novo_vinculo_db = "" if novo_vinc == "Pontual (fora de projetos)" else novo_vinc
                atualizar_lembrete_pessoal_db(l["id"], vinculo=novo_vinculo_db)
                st.rerun()

            if status_l == "Pendente":
                if cols[3].button("✅", key=f"lemb_ok_{l['id']}", use_container_width=True):
                    atualizar_lembrete_pessoal_db(l["id"], status="Executado")
                    st.rerun()
            if cols[4].button("🗑️", key=f"lemb_del_{l['id']}", use_container_width=True):
                deletar_lembrete_pessoal_db(l["id"])
                st.rerun()

            historico_l = l.get("historico_adiamentos", [])
            if historico_l:
                with st.expander(f"⏳ Histórico de adiamentos ({len(historico_l)})"):
                    for h in reversed(historico_l):
                        st.caption(
                            f"{h.get('data_alteracao','')} — de **{h.get('de','')}** "
                            f"para **{h.get('para', l.get('data_hora',''))}**. "
                            f"Motivo: {h.get('motivo','—')}"
                        )
