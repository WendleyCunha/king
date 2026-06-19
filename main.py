import streamlit as st
from database import verificar_login

st.set_page_config(page_title="Gestão KingStar", layout="wide")

# Inicialização de Sessão
if "user" not in st.session_state:
    st.session_state.user = None

# Tela de Login
if not st.session_state.user:
    st.title("🔐 Login KingStar")
    email = st.text_input("E-mail")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        user = verificar_login(email, senha)
        if user:
            st.session_state.user = user
            st.rerun()
        else:
            st.error("Credenciais inválidas")
else:
    # Área Logada
    user = st.session_state.user
    st.sidebar.write(f"Usuário: {user['nome']}")
    st.sidebar.write(f"Perfil: {user['role'].upper()}")
    
    if st.sidebar.button("Sair"):
        st.session_state.user = None
        st.rerun()

    # Roteamento por Permissões
    if user['role'] == "operacional":
        st.subheader("Painel Operacional (Apenas Visualização)")
        # ... carregar apenas visualização
        
    elif user['role'] == "supervisor":
        st.subheader("Painel de Gestão")
        # ... permitir editar e extrair relatórios

    elif user['role'] == "adm":
        st.subheader("Painel ADM")
        # ... acesso total + exclusão
        if st.button("Excluir Dados Críticos"):
            st.warning("Atenção: Ação irreversível")
