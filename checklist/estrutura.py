"""
checklist/estrutura.py
Aba "Estrutura" — organização, unidades e setores. É o primeiro cadastro que
precisa existir: colaboradores, checklists e aplicações todos dependem de
pelo menos uma unidade já existir.
"""
import streamlit as st
from . import api_client as api


def _garantir_organizacao():
    """
    Retorna o id da organização a usar, criando uma automaticamente na
    primeira vez (a King Star é uma única empresa — não faz sentido pedir
    pra escolher toda hora). Guarda em session_state pra não re-consultar
    a cada rerun da tela.
    """
    if "checklist_org_id" in st.session_state:
        return st.session_state.checklist_org_id

    orgs = api.get("/api/v1/organizacoes", mostrar_erro=False)
    if orgs:
        st.session_state.checklist_org_id = orgs[0]["id"]
        return st.session_state.checklist_org_id

    st.info("🏢 Nenhuma organização cadastrada ainda — crie a primeira (só precisa fazer isso uma vez).")
    with st.form("form_nova_organizacao"):
        nome_org = st.text_input("Nome da organização", value="KingStar Colchões")
        if st.form_submit_button("Criar organização"):
            novo = api.post("/api/v1/organizacoes", {"nome": nome_org.strip()},
                             mostrar_sucesso="Organização criada!")
            if novo:
                st.session_state.checklist_org_id = novo["id"]
                st.rerun()
    return None


def renderizar_estrutura():
    org_id = _garantir_organizacao()
    if not org_id:
        return  # ainda não tem organização — para aqui até criar

    aba_unidades, aba_setores = st.tabs(["🏬 Unidades", "🗂️ Setores"])

    # ═══════════════════════════════ UNIDADES ═══════════════════════════════
    with aba_unidades:
        with st.expander("➕ Nova Unidade", expanded=False):
            with st.form("form_nova_unidade"):
                nome = st.text_input("Nome da unidade (ex: CD Osasco, Loja Tatuapé)")
                tipo = st.selectbox("Tipo", ["loja", "cd", "deposito", "escritorio", "outro"])
                if st.form_submit_button("Criar"):
                    if not nome.strip():
                        st.warning("Informe um nome.")
                    else:
                        r = api.post("/api/v1/unidades", {
                            "organizacao_id": org_id, "nome": nome.strip(), "tipo": tipo,
                        }, mostrar_sucesso=f"Unidade '{nome}' criada!")
                        if r:
                            st.rerun()

        unidades = api.get("/api/v1/unidades") or []
        if not unidades:
            st.info("Nenhuma unidade cadastrada ainda.")
        for u in unidades:
            situacao = "🟢 ativa" if u["ativo"] else "🔴 inativa"
            st.markdown(f"- **{u['nome']}** · {u.get('tipo') or '—'} · {situacao}")

    # ═══════════════════════════════ SETORES ════════════════════════════════
    with aba_setores:
        unidades = api.get("/api/v1/unidades", mostrar_erro=False) or []
        if not unidades:
            st.info("Cadastre uma unidade primeiro, na aba ao lado.")
            return
        mapa_unidades = {u["nome"]: u["id"] for u in unidades}

        with st.expander("➕ Novo Setor", expanded=False):
            with st.form("form_novo_setor"):
                unidade_nome = st.selectbox("Unidade", list(mapa_unidades.keys()))
                nome = st.text_input("Nome do setor (ex: Expedição, Armazenagem, SAC)")
                if st.form_submit_button("Criar"):
                    if not nome.strip():
                        st.warning("Informe um nome.")
                    else:
                        r = api.post("/api/v1/setores", {
                            "unidade_id": mapa_unidades[unidade_nome], "nome": nome.strip(),
                        }, mostrar_sucesso=f"Setor '{nome}' criado!")
                        if r:
                            st.rerun()

        algum_setor = False
        for u in unidades:
            setores = api.get("/api/v1/setores", params={"unidade_id": u["id"]}, mostrar_erro=False) or []
            if setores:
                algum_setor = True
                st.markdown(f"**{u['nome']}**")
                for s in setores:
                    st.markdown(f"　- {s['nome']} {'🟢' if s['ativo'] else '🔴'}")
        if not algum_setor:
            st.info("Nenhum setor cadastrado ainda.")
