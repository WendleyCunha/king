"""
checklist/editor.py
Aba "Editor de Checklist" — criar checklist, gerenciar áreas, perguntas
(itens) e regras condicionais, e publicar uma versão.

Fluxo do backend (importante pra UI fazer sentido):
  - Um Checklist sempre nasce com uma Versão em RASCUNHO (versão 1).
  - Só dá pra editar (criar área/pergunta/regra) numa versão em rascunho.
  - "Publicar" congela um snapshot imutável dessa versão — depois disso, pra
    editar de novo é preciso criar uma NOVA versão (que clona áreas/perguntas
    da última, mas não as regras — regras precisam ser recriadas).
  - Só um checklist com uma versão PUBLICADA pode ser usado para iniciar uma
    aplicação em campo (aba "Aplicação").
"""
import streamlit as st
from . import api_client as api

TIPOS_RESPOSTA_LABEL = {
    "sim_nao": "Sim / Não",
    "conforme_nao_conforme": "Conforme / Não conforme",
    "texto_curto": "Texto curto",
    "texto_longo": "Texto longo",
    "numero": "Número",
    "nota_0_10": "Nota (0 a 10)",
    "foto": "Foto",
    "data": "Data",
}

TIPOS_EFEITO_LABEL = {
    "exibir": "Exibir o item alvo",
    "ocultar": "Ocultar o item alvo",
    "exigir": "Tornar o item alvo obrigatório",
    "tornar_opcional": "Tornar o item alvo opcional",
    "exigir_evidencia": "Exigir foto no item alvo",
    "disparar_nao_conformidade": "Disparar não conformidade",
}

OPERADORES_LABEL = {"=": "for igual a", "!=": "for diferente de", ">": "for maior que",
                     "<": "for menor que", ">=": "for maior ou igual a", "<=": "for menor ou igual a"}


def _selecionar_ou_criar_checklist():
    with st.expander("➕ Novo Checklist", expanded=False):
        unidades = api.get("/api/v1/unidades", mostrar_erro=False) or []
        mapa_unidades = {u["nome"]: u["id"] for u in unidades}
        with st.form("form_novo_checklist_editor"):
            nome = st.text_input("Nome do checklist (ex: Auditoria de Expedição)")
            descricao = st.text_area("Descrição (opcional)", height=70)
            unidade_nome = st.selectbox(
                "Unidade (opcional — deixe em branco para um checklist-modelo, "
                "reutilizável em qualquer unidade)",
                ["— Nenhuma (modelo global) —"] + list(mapa_unidades.keys()),
            )
            if st.form_submit_button("Criar"):
                if not nome.strip():
                    st.warning("Informe um nome.")
                else:
                    corpo = {"nome": nome.strip(), "descricao": descricao.strip() or None}
                    if unidade_nome != "— Nenhuma (modelo global) —":
                        corpo["unidade_id"] = mapa_unidades[unidade_nome]
                    r = api.post("/api/v1/checklists", corpo, mostrar_sucesso=f"Checklist '{nome}' criado!")
                    if r:
                        st.session_state.checklist_editor_id = r["id"]
                        st.rerun()

    checklists = api.get("/api/v1/checklists") or []
    if not checklists:
        return None

    mapa = {f"{c['nome']} · {c['status']}": c["id"] for c in checklists}
    nomes = list(mapa.keys())
    atual_id = st.session_state.get("checklist_editor_id")
    index_atual = 0
    for i, id_c in enumerate(mapa.values()):
        if id_c == atual_id:
            index_atual = i
            break
    escolha = st.selectbox("Checklist selecionado", nomes, index=index_atual)
    checklist_id = mapa[escolha]
    st.session_state.checklist_editor_id = checklist_id
    return checklist_id


def _gerenciar_versao(checklist_id):
    """Garante que existe uma versão em rascunho editável. Retorna a versão
    (dict) em rascunho, ou None se o usuário ainda precisa criar uma nova
    (nesse caso já mostra o botão pra isso)."""
    versoes = api.get(f"/api/v1/checklists/{checklist_id}/versoes", mostrar_erro=False) or []
    rascunho = next((v for v in versoes if v["status"] == "rascunho"), None)
    publicada = next((v for v in versoes if v["status"] == "publicada"), None)

    if publicada:
        st.caption(f"✅ Versão {publicada['numero_versao']} publicada e em uso pelas aplicações em campo.")

    if rascunho:
        st.caption(f"✏️ Editando a versão {rascunho['numero_versao']} (ainda não publicada).")
        return rascunho

    st.warning("Este checklist não tem nenhuma versão em rascunho editável no momento.")
    if st.button("➕ Criar nova versão para editar", key=f"btn_nova_versao_{checklist_id}"):
        r = api.post(f"/api/v1/checklists/{checklist_id}/versoes", {}, mostrar_sucesso="Nova versão criada!")
        if r:
            st.rerun()
    return None


