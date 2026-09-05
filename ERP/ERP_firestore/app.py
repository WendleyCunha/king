"""
ERP — aplicação principal (Firestore).

Requer em .streamlit/secrets.toml (ou nas secrets do Streamlit Cloud):

    textkey = '''{ ... conteúdo do JSON da service account ... }'''

Roda com:
    streamlit run app.py

Usuário padrão embutido (igual ao painel): login "admin", senha "admin123",
com acesso EDITAR em todas as abas. Crie os demais usuários pela própria
ABA DIRETORIA depois de logar.
"""
import streamlit as st
from auth import verificar_login, pode_visualizar, pode_editar

from views import (
    cadastro_view, produto_view, venda_view, agendar_view, encomendar_view,
    logistica_view, motorista_view, empresa_view, financeiro_view,
    fiscal_view, rh_view, diretoria_view,
)

st.set_page_config(page_title="ERP", layout="wide")

DEFINICAO_ABAS = [
    ("CADASTRO", "📇 Cadastro"),
    ("PRODUTO", "📦 Produto"),
    ("VENDA", "🛒 Venda"),
    ("AGENDAR", "📅 Agendar"),
    ("ENCOMENDAR", "🧾 Encomendar"),
    ("LOGISTICA", "🚚 Logística"),
    ("MOTORISTA", "🚛 Motorista"),
    ("EMPRESA", "🏢 Empresa"),
    ("FINANCEIRO", "💰 Financeiro"),
    ("FISCAL", "🧾 Fiscal"),
    ("RH", "👥 RH"),
    ("DIRETORIA", "🏛️ Diretoria"),
]


def tela_login():
    st.title("🔐 ERP — Login")
    with st.form("login"):
        login = st.text_input("Login")
        senha = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            usuario = verificar_login(login, senha)
            if usuario:
                st.session_state["usuario"] = usuario
                st.rerun()
            else:
                st.error("Login ou senha inválidos.")


def renderizar_aba(aba: str, usuario_login: str, editar: bool):
    if aba == "CADASTRO":
        cadastro_view.render(editar)
    elif aba == "PRODUTO":
        produto_view.render(editar, usuario_login)
    elif aba == "VENDA":
        venda_view.render(editar, usuario_login)
    elif aba == "AGENDAR":
        agendar_view.render(editar)
    elif aba == "ENCOMENDAR":
        encomendar_view.render()
    elif aba == "LOGISTICA":
        logistica_view.render(editar)
    elif aba == "MOTORISTA":
        motorista_view.render(editar)
    elif aba == "EMPRESA":
        empresa_view.render(editar)
    elif aba == "FINANCEIRO":
        financeiro_view.render()
    elif aba == "FISCAL":
        fiscal_view.render()
    elif aba == "RH":
        rh_view.render(editar)
    elif aba == "DIRETORIA":
        diretoria_view.render(editar, usuario_login)


def app_principal():
    usuario = st.session_state["usuario"]
    usuario_login = usuario["usuario"]

    with st.sidebar:
        st.write(f"👤 **{usuario['nome']}**")
        if st.button("Sair"):
            st.session_state.pop("usuario", None)
            st.rerun()

    abas_visiveis = [(c, r) for c, r in DEFINICAO_ABAS if pode_visualizar(usuario, c)]
    if not abas_visiveis:
        st.warning("Seu usuário não tem acesso a nenhuma aba. Fale com a DIRETORIA.")
        return

    st.title("ERP")
    tabs = st.tabs([rotulo for _, rotulo in abas_visiveis])
    for tab, (codigo, _rotulo) in zip(tabs, abas_visiveis):
        with tab:
            renderizar_aba(codigo, usuario_login, pode_editar(usuario, codigo))


def main():
    if "usuario" not in st.session_state:
        tela_login()
    else:
        app_principal()


if __name__ == "__main__":
    main()
