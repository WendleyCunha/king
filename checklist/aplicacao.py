"""
checklist/aplicacao.py
Aba "Aplicação" — execução de um checklist publicado em campo: iniciar,
responder cada pergunta, anexar evidência (foto) e concluir.

Nota sobre regras condicionais: das seis regras possíveis (exibir / ocultar /
exigir / tornar_opcional / exigir_evidencia / disparar_nao_conformidade), só
o efeito 'exigir' é de fato avaliado pelo servidor (na hora de concluir,
decidindo quais perguntas ficam obrigatórias). Por isso esta tela replica
essa mesma lógica para avisar em tempo real quais perguntas ficaram
obrigatórias por causa de uma regra — os outros efeitos já existem no
cadastro (aba Editor), mas não têm comportamento próprio aqui ainda, pra
não fingir uma validação que o servidor não faz de fato neste MVP.

Limitação conhecida: a API não tem uma rota para LISTAR aplicações em
andamento — só para iniciar uma (e devolver o id) e consultar uma pelo id.
Por isso esta tela só acompanha a aplicação atual dentro da mesma sessão do
navegador (guardada em st.session_state). Pra retomar depois de fechar a
aba, seria necessário colar o ID da aplicação manualmente (campo oferecido
abaixo) — ou aguardar até que a API ganhe uma rota de listagem.
"""
import datetime as _dt
import streamlit as st
from . import api_client as api

_OPERADORES = {
    "=": lambda a, b: a == b, "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b, "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
}


def _avaliar_condicao(condicao, respostas_por_item):
    """Réplica exata de avaliar_condicao() da API (modules.py) — usada só
    para dar feedback em tempo real na tela, sem esperar o servidor recusar."""
    if "item_id" in condicao:
        item_id = str(condicao["item_id"])
        operador = condicao.get("operador_comparacao", "=")
        valor_esperado = condicao.get("valor")
        if item_id not in respostas_por_item:
            return False
        comparador = _OPERADORES.get(operador)
        if comparador is None:
            return False
        try:
            return bool(comparador(respostas_por_item[item_id], valor_esperado))
        except TypeError:
            return False
    operador_logico = condicao.get("operador", "E")
    resultados = [_avaliar_condicao(sub, respostas_por_item) for sub in condicao.get("condicoes", [])]
    return any(resultados) if operador_logico == "OU" else all(resultados)


def _iniciar_nova_aplicacao():
    checklists = api.get("/api/v1/checklists", mostrar_erro=False) or []
    checklists_ativos = [c for c in checklists if c["status"] == "ativo"]
    if not checklists_ativos:
        st.info("Nenhum checklist publicado ainda — publique um na aba Editor primeiro.")
        return
    unidades = api.get("/api/v1/unidades", mostrar_erro=False) or []
    if not unidades:
        st.info("Cadastre uma unidade primeiro, na aba Estrutura.")
        return

    mapa_checklists = {c["nome"]: c["id"] for c in checklists_ativos}
    mapa_unidades = {u["nome"]: u["id"] for u in unidades}

    checklist_nome = st.selectbox("Checklist", list(mapa_checklists.keys()))
    unidade_nome = st.selectbox("Unidade", list(mapa_unidades.keys()))
    setores = api.get("/api/v1/setores", params={"unidade_id": mapa_unidades[unidade_nome]},
                       mostrar_erro=False) or []
    mapa_setores = {s["nome"]: s["id"] for s in setores}
    setor_nome = st.selectbox("Setor (opcional)", ["— Nenhum —"] + list(mapa_setores.keys()))

    if st.button("▶️ Iniciar Aplicação", type="primary"):
        corpo = {"checklist_id": mapa_checklists[checklist_nome], "unidade_id": mapa_unidades[unidade_nome]}
        if setor_nome != "— Nenhum —":
            corpo["setor_id"] = mapa_setores[setor_nome]
        r = api.post("/api/v1/aplicacoes", corpo, mostrar_sucesso="Aplicação iniciada!")
        if r:
            st.session_state.aplicacao_atual_id = r["id"]
            st.session_state.aplicacao_atual_checklist_id = mapa_checklists[checklist_nome]
            st.rerun()

    st.markdown("---")
    st.caption("Já tem uma aplicação em andamento de outra sessão? Cole o ID dela aqui para continuar:")
    id_manual = st.text_input("ID da aplicação", key="id_aplicacao_manual")
    if st.button("Retomar", key="btn_retomar_aplicacao"):
        detalhe = api.get(f"/api/v1/aplicacoes/{id_manual.strip()}")
        if detalhe:
            st.session_state.aplicacao_atual_id = detalhe["aplicacao"]["id"]
            st.session_state.aplicacao_atual_checklist_id = None  # não sabemos sem consultar mais; ok pra visualização
            st.rerun()


