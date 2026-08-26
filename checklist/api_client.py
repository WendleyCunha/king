"""
checklist/api_client.py
Camada HTTP compartilhada por todas as telas do módulo de Checklist —
autenticação (conta de serviço fixa) e chamadas autenticadas à API própria
(FastAPI + Postgres, hospedada separadamente no Render — ver checklist_api/).

Secrets necessários (Streamlit → Settings → Secrets):
    CHECKLIST_API_URL    = "https://kingstar-checklist-api.onrender.com"
    CHECKLIST_API_EMAIL  = "o e-mail criado pelo bootstrap_service_account.py"
    CHECKLIST_API_SENHA  = "a senha criada pelo bootstrap_service_account.py"

O token JWT fica cacheado em st.session_state pela duração da sessão do
navegador. Se uma chamada voltar 401 (token expirado/revogado), tentamos
logar de novo automaticamente, uma vez, antes de desistir e mostrar erro.
"""
import streamlit as st
import requests

_TIMEOUT = 15  # segundos — a API está no plano Free do Render, que "dorme"
               # após inatividade; a primeira chamada depois de um tempo
               # pode demorar até ~50s pra acordar.


def config_api():
    """Lê a config da API dos Secrets. Retorna (url, email, senha) ou
    (None, None, None) se algum estiver faltando."""
    try:
        url = st.secrets["CHECKLIST_API_URL"].rstrip("/")
        email = st.secrets["CHECKLIST_API_EMAIL"]
        senha = st.secrets["CHECKLIST_API_SENHA"]
        return url, email, senha
    except Exception:
        return None, None, None


def _login(url: str, email: str, senha: str):
    try:
        resp = requests.post(
            f"{url}/api/v1/auth/login",
            data={"username": email, "password": senha},  # OAuth2PasswordRequestForm = form-encoded
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        return None
    except Exception:
        return None


def garantir_token() -> bool:
    """Garante que st.session_state.checklist_token está preenchido.
    Retorna False (já mostrando o erro na tela) se não conseguir."""
    url, email, senha = config_api()
    if not url or not email or not senha:
        st.error(
            "⚠️ O módulo de Checklist não está configurado. Faltam os Secrets "
            "`CHECKLIST_API_URL`, `CHECKLIST_API_EMAIL` e/ou `CHECKLIST_API_SENHA`."
        )
        return False

    if "checklist_token" not in st.session_state:
        token = _login(url, email, senha)
        if not token:
            st.error(
                "🚫 Não foi possível conectar à API de Checklist agora "
                "(credenciais incorretas, ou a API está 'acordando' — planos Free "
                "do Render dormem após inatividade, tente de novo em alguns segundos)."
            )
            return False
        st.session_state.checklist_token = token

    return True


def chamar_api(metodo: str, caminho: str, **kwargs):
    """Chamada HTTP crua e autenticada. Retorna o Response, ou None se a
    chamada falhou por completo (já mostra o erro nesse caso). Usada
    diretamente (em vez de get/post/patch) quando a resposta não é JSON,
    como no download de CSV."""
    if not garantir_token():
        return None
    url, email, senha = config_api()
    if not url:
        return None

    def _fazer():
        func = getattr(requests, metodo)
        return func(
            f"{url}{caminho}",
            headers={"Authorization": f"Bearer {st.session_state.checklist_token}"},
            timeout=_TIMEOUT,
            **kwargs,
        )

    try:
        resp = _fazer()
    except Exception as e:
        st.error("🚫 Não foi possível falar com a API de Checklist agora.")
        st.caption(f"Detalhe técnico: {type(e).__name__}: {e}")
        return None

    if resp.status_code == 401:
        novo_token = _login(url, email, senha)
        if not novo_token:
            st.error("🚫 A sessão com a API de Checklist expirou e não foi possível renovar.")
            return None
        st.session_state.checklist_token = novo_token
        try:
            resp = _fazer()
        except Exception as e:
            st.error("🚫 Não foi possível falar com a API de Checklist agora.")
            st.caption(f"Detalhe técnico: {type(e).__name__}: {e}")
            return None

    return resp


def _mostrar_detalhe_erro(resp):
    """Mostra o corpo do erro de forma legível — string simples como legenda,
    lista/dict (422 de validação, ou o detail estruturado de 'itens_faltando')
    como JSON expansível."""
    try:
        detalhe = resp.json().get("detail")
    except Exception:
        return
    if detalhe is None:
        return
    if isinstance(detalhe, (list, dict)):
        st.json(detalhe)
    else:
        st.caption(str(detalhe))


def get(caminho: str, params: dict = None, mostrar_erro: bool = True):
    """GET que já retorna o JSON parseado, ou None em qualquer falha."""
    resp = chamar_api("get", caminho, params=params)
    if resp is None:
        return None
    if resp.status_code == 200:
        return resp.json()
    if mostrar_erro:
        st.error(f"Não foi possível carregar os dados (HTTP {resp.status_code}).")
        _mostrar_detalhe_erro(resp)
    return None


def post(caminho: str, corpo: dict, mostrar_sucesso: str = None):
    """POST que já retorna o JSON parseado em caso de sucesso (200/201),
    ou None em qualquer falha (já mostra o erro)."""
    resp = chamar_api("post", caminho, json=corpo)
    if resp is None:
        return None
    if resp.status_code in (200, 201):
        if mostrar_sucesso:
            st.success(mostrar_sucesso)
        return resp.json()
    st.error(f"Não foi possível concluir a ação (HTTP {resp.status_code}).")
    _mostrar_detalhe_erro(resp)
    return None


def patch(caminho: str, corpo: dict, mostrar_sucesso: str = None):
    """PATCH — mesmo contrato do post()."""
    resp = chamar_api("patch", caminho, json=corpo)
    if resp is None:
        return None
    if resp.status_code == 200:
        if mostrar_sucesso:
            st.success(mostrar_sucesso)
        return resp.json()
    st.error(f"Não foi possível concluir a ação (HTTP {resp.status_code}).")
    _mostrar_detalhe_erro(resp)
    return None