def _form_nova_area(checklist_id, ordem_sugerida):
    with st.expander("➕ Nova Área/Seção", expanded=(ordem_sugerida == 0)):
        with st.form("form_nova_area"):
            nome = st.text_input("Nome da área (ex: Doca de Carregamento)")
            ordem = st.number_input("Ordem", min_value=0, value=ordem_sugerida, step=1)
            if st.form_submit_button("Criar Área"):
                if not nome.strip():
                    st.warning("Informe um nome.")
                else:
                    r = api.post(f"/api/v1/checklists/{checklist_id}/areas",
                                 {"nome": nome.strip(), "ordem": int(ordem)},
                                 mostrar_sucesso=f"Área '{nome}' criada!")
                    if r:
                        st.rerun()


def _form_nova_pergunta(checklist_id, area):
    with st.expander(f"➕ Nova pergunta em '{area['nome']}'", expanded=False):
        tipo_chave = st.selectbox(
            "Tipo de resposta", list(TIPOS_RESPOSTA_LABEL.keys()),
            format_func=lambda k: TIPOS_RESPOSTA_LABEL[k], key=f"tiposel_{area['id']}",
        )
        with st.form(f"form_nova_pergunta_{area['id']}"):
            titulo = st.text_input("Pergunta / item")
            col1, col2, col3 = st.columns(3)
            obrigatorio = col1.checkbox("Obrigatório", value=True)
            peso = col2.number_input("Peso (para a nota final)", min_value=0.0, value=1.0, step=0.5)
            evidencia_obrig = col3.checkbox("Exige foto")
            comentario_se_nc = st.checkbox("Exigir comentário quando a resposta for não conforme")

            resposta_critica = None
            usar_critica = False
            if tipo_chave == "sim_nao":
                opc = st.selectbox("Disparar não conformidade automaticamente quando a resposta for:",
                                    ["Não usar", "Sim", "Não"])
                if opc != "Não usar":
                    resposta_critica = (opc == "Sim")
                    usar_critica = True
            elif tipo_chave == "conforme_nao_conforme":
                opc = st.selectbox("Disparar não conformidade automaticamente quando a resposta for:",
                                    ["Não usar", "conforme", "nao_conforme"])
                if opc != "Não usar":
                    resposta_critica = opc
                    usar_critica = True
            else:
                st.caption(
                    "ℹ️ Valor crítico automático só está disponível para os tipos "
                    "'Sim / Não' e 'Conforme / Não conforme' (comparação exata)."
                )

            if st.form_submit_button("Criar Pergunta"):
                if not titulo.strip():
                    st.warning("Informe o texto da pergunta.")
                else:
                    corpo = {
                        "area_id": area["id"], "titulo": titulo.strip(),
                        "tipo_resposta_chave": tipo_chave, "obrigatorio": obrigatorio,
                        "peso": float(peso), "evidencia_obrigatoria": evidencia_obrig,
                        "comentario_obrigatorio_se_nao_conforme": comentario_se_nc,
                    }
                    if usar_critica:
                        corpo["resposta_critica"] = resposta_critica
                    r = api.post(f"/api/v1/checklists/{checklist_id}/itens", corpo,
                                 mostrar_sucesso="Pergunta criada!")
                    if r:
                        st.rerun()