def _widget_para_tipo(tipo_chave: str, key: str, valor_atual=None):
    if tipo_chave == "sim_nao":
        opcoes = ["— Sem resposta —", "Sim", "Não"]
        idx = 1 if valor_atual is True else (2 if valor_atual is False else 0)
        escolha = st.selectbox("Resposta", opcoes, index=idx, key=key)
        return {"Sim": True, "Não": False}.get(escolha)
    if tipo_chave == "conforme_nao_conforme":
        opcoes = ["— Sem resposta —", "conforme", "nao_conforme"]
        idx = opcoes.index(valor_atual) if valor_atual in opcoes else 0
        escolha = st.selectbox("Resposta", opcoes, index=idx, key=key)
        return escolha if escolha != "— Sem resposta —" else None
    if tipo_chave == "texto_curto":
        v = st.text_input("Resposta", value=valor_atual or "", max_chars=255, key=key)
        return v or None
    if tipo_chave == "texto_longo":
        v = st.text_area("Resposta", value=valor_atual or "", key=key)
        return v or None
    if tipo_chave == "numero":
        return st.number_input("Resposta", value=float(valor_atual) if valor_atual is not None else 0.0, key=key)
    if tipo_chave == "nota_0_10":
        return st.slider("Nota", 0, 10, int(valor_atual) if valor_atual is not None else 5, key=key)
    if tipo_chave == "data":
        return st.date_input("Data", key=key).isoformat()
    if tipo_chave == "foto":
        st.caption("Anexe a foto no campo de evidência (📷) abaixo — este tipo não tem texto de resposta.")
        return True  # marca "respondido" só pela evidência
    return st.text_input("Resposta", value=str(valor_atual) if valor_atual else "", key=key)


def _preencher_aplicacao(aplicacao_id):
    detalhe = api.get(f"/api/v1/aplicacoes/{aplicacao_id}")
    if not detalhe:
        return
    aplicacao = detalhe["aplicacao"]

    if aplicacao["status"] == "concluida":
        st.success(
            f"✅ Aplicação concluída — "
            f"{aplicacao.get('percentual_conformidade', '—')}% de conformidade."
        )
        if st.button("Iniciar uma nova aplicação"):
            del st.session_state["aplicacao_atual_id"]
            st.rerun()
        return

    checklist_id = st.session_state.get("aplicacao_atual_checklist_id")
    if not checklist_id:
        # Aplicação retomada por ID manual — precisamos descobrir o checklist a
        # partir da versão, já que AplicacaoOut só traz checklist_versao_id.
        st.warning("Estrutura não disponível para aplicações retomadas por ID (limitação desta tela). "
                   "Use a aplicação recém-iniciada nesta mesma sessão para o formulário completo.")
        return

    versao_publicada = api.get(f"/api/v1/checklists/{checklist_id}/versao-publicada")
    if not versao_publicada or not versao_publicada.get("snapshot_estrutura"):
        st.error("Não foi possível carregar a estrutura publicada deste checklist.")
        return

    respostas_por_item = {str(r["item_id"]): r["valor"] for r in detalhe["respostas"]}
    respostas_ids_por_item = {str(r["item_id"]): r["id"] for r in detalhe["respostas"]}

    for area in versao_publicada["snapshot_estrutura"]["areas"]:
        st.markdown(f"#### 📁 {area['nome']}")
        for item in area["itens"]:
            item_id = item["id"]
            regras_exigir = [r for r in item.get("regras", []) if r["tipo_efeito"] == "exigir"]
            obrigatorio_condicional = any(
                _avaliar_condicao(r["condicao"], respostas_por_item) for r in regras_exigir
            )
            obrigatorio_efetivo = item["obrigatorio"] or obrigatorio_condicional
            marcador = " **\\***" if obrigatorio_efetivo else ""
            aviso_condicional = " _(obrigatório por uma regra condicional)_" if obrigatorio_condicional and not item["obrigatorio"] else ""

            with st.container(border=True):
                st.markdown(f"**{item['titulo']}**{marcador}{aviso_condicional}")
                valor_atual = respostas_por_item.get(item_id)
                novo_valor = _widget_para_tipo(item["tipo_resposta"], key=f"resp_{aplicacao_id}_{item_id}",
                                                valor_atual=valor_atual)

                foto = None
                if item.get("evidencia_obrigatoria") or item["tipo_resposta"] == "foto":
                    foto = st.camera_input("📷 Evidência (foto)", key=f"foto_{aplicacao_id}_{item_id}")

                if st.button("💾 Salvar resposta", key=f"btn_salvar_{aplicacao_id}_{item_id}"):
                    if novo_valor is None and item["tipo_resposta"] != "foto":
                        st.warning("Preencha uma resposta antes de salvar.")
                    else:
                        r = api.post(f"/api/v1/aplicacoes/{aplicacao_id}/respostas", {
                            "item_id": item_id, "valor": novo_valor,
                        }, mostrar_sucesso="Resposta salva!")
                        if r and foto is not None:
                            base64_foto = "data:image/jpeg;base64," + _bytes_para_base64(foto.getvalue())
                            api.post(f"/api/v1/aplicacoes/{aplicacao_id}/evidencias", {
                                "resposta_id": r["id"], "tipo": "foto",
                                "arquivo_url": base64_foto, "capturado_via_camera_direta": True,
                            })
                        if r:
                            st.rerun()

    st.markdown("---")
    if st.button("✅ Concluir Aplicação", type="primary"):
        resultado = api.post(f"/api/v1/aplicacoes/{aplicacao_id}/concluir", {})
        if resultado:
            st.success(
                f"🎉 Aplicação concluída! Conformidade: {resultado.get('percentual_conformidade', '—')}%"
            )
            st.rerun()


def _bytes_para_base64(dados: bytes) -> str:
    import base64
    return base64.b64encode(dados).decode("ascii")


def renderizar_aplicacao():
    aplicacao_id = st.session_state.get("aplicacao_atual_id")
    if aplicacao_id:
        col1, col2 = st.columns([4, 1])
        col1.caption(f"Aplicação em andamento: `{aplicacao_id}`")
        if col2.button("Cancelar / trocar"):
            del st.session_state["aplicacao_atual_id"]
            st.rerun()
        _preencher_aplicacao(aplicacao_id)
    else:
        st.markdown("### ▶️ Iniciar nova aplicação")
        _iniciar_nova_aplicacao()
