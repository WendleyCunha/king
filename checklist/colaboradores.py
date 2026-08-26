"""
checklist/colaboradores.py
Aba "Colaboradores" — papéis de acesso (perfis) e usuários, incluindo o
vínculo que dá a cada usuário um papel + escopo (toda a organização, ou
restrito a uma unidade específica).

IMPORTANTE: criar um usuário sozinho (POST /usuarios) não dá acesso a nada —
é o vínculo (POST /usuarios/{id}/escopo) que liga um papel a ele. Por isso
esta tela deixa isso bem explícito: todo colaborador sem vínculo aparece com
um aviso.
"""
import streamlit as st
from . import api_client as api

# Agrupamento amigável das permissões existentes na API — usado tanto no
# formulário de novo papel quanto para exibir os modelos prontos.
PERMISSOES_DISPONIVEIS = {
    "Estrutura (unidades/setores)": ["unidade.visualizar", "unidade.gerenciar"],
    "Colaboradores": ["usuario.visualizar", "usuario.gerenciar"],
    "Checklists (editor)": ["checklist.visualizar", "checklist.criar", "checklist.publicar"],
    "Aplicações (execução em campo)": ["aplicacao.visualizar", "aplicacao.criar", "aplicacao.executar"],
    "Planos de Ação": ["plano_acao.visualizar", "plano_acao.criar", "plano_acao.gerenciar"],
    "Dashboard e Relatórios": ["dashboard.visualizar", "relatorio.exportar"],
}

# Papéis prontos, espelhando a tabela "6. Papéis de Usuário" do escopo original.
PERFIS_MODELO = {
    "Administrador (acesso total)": [p for grupo in PERMISSOES_DISPONIVEIS.values() for p in grupo],
    "Gestor de Setor": [
        "unidade.visualizar", "usuario.visualizar",
        "checklist.visualizar",
        "aplicacao.visualizar", "aplicacao.criar",
        "plano_acao.visualizar", "plano_acao.criar", "plano_acao.gerenciar",
        "dashboard.visualizar", "relatorio.exportar",
    ],
    "Aplicador (colaborador de campo)": [
        "checklist.visualizar",
        "aplicacao.visualizar", "aplicacao.criar", "aplicacao.executar",
    ],
}


def _aba_perfis():
    st.markdown("### 🏷️ Papéis de acesso")
    st.caption(
        "Um papel define o que um colaborador pode fazer. Comece por um dos modelos "
        "prontos (baseados no levantamento de requisitos) ou monte um personalizado."
    )

    with st.expander("➕ Novo Papel", expanded=False):
        modelo = st.selectbox(
            "Começar a partir de um modelo (opcional)",
            ["— Personalizado —"] + list(PERFIS_MODELO.keys()),
            key="modelo_perfil_select",
        )
        permissoes_marcadas = set(PERFIS_MODELO.get(modelo, []))

        with st.form("form_novo_perfil"):
            nome_sugerido = "" if modelo == "— Personalizado —" else modelo
            nome = st.text_input("Nome do papel", value=nome_sugerido)

            selecionadas = []
            for grupo, perms in PERMISSOES_DISPONIVEIS.items():
                st.markdown(f"**{grupo}**")
                cols = st.columns(len(perms))
                for col, p in zip(cols, perms):
                    rotulo = p.split(".")[-1].capitalize()
                    if col.checkbox(rotulo, value=(p in permissoes_marcadas), key=f"perm_{p}"):
                        selecionadas.append(p)

            if st.form_submit_button("Criar Papel"):
                if not nome.strip():
                    st.warning("Informe um nome para o papel.")
                elif not selecionadas:
                    st.warning("Selecione ao menos uma permissão.")
                else:
                    r = api.post("/api/v1/perfis", {"nome": nome.strip(), "permissoes": selecionadas},
                                 mostrar_sucesso=f"Papel '{nome}' criado!")
                    if r:
                        st.rerun()

    perfis = api.get("/api/v1/perfis") or []
    if not perfis:
        st.info("Nenhum papel cadastrado ainda.")
    for p in perfis:
        with st.expander(f"**{p['nome']}** · {len(p['permissoes'])} permissão(ões)"):
            st.write(", ".join(sorted(p["permissoes"])) or "_Nenhuma._")


