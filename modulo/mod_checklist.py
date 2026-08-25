"""
mod_checklist.py
Módulo do Painel que consome a API própria de Checklist (FastAPI + Postgres,
hospedada separadamente no Render — ver checklist_api/). Diferente dos
outros módulos (Rastreio, Tickets, Cartas), que leem direto do Firestore,
este módulo fala com a API por HTTP.

Autenticação: conta de serviço fixa (ver bootstrap_service_account.py).
O login do Painel (Firestore) e o login da API de Checklist (Postgres/JWT)
são sistemas independentes — o módulo loga sozinho com essa conta de
serviço, sem pedir usuário/senha de novo pra quem já está no Painel.

Secrets necessários (Streamlit → Settings → Secrets):
    CHECKLIST_API_URL    = "https://kingstar-checklist-api.onrender.com"
    CHECKLIST_API_EMAIL  = "o e-mail criado pelo bootstrap_service_account.py"
    CHECKLIST_API_SENHA  = "a senha criada pelo bootstrap_service_account.py"

O token JWT fica cacheado em st.session_state pela duração da sessão do
navegador — não relogamos a cada rerun. Se uma chamada voltar 401 (token
expirado), o módulo tenta logar de novo automaticamente, uma vez, antes de
desistir e mostrar erro.
"""
import streamlit as st
import requests
from datetime import datetime

_TIMEOUT = 10  # segundos — a API está no plano Free do Render, que "dorme"
               # após inatividade; a primeira chamada depois de um tempo
               # pode demorar até ~50s pra acordar. Timeout maior só nessa
               # primeira chamada seria ideal, mas mantemos simples por ora.


def _config_api():
    """Lê a config da API dos Secrets. Retorna (url, email, senha) ou
    (None, None, None) se algum estiver faltando — quem chamar decide
    o que mostrar na tela nesse caso."""
    try:
        url   = st.secrets["CHECKLIST_API_URL"].rstrip("/")
        email = st.secrets["CHECKLIST_API_EMAIL"]
        senha = st.secrets["CHECKLIST_API_SENHA"]
        return url, email, senha
    except Exception:
        return None, None, None


def _login_api(url: str, email: str, senha: str):
    """Faz login na API de Checklist e retorna o access_token, ou None se falhar."""
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


def _garantir_token() -> bool:
    """
    Garante que st.session_state.checklist_token está preenchido e válido.
    Retorna True se conseguiu (ou já tinha) um token, False se não deu pra
    logar (config faltando ou credenciais erradas) — nesse caso já mostra
    o erro na tela, quem chamou só precisa parar de renderizar o resto.
    """
    url, email, senha = _config_api()
    if not url or not email or not senha:
        st.error(
            "⚠️ O módulo de Checklist não está configurado. Faltam os Secrets "
            "`CHECKLIST_API_URL`, `CHECKLIST_API_EMAIL` e/ou `CHECKLIST_API_SENHA`."
        )
        return False

    if "checklist_token" not in st.session_state:
        token = _login_api(url, email, senha)
        if not token:
            st.error(
                "🚫 Não foi possível conectar à API de Checklist agora "
                "(credenciais da conta de serviço incorretas, ou a API está fora do ar / "
                "ainda 'acordando' — planos Free do Render dormem após inatividade, "
                "tente de novo em alguns segundos)."
            )
            return False
        st.session_state.checklist_token = token

    return True


def _chamar_api(metodo: str, caminho: str, **kwargs):
    """
    Faz uma chamada autenticada à API de Checklist. `metodo` é 'get', 'post',
    'patch' etc. `caminho` é relativo, ex: '/api/v1/checklists'.

    Se a API responder 401 (token expirado/inválido), tenta logar de novo
    UMA vez e repete a chamada — sem loop infinito de retry.

    Retorna o objeto Response do requests, ou None se a chamada falhou por
    completo (rede fora do ar etc.) — já mostra o erro na tela nesse caso.
    """
    url, email, senha = _config_api()
    if not url:
        return None

    def _fazer_chamada():
        func = getattr(requests, metodo)
        return func(
            f"{url}{caminho}",
            headers={"Authorization": f"Bearer {st.session_state.checklist_token}"},
            timeout=_TIMEOUT,
            **kwargs,
        )

    try:
        resp = _fazer_chamada()
    except Exception as e:
        st.error("🚫 Não foi possível falar com a API de Checklist agora.")
        st.caption(f"Detalhe técnico: {type(e).__name__}: {e}")
        return None

    if resp.status_code == 401:
        # Token expirado (ou revogado) — tenta logar de novo, uma vez só.
        novo_token = _login_api(url, email, senha)
        if not novo_token:
            st.error("🚫 A sessão com a API de Checklist expirou e não foi possível renovar.")
            return None
        st.session_state.checklist_token = novo_token
        try:
            resp = _fazer_chamada()
        except Exception as e:
            st.error("🚫 Não foi possível falar com a API de Checklist agora.")
            st.caption(f"Detalhe técnico: {type(e).__name__}: {e}")
            return None

    return resp


