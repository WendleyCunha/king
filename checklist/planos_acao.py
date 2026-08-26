"""
checklist/planos_acao.py
Aba "Planos de Ação" — 5W2H (what/why/where/when/who/how/how_much), criação
avulsa, listagem com filtros e mudança de status respeitando as transições
que a API valida (ver _TRANSICOES_VALIDAS em modules.py):

    pendente      -> em_andamento, cancelado
    em_andamento  -> concluido, atrasado, cancelado
    atrasado      -> em_andamento, concluido, cancelado
    concluido     -> (estado final)
    cancelado     -> (estado final)
"""
import base64
import datetime as _dt
import streamlit as st
from . import api_client as api

TRANSICOES_VALIDAS = {
    "pendente": ["em_andamento", "cancelado"],
    "em_andamento": ["concluido", "atrasado", "cancelado"],
    "atrasado": ["em_andamento", "concluido", "cancelado"],
    "concluido": [],
    "cancelado": [],
}

STATUS_LABEL = {
    "pendente": "🟡 Pendente", "em_andamento": "🔵 Em andamento",
    "atrasado": "🔴 Atrasado", "concluido": "🟢 Concluído", "cancelado": "⚪ Cancelado",
}


def _mapa_usuarios():
    usuarios = api.get("/api/v1/usuarios", mostrar_erro=False) or []
    return {u["nome"]: u["id"] for u in usuarios}


def _form_novo_plano_avulso():
    with st.expander("➕ Novo Plano de Ação (avulso)", expanded=False):
        mapa_usuarios = _mapa_usuarios()
        if not mapa_usuarios:
            st.caption("Cadastre um colaborador primeiro, na aba Colaboradores.")
            return
        with st.form("form_novo_plano_avulso"):
            titulo = st.text_input("Título")
            responsavel_nome = st.selectbox("Responsável", list(mapa_usuarios.keys()))
            prazo = st.date_input("Prazo", value=_dt.date.today() + _dt.timedelta(days=7))
            st.markdown("**5W2H** _(todos os campos abaixo são opcionais)_")
            what = st.text_area("O quê (what)", height=60)
            why = st.text_area("Por quê (why)", height=60)
            col1, col2 = st.columns(2)
            where_ = col1.text_input("Onde (where)")
            when_ = col2.text_input("Quando (when)")
            who = col1.text_input("Quem (who)")
            how = col2.text_area("Como (how)", height=60)
            how_much = st.text_input("Quanto custa (how much)")
            if st.form_submit_button("Criar Plano"):
                if not titulo.strip():
                    st.warning("Informe um título.")
                else:
                    r = api.post("/api/v1/planos-acao", {
                        "origem_tipo": "AVULSO",
                        "titulo": titulo.strip(),
                        "what": what or None, "why": why or None, "where_": where_ or None,
                        "when_": when_ or None, "who": who or None, "how": how or None,
                        "how_much": how_much or None,
                        "responsavel_id": mapa_usuarios[responsavel_nome],
                        "prazo": prazo.isoformat(),
                    }, mostrar_sucesso=f"Plano de Ação '{titulo}' criado!")
                    if r:
                        st.rerun()


def _card_plano(p, mapa_usuarios_inverso):
    responsavel = mapa_usuarios_inverso.get(p["responsavel_id"], p["responsavel_id"])
    with st.expander(f"**{p['titulo']}** · {STATUS_LABEL.get(p['status'], p['status'])} · prazo {p['prazo']}"):
        col1, col2 = st.columns(2)
        col1.markdown(f"**Responsável:** {responsavel}")
        col2.markdown(f"**Origem:** {p['origem_tipo']}")

        transicoes = TRANSICOES_VALIDAS.get(p["status"], [])
        if transicoes:
            novo_status = st.selectbox(
                "Mudar status para", ["— manter —"] + transicoes,
                key=f"status_plano_{p['id']}",
                format_func=lambda s: s if s == "— manter —" else STATUS_LABEL.get(s, s),
            )
            if novo_status != "— manter —" and st.button("💾 Atualizar status", key=f"btn_status_{p['id']}"):
                r = api.patch(f"/api/v1/planos-acao/{p['id']}/status", {"status": novo_status},
                              mostrar_sucesso="Status atualizado!")
                if r:
                    st.rerun()
        else:
            st.caption("Este plano está em um estado final (não aceita mais mudanças de status).")

        st.markdown("---")
        foto = st.file_uploader("📷 Anexar evidência de encerramento", type=["jpg", "jpeg", "png"],
                                 key=f"evid_plano_{p['id']}")
        if foto is not None and st.button("Salvar evidência", key=f"btn_evid_plano_{p['id']}"):
            base64_foto = "data:image/jpeg;base64," + base64.b64encode(foto.getvalue()).decode("ascii")
            r = api.post(f"/api/v1/planos-acao/{p['id']}/evidencias", {
                "tipo": "foto", "arquivo_url": base64_foto,
            }, mostrar_sucesso="Evidência anexada!")
            if r:
                st.rerun()


def renderizar_planos_acao():
    _form_novo_plano_avulso()

    st.markdown("### 🛠️ Planos de Ação")
    col1, col2 = st.columns(2)
    filtro_status = col1.selectbox("Filtrar por status", ["Todos"] + list(STATUS_LABEL.keys()),
                                    format_func=lambda s: s if s == "Todos" else STATUS_LABEL[s])
    somente_atrasados = col2.checkbox("Somente atrasados")

    params = {}
    if filtro_status != "Todos":
        params["status"] = filtro_status
    if somente_atrasados:
        params["atrasados"] = True

    planos = api.get("/api/v1/planos-acao", params=params) or []
    usuarios = api.get("/api/v1/usuarios", mostrar_erro=False) or []
    mapa_usuarios_inverso = {u["id"]: u["nome"] for u in usuarios}

    if not planos:
        st.info("Nenhum plano de ação encontrado com esse filtro.")
    for p in planos:
        _card_plano(p, mapa_usuarios_inverso)