def _aba_usuarios():
    st.markdown("### 👤 Colaboradores")

    with st.expander("➕ Novo Colaborador", expanded=False):
        with st.form("form_novo_colaborador"):
            nome = st.text_input("Nome completo")
            email = st.text_input("E-mail (usado como login)")
            senha = st.text_input("Senha provisória", type="password",
                                   help="Mínimo 8 caracteres. O colaborador pode trocar depois.")
            if st.form_submit_button("Criar"):
                if not (nome.strip() and email.strip() and senha):
                    st.warning("Preencha todos os campos.")
                elif len(senha) < 8:
                    st.warning("A senha precisa ter pelo menos 8 caracteres.")
                else:
                    r = api.post("/api/v1/usuarios", {
                        "nome": nome.strip(), "email": email.strip(), "senha": senha,
                    }, mostrar_sucesso=f"Colaborador '{nome}' criado! Vincule um papel a ele abaixo.")
                    if r:
                        st.rerun()

    usuarios = api.get("/api/v1/usuarios") or []
    if not usuarios:
        st.info("Nenhum colaborador cadastrado ainda.")
        return

    perfis = api.get("/api/v1/perfis", mostrar_erro=False) or []
    unidades = api.get("/api/v1/unidades", mostrar_erro=False) or []
    mapa_perfis = {p["nome"]: p["id"] for p in perfis}
    mapa_unidades = {u["nome"]: u["id"] for u in unidades}

    for u in usuarios:
        with st.expander(f"**{u['nome']}** · {u['email']} · {u['status']}"):
            vinculos = api.get(f"/api/v1/usuarios/{u['id']}/escopos", mostrar_erro=False) or []
            if vinculos:
                st.markdown("**Papéis vinculados:**")
                for v in vinculos:
                    nome_perfil = next((p["nome"] for p in perfis if p["id"] == v["perfil_id"]), "(papel removido)")
                    nome_unidade = next((un["nome"] for un in unidades if un["id"] == v["unidade_id"]), None)
                    escopo_txt = f"restrito a: {nome_unidade}" if nome_unidade else "toda a organização"
                    st.markdown(f"　- **{nome_perfil}** ({escopo_txt})")
            else:
                st.warning(
                    "⚠️ Sem nenhum papel vinculado — este colaborador não consegue "
                    "acessar nada até você vincular um papel abaixo."
                )

            st.markdown("---")
            st.markdown("**Vincular um papel**")
            if not mapa_perfis:
                st.caption("Cadastre um papel na aba 'Papéis de Acesso' primeiro.")
            else:
                col1, col2 = st.columns(2)
                perfil_nome = col1.selectbox("Papel", list(mapa_perfis.keys()), key=f"perfil_{u['id']}")
                unidade_nome = col2.selectbox(
                    "Restringir a uma unidade (opcional)",
                    ["— Toda a organização —"] + list(mapa_unidades.keys()),
                    key=f"unidade_{u['id']}",
                )
                if st.button("💾 Vincular papel", key=f"btn_vincular_{u['id']}"):
                    corpo = {"perfil_id": mapa_perfis[perfil_nome]}
                    if unidade_nome != "— Toda a organização —":
                        corpo["unidade_id"] = mapa_unidades[unidade_nome]
                    r = api.post(f"/api/v1/usuarios/{u['id']}/escopo", corpo, mostrar_sucesso="Papel vinculado!")
                    if r:
                        st.rerun()


def renderizar_colaboradores():
    aba_perfis, aba_usuarios = st.tabs(["🏷️ Papéis de Acesso", "👤 Colaboradores"])
    with aba_perfis:
        _aba_perfis()
    with aba_usuarios:
        _aba_usuarios()