def _form_nova_regra(checklist_id, todos_itens: dict):
    """todos_itens: {titulo_exibicao: item_id} de TODAS as perguntas do checklist."""
    if len(todos_itens) < 2:
        st.caption("Cadastre pelo menos 2 perguntas para poder criar uma regra condicional entre elas.")
        return
    with st.expander("➕ Nova Regra Condicional", expanded=False):
        with st.form("form_nova_regra"):
            alvo_nome = st.selectbox("Quando a condição for satisfeita, afeta a pergunta:", list(todos_itens.keys()),
                                      key="regra_alvo")
            efeito = st.selectbox("Efeito", list(TIPOS_EFEITO_LABEL.keys()),
                                   format_func=lambda k: TIPOS_EFEITO_LABEL[k], key="regra_efeito")
            st.markdown("**Condição:** a resposta da pergunta...")
            condicao_nome = st.selectbox("Pergunta de condição", list(todos_itens.keys()), key="regra_condicao")
            operador = st.selectbox("Operador", list(OPERADORES_LABEL.keys()),
                                     format_func=lambda k: OPERADORES_LABEL[k], key="regra_operador")
            valor_texto = st.text_input(
                "Valor de comparação (ex: false para 'Não', \"nao_conforme\", ou um número)",
                key="regra_valor",
            )
            if st.form_submit_button("Criar Regra"):
                if alvo_nome == condicao_nome:
                    st.warning("A pergunta alvo e a pergunta de condição não podem ser a mesma.")
                elif not valor_texto.strip():
                    st.warning("Informe o valor de comparação.")
                else:
                    valor = _interpretar_valor(valor_texto.strip())
                    r = api.post(f"/api/v1/checklists/{checklist_id}/regras", {
                        "item_alvo_id": todos_itens[alvo_nome],
                        "tipo_efeito": efeito,
                        "item_condicao_id": todos_itens[condicao_nome],
                        "operador_comparacao": operador,
                        "valor": valor,
                    }, mostrar_sucesso="Regra criada!")
                    if r:
                        st.rerun()


def _interpretar_valor(texto: str):
    """Converte o texto digitado no formulário de regra para o tipo JSON
    correto — true/false viram booleano, números viram número, o resto
    fica como string (removendo aspas se o usuário digitou 'assim')."""
    baixo = texto.lower()
    if baixo in ("true", "verdadeiro"):
        return True
    if baixo in ("false", "falso"):
        return False
    try:
        if "." in texto:
            return float(texto)
        return int(texto)
    except ValueError:
        return texto.strip('"').strip("'")


def _publicar(checklist_id):
    st.markdown("---")
    st.markdown("### 🚀 Publicar")
    st.caption(
        "Publicar congela a estrutura atual (áreas, perguntas e regras) numa versão "
        "imutável, liberando este checklist para ser usado em aplicações de campo."
    )
    if st.button("🚀 Publicar esta versão", type="primary", key=f"btn_publicar_{checklist_id}"):
        r = api.post(f"/api/v1/checklists/{checklist_id}/publicar", {}, mostrar_sucesso="Checklist publicado! 🎉")
        if r:
            st.rerun()


def renderizar_editor():
    checklist_id = _selecionar_ou_criar_checklist()
    if not checklist_id:
        st.info("Crie o primeiro checklist acima para começar.")
        return

    versao_rascunho = _gerenciar_versao(checklist_id)
    if not versao_rascunho:
        return  # sem rascunho editável — o botão de criar nova versão já foi mostrado

    areas = api.get(f"/api/v1/checklists/{checklist_id}/areas", mostrar_erro=False) or []
    _form_nova_area(checklist_id, ordem_sugerida=len(areas))

    if not areas:
        st.info("Crie ao menos uma área acima para começar a adicionar perguntas.")
        return

    todos_itens = {}  # "Área · Pergunta" -> item_id, usado no formulário de regras

    for area in areas:
        st.markdown(f"#### 📁 {area['nome']}")
        itens = api.get(f"/api/v1/checklists/{checklist_id}/itens",
                         params={"area_id": area["id"]}, mostrar_erro=False) or []

        if itens:
            for item in itens:
                tags = []
                if item["obrigatorio"]:
                    tags.append("obrigatório")
                if item["evidencia_obrigatoria"]:
                    tags.append("exige foto")
                sufixo = f" _({', '.join(tags)})_" if tags else ""
                st.markdown(f"　- {item['titulo']}{sufixo}")
                todos_itens[f"{area['nome']} · {item['titulo']}"] = item["id"]
        else:
            st.caption("Nenhuma pergunta cadastrada nesta área ainda.")

        _form_nova_pergunta(checklist_id, area)
        st.markdown("")

    st.markdown("---")
    st.markdown("### 🔀 Regras Condicionais")
    regras = api.get(f"/api/v1/checklists/{checklist_id}/regras", mostrar_erro=False) or []
    if regras:
        mapa_id_para_titulo = {v: k for k, v in todos_itens.items()}
        for r in regras:
            alvo = mapa_id_para_titulo.get(r["item_alvo_id"], r["item_alvo_id"])
            st.markdown(f"- **{TIPOS_EFEITO_LABEL.get(r['tipo_efeito'], r['tipo_efeito'])}** → {alvo}")
    else:
        st.caption("Nenhuma regra condicional cadastrada ainda.")

    _form_nova_regra(checklist_id, todos_itens)

    _publicar(checklist_id)