def renderizar_checklist(papel, user=None):
    """Ponto de entrada do módulo — chamado pelo roteamento do main.py,
    já dentro de _executar_modulo_protegido (blindado contra erro)."""

    if not _garantir_token():
        return

    aba_checklists, aba_aplicacoes, aba_planos, aba_dashboard = st.tabs(
        ["📋 Checklists", "▶️ Aplicações", "🛠️ Planos de Ação", "📊 Dashboard"]
    )

    # ═══════════════════════════════════════════════════════════
    # ABA CHECKLISTS — listar + criar
    # ═══════════════════════════════════════════════════════════
    with aba_checklists:
        st.markdown("### 📋 Checklists cadastrados")

        with st.expander("➕ Novo Checklist", expanded=False):
            with st.form("form_novo_checklist"):
                nome = st.text_input("Nome do checklist")
                descricao = st.text_area("Descrição (opcional)", height=80)
                if st.form_submit_button("Criar"):
                    if not nome.strip():
                        st.warning("Informe um nome para o checklist.")
                    else:
                        resp = _chamar_api(
                            "post", "/api/v1/checklists",
                            json={"nome": nome.strip(), "descricao": descricao.strip() or None},
                        )
                        if resp is not None:
                            if resp.status_code in (200, 201):
                                st.success(f"Checklist '{nome}' criado!")
                                st.rerun()
                            else:
                                st.error(f"Não foi possível criar o checklist (HTTP {resp.status_code}).")
                                st.code(resp.text, language="json")

        resp = _chamar_api("get", "/api/v1/checklists")
        if resp is not None:
            if resp.status_code == 200:
                checklists = resp.json()
                if not checklists:
                    st.info("Nenhum checklist cadastrado ainda.")
                else:
                    for c in checklists:
                        with st.expander(f"**{c.get('nome','—')}** · `{c.get('id','')[:8]}...`"):
                            st.write(c.get("descricao") or "_Sem descrição._")
                            st.caption(f"Criado em: {c.get('criado_em','—')}")
            else:
                st.error(f"Não foi possível carregar os checklists (HTTP {resp.status_code}).")

    # ═══════════════════════════════════════════════════════════
    # ABA APLICAÇÕES — execuções de checklist em andamento/concluídas
    # ═══════════════════════════════════════════════════════════
    with aba_aplicacoes:
        st.markdown("### ▶️ Aplicações")
        st.caption(
            "Uma 'aplicação' é uma execução de um checklist publicado — normalmente "
            "iniciada pelo app de campo, não por aqui. Esta aba é só consulta."
        )
        aplicacao_id = st.text_input("ID da aplicação (cole o UUID para consultar)")
        if st.button("🔎 Consultar aplicação"):
            if not aplicacao_id.strip():
                st.warning("Informe o ID da aplicação.")
            else:
                resp = _chamar_api("get", f"/api/v1/aplicacoes/{aplicacao_id.strip()}")
                if resp is not None:
                    if resp.status_code == 200:
                        st.json(resp.json())
                    elif resp.status_code == 404:
                        st.warning("Aplicação não encontrada.")
                    else:
                        st.error(f"Erro ao consultar (HTTP {resp.status_code}).")

    # ═══════════════════════════════════════════════════════════
    # ABA PLANOS DE AÇÃO
    # ═══════════════════════════════════════════════════════════
    with aba_planos:
        st.markdown("### 🛠️ Planos de Ação")
        resp = _chamar_api("get", "/api/v1/planos-acao")
        if resp is not None:
            if resp.status_code == 200:
                planos = resp.json()
                if not planos:
                    st.info("Nenhum plano de ação registrado ainda.")
                else:
                    for p in planos:
                        status = p.get("status", "—")
                        with st.expander(f"**{p.get('titulo','—')}** · {status}"):
                            st.write(p.get("descricao") or "_Sem descrição._")
                            st.caption(f"Criado em: {p.get('criado_em','—')}")
                            novo_status = st.selectbox(
                                "Status", ["pendente", "em_andamento", "concluido", "cancelado"],
                                index=["pendente","em_andamento","concluido","cancelado"].index(status)
                                      if status in ("pendente","em_andamento","concluido","cancelado") else 0,
                                key=f"status_plano_{p.get('id')}",
                            )
                            if st.button("💾 Atualizar status", key=f"btn_status_plano_{p.get('id')}"):
                                r2 = _chamar_api(
                                    "patch", f"/api/v1/planos-acao/{p.get('id')}/status",
                                    json={"status": novo_status},
                                )
                                if r2 is not None and r2.status_code == 200:
                                    st.success("Status atualizado!")
                                    st.rerun()
                                elif r2 is not None:
                                    st.error(f"Não foi possível atualizar (HTTP {r2.status_code}).")
            else:
                st.error(f"Não foi possível carregar os planos de ação (HTTP {resp.status_code}).")

    # ═══════════════════════════════════════════════════════════
    # ABA DASHBOARD — resumo dos números
    # ═══════════════════════════════════════════════════════════
    with aba_dashboard:
        st.markdown("### 📊 Dashboard")
        c1, c2, c3 = st.columns(3)

        r_apl = _chamar_api("get", "/api/v1/dashboards/aplicacoes")
        if r_apl is not None and r_apl.status_code == 200:
            d = r_apl.json()
            c1.metric("Aplicações", d.get("total", 0))

        r_nc = _chamar_api("get", "/api/v1/dashboards/nao-conformidades")
        if r_nc is not None and r_nc.status_code == 200:
            d = r_nc.json()
            c2.metric("Não Conformidades", d.get("total", 0))

        r_pa = _chamar_api("get", "/api/v1/dashboards/planos-acao")
        if r_pa is not None and r_pa.status_code == 200:
            d = r_pa.json()
            c3.metric("Planos de Ação", d.get("total", 0))

        st.markdown("---")
        if st.button("📥 Exportar relatório de aplicações (CSV)"):
            resp = _chamar_api("get", "/api/v1/relatorios/aplicacoes.csv")
            if resp is not None and resp.status_code == 200:
                st.download_button(
                    "Baixar CSV",
                    data=resp.content,
                    file_name=f"aplicacoes_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                )
            elif resp is not None:
                st.error(f"Não foi possível gerar o relatório (HTTP {resp.status_code}).")
