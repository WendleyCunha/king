"""
KingStar — Módulo de Tickets
Fase 1: Lê do Firestore (espelhado da Zendesk via sync)
Fase 2: Abre tickets direto no Firestore
Fase 3: Importa histórico Zendesk → Firestore e desliga Zendesk
"""
import streamlit as st
import pandas as pd
import time
from datetime import datetime, timezone, timedelta

try:
    import sys, os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from database import get_db
except:
    pass

BRT = timezone(timedelta(hours=-3))

def agora_brt_str():
    return datetime.now(BRT).strftime("%Y-%m-%d %H:%M:%S")

# ── Coleção Firestore ──────────────────────────────────────────────
COLECAO = "tickets"

CATEGORIAS = {
    "Garantia":      ["Troca de produto","Defeito de fabricação","Prazo vencido","Outros"],
    "Logística":     ["Atraso na entrega","Produto errado","Avaria no transporte","Outros"],
    "Financeiro":    ["Divergência de valor","Reembolso","Cobrança indevida","Outros"],
    "Pós-venda":     ["Dúvida sobre produto","Montagem","Limpeza e conservação","Outros"],
    "Administrativo":["Documentação","Contrato","RH","Outros"],
    "TI":            ["Sistema fora do ar","Erro no sistema","Acesso bloqueado","Outros"],
}

STATUS_LABEL = {
    "aberto":      ("🟡 Aberto",      "#FEF9C3","#854D0E"),
    "em_andamento":("🔵 Em Andamento","#EFF6FF","#1D5FAE"),
    "aguardando":  ("🟠 Aguardando",  "#FFF7ED","#9A3412"),
    "resolvido":   ("🟢 Resolvido",   "#DCFCE7","#15803D"),
    "cancelado":   ("⚫ Cancelado",   "#F1F5F9","#475569"),
}

PRIO_LABEL = {
    "urgente": ("🔴 Urgente","#FEE2E2","#991B1B"),
    "alta":    ("🟠 Alta",   "#FFF7ED","#9A3412"),
    "normal":  ("🟡 Normal", "#FEF9C3","#854D0E"),
    "baixa":   ("⚪ Baixa",  "#F1F5F9","#475569"),
}

def pill(texto, bg, cor):
    return f'<span style="background:{bg};color:{cor};padding:3px 10px;border-radius:12px;font-size:0.75rem;font-weight:700;">{texto}</span>'

# ── CRUD Firestore ────────────────────────────────────────────────
def criar_ticket(dados: dict) -> str:
    db  = get_db()
    ref = db.collection(COLECAO).document()
    dados["id"]         = ref.id
    dados["criado_em"]  = agora_brt_str()
    dados["atualizado_em"] = agora_brt_str()
    dados["status"]     = "aberto"
    dados["origem"]     = "interno"
    dados["comentarios"]= []
    ref.set(dados)
    return ref.id

def listar_tickets(filtro_status=None, filtro_categoria=None) -> list:
    db   = get_db()
    ref  = db.collection(COLECAO)
    docs = ref.stream()
    tickets = [d.to_dict() for d in docs]
    if filtro_status and filtro_status != "Todos":
        tickets = [t for t in tickets if t.get("status") == filtro_status]
    if filtro_categoria and filtro_categoria != "Todas":
        tickets = [t for t in tickets if t.get("categoria") == filtro_categoria]
    return sorted(tickets, key=lambda x: x.get("criado_em",""), reverse=True)

def atualizar_ticket(ticket_id: str, dados: dict):
    dados["atualizado_em"] = agora_brt_str()
    get_db().collection(COLECAO).document(ticket_id).update(dados)

def adicionar_comentario(ticket_id: str, autor: str, texto: str):
    from google.cloud.firestore import ArrayUnion
    get_db().collection(COLECAO).document(ticket_id).update({
        "comentarios": ArrayUnion([{
            "autor": autor, "texto": texto, "data": agora_brt_str()
        }]),
        "atualizado_em": agora_brt_str(),
    })

def obter_ticket(ticket_id: str) -> dict:
    doc = get_db().collection(COLECAO).document(ticket_id).get()
    return doc.to_dict() if doc.exists else {}

# ── SYNC ZENDESK → FIRESTORE ──────────────────────────────────────
def sync_zendesk_para_firestore(subdomain, email, token, view_id) -> tuple:
    """Busca tickets da view Zendesk e espelha no Firestore. Retorna (ok, qtd, msg)."""
    import requests as req
    url  = f"https://{subdomain}.zendesk.com/api/v2/views/{view_id}/tickets.json?per_page=100"
    auth = (f"{email}/token", token)
    try:
        r = req.get(url, auth=auth, timeout=15)
        if r.status_code != 200:
            return False, 0, f"Zendesk retornou {r.status_code}"
        tickets = r.json().get("tickets", [])
        db = get_db()
        batch = db.batch()
        for t in tickets:
            doc_id = f"zendesk_{t['id']}"
            ref    = db.collection(COLECAO).document(doc_id)
            batch.set(ref, {
                "id":           doc_id,
                "id_zendesk":   t["id"],
                "assunto":      t.get("subject",""),
                "descricao":    t.get("description",""),
                "status":       _mapear_status_zendesk(t.get("status","open")),
                "prioridade":   _mapear_prio_zendesk(t.get("priority","normal")),
                "categoria":    "Zendesk/TERMOS",
                "solicitante":  t.get("requester_id",""),
                "criado_em":    t.get("created_at","")[:19].replace("T"," "),
                "atualizado_em":t.get("updated_at","")[:19].replace("T"," "),
                "origem":       "zendesk",
                "comentarios":  [],
            }, merge=True)
        batch.commit()
        return True, len(tickets), f"{len(tickets)} tickets sincronizados"
    except Exception as e:
        return False, 0, str(e)

def _mapear_status_zendesk(s):
    return {"new":"aberto","open":"em_andamento","pending":"aguardando",
            "hold":"aguardando","solved":"resolvido","closed":"resolvido"}.get(s,"aberto")

def _mapear_prio_zendesk(p):
    return {"urgent":"urgente","high":"alta","normal":"normal","low":"baixa"}.get(p,"normal")

# ── IMPORTAÇÃO HISTÓRICA ──────────────────────────────────────────
def importar_historico_zendesk(subdomain, email, token) -> tuple:
    """Importa TODOS os tickets da Zendesk (paginado). Fase 3."""
    import requests as req
    url  = f"https://{subdomain}.zendesk.com/api/v2/tickets.json?per_page=100&sort_by=created_at"
    auth = (f"{email}/token", token)
    total = 0
    try:
        while url:
            r = req.get(url, auth=auth, timeout=30)
            if r.status_code != 200: break
            data    = r.json()
            tickets = data.get("tickets", [])
            db      = get_db()
            batch   = db.batch()
            for t in tickets:
                doc_id = f"zendesk_{t['id']}"
                ref    = db.collection(COLECAO).document(doc_id)
                batch.set(ref, {
                    "id":         doc_id,
                    "id_zendesk": t["id"],
                    "assunto":    t.get("subject",""),
                    "status":     _mapear_status_zendesk(t.get("status","open")),
                    "prioridade": _mapear_prio_zendesk(t.get("priority","normal")),
                    "categoria":  "Zendesk/Histórico",
                    "criado_em":  t.get("created_at","")[:19].replace("T"," "),
                    "atualizado_em": t.get("updated_at","")[:19].replace("T"," "),
                    "origem":     "zendesk_historico",
                    "comentarios":[],
                }, merge=True)
            batch.commit()
            total += len(tickets)
            url = data.get("next_page")
        return True, total, f"{total} tickets importados"
    except Exception as e:
        return False, total, str(e)

# ── RENDERIZAÇÃO PRINCIPAL ────────────────────────────────────────
def renderizar_tickets(papel: str, user: dict = None):
    if user is None: user = {"role": papel, "nome": "Usuário", "usuario": "user"}

    # ── KPIs rápidos ─────────────────────────────────────────────
    todos = listar_tickets()
    total   = len(todos)
    abertos = sum(1 for t in todos if t.get("status") == "aberto")
    em_and  = sum(1 for t in todos if t.get("status") == "em_andamento")
    urgentes= sum(1 for t in todos if t.get("prioridade") == "urgente")
    resolvidos = sum(1 for t in todos if t.get("status") == "resolvido")

    k1,k2,k3,k4,k5 = st.columns(5)
    k1.markdown(f'<div class="kpi-card gold"><div class="kpi-label">🎫 Total</div><div class="kpi-value">{total}</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card gold"><div class="kpi-label">🟡 Abertos</div><div class="kpi-value">{abertos}</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card blue"><div class="kpi-label">🔵 Em Andamento</div><div class="kpi-value">{em_and}</div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="kpi-card red"><div class="kpi-label">🔴 Urgentes</div><div class="kpi-value">{urgentes}</div></div>', unsafe_allow_html=True)
    k5.markdown(f'<div class="kpi-card green"><div class="kpi-label">🟢 Resolvidos</div><div class="kpi-value">{resolvidos}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    abas = st.tabs(["📋 Fila", "➕ Novo Ticket", "🔍 Detalhe", "🔄 Sync Zendesk"])

    # ══ ABA FILA ════════════════════════════════════════════════
    with abas[0]:
        fc1, fc2, fc3 = st.columns([2, 1.5, 1.5])
        with fc1:
            busca = st.text_input("🔍 Buscar", placeholder="Assunto, solicitante, ID...", label_visibility="collapsed", key="tk_busca")
        with fc2:
            f_status = st.selectbox("Status", ["Todos","aberto","em_andamento","aguardando","resolvido","cancelado"], label_visibility="collapsed", key="tk_fstatus")
        with fc3:
            f_cat = st.selectbox("Categoria", ["Todas"] + list(CATEGORIAS.keys()) + ["Zendesk/TERMOS"], label_visibility="collapsed", key="tk_fcat")

        tickets = listar_tickets(
            filtro_status=f_status if f_status != "Todos" else None,
            filtro_categoria=f_cat if f_cat != "Todas" else None
        )
        if busca:
            b = busca.lower()
            tickets = [t for t in tickets if
                b in str(t.get("assunto","")).lower() or
                b in str(t.get("solicitante_nome","")).lower() or
                b in str(t.get("id","")).lower() or
                b in str(t.get("id_zendesk","")).lower()
            ]

        if not tickets:
            st.info("Nenhum ticket encontrado.")
        else:
            for t in tickets:
                tid    = t.get("id","")
                sv, sbg, sc = STATUS_LABEL.get(t.get("status","aberto"), ("—","#fff","#000"))
                pv, pbg, pc = PRIO_LABEL.get(t.get("prioridade","normal"), ("—","#fff","#000"))
                origem_icon = "🔗" if t.get("origem","") == "zendesk" else "🏠"
                with st.expander(
                    f"{origem_icon} **#{t.get('id_zendesk', tid[:8])}** — {t.get('assunto','Sem título')[:60]}",
                    expanded=False
                ):
                    cc1, cc2, cc3, cc4 = st.columns([2,1.5,1.5,1])
                    cc1.markdown(f"**Categoria:** {t.get('categoria','—')}")
                    cc2.markdown(pill(sv,sbg,sc), unsafe_allow_html=True)
                    cc3.markdown(pill(pv,pbg,pc), unsafe_allow_html=True)
                    cc4.markdown(f"**{t.get('criado_em','')[:10]}**")

                    if t.get("descricao"):
                        st.markdown(f"> {t.get('descricao','')[:200]}{'...' if len(t.get('descricao',''))>200 else ''}")

                    # Ações — só supervisor/adm
                    if papel in ("supervisor","adm"):
                        ac1, ac2, ac3 = st.columns(3)
                        novo_status = ac1.selectbox(
                            "Mudar status", list(STATUS_LABEL.keys()),
                            index=list(STATUS_LABEL.keys()).index(t.get("status","aberto")),
                            key=f"st_{tid}"
                        )
                        nova_prio = ac2.selectbox(
                            "Prioridade", list(PRIO_LABEL.keys()),
                            index=list(PRIO_LABEL.keys()).index(t.get("prioridade","normal")),
                            key=f"pr_{tid}"
                        )
                        if ac3.button("💾 Salvar", key=f"sv_{tid}", type="primary"):
                            atualizar_ticket(tid, {"status": novo_status, "prioridade": nova_prio})
                            st.success("Atualizado!"); time.sleep(.5); st.rerun()

                    # Comentários
                    comentarios = t.get("comentarios", [])
                    if comentarios:
                        st.markdown("**💬 Histórico:**")
                        for c in comentarios[-3:]:
                            st.markdown(
                                f'<div style="background:#f8f9fa;border-left:3px solid #C9A84C;'
                                f'padding:8px 12px;border-radius:6px;margin:4px 0;font-size:0.82rem;">'
                                f'<b>{c.get("autor","")}</b> · {c.get("data","")[:16]}<br>{c.get("texto","")}'
                                f'</div>', unsafe_allow_html=True)

                    novo_com = st.text_input("Adicionar comentário", key=f"com_{tid}", placeholder="Digite e pressione Enter...")
                    if novo_com:
                        adicionar_comentario(tid, user.get("nome",""), novo_com)
                        st.success("Comentário adicionado!"); time.sleep(.3); st.rerun()

    # ══ ABA NOVO TICKET ═════════════════════════════════════════
    with abas[1]:
        st.markdown("### ➕ Abrir Novo Chamado")
        with st.form("form_novo_ticket", clear_on_submit=True):
            nc1, nc2 = st.columns([3, 1])
            assunto  = nc1.text_input("Assunto *", placeholder="Descreva o problema resumidamente")
            prioridade = nc2.selectbox("Prioridade", ["normal","alta","urgente","baixa"])

            categoria = st.selectbox("Categoria", list(CATEGORIAS.keys()))
            subcategoria = st.selectbox("Subcategoria", CATEGORIAS.get(categoria, ["Outros"]))

            descricao = st.text_area("Descrição *", height=140, placeholder="Descreva em detalhes...")

            nd1, nd2 = st.columns(2)
            solicitante_nome  = nd1.text_input("Nome do solicitante", value=user.get("nome",""))
            solicitante_email = nd2.text_input("E-mail", placeholder="email@kingstar.com.br")

            atribuir_para = st.text_input("Atribuir para (opcional)", placeholder="Nome do responsável")

            if st.form_submit_button("🚀 Abrir Chamado", type="primary", use_container_width=True):
                if not assunto.strip() or not descricao.strip():
                    st.error("Preencha Assunto e Descrição.")
                else:
                    novo_id = criar_ticket({
                        "assunto":          assunto.strip(),
                        "descricao":        descricao.strip(),
                        "categoria":        categoria,
                        "subcategoria":     subcategoria,
                        "prioridade":       prioridade,
                        "solicitante_nome": solicitante_nome,
                        "solicitante_email":solicitante_email,
                        "atribuido_para":   atribuir_para,
                        "aberto_por":       user.get("usuario",""),
                    })
                    st.success(f"✅ Chamado **#{novo_id[:8]}** aberto com sucesso!")
                    st.balloons()

    # ══ ABA DETALHE ═════════════════════════════════════════════
    with abas[2]:
        st.markdown("### 🔍 Buscar Ticket por ID")
        tid_busca = st.text_input("ID do ticket (Firestore ou Zendesk)", key="tk_detail_id")
        if tid_busca:
            t = obter_ticket(tid_busca) or obter_ticket(f"zendesk_{tid_busca}")
            if t:
                sv, sbg, sc = STATUS_LABEL.get(t.get("status","aberto"), ("—","#fff","#000"))
                pv, pbg, pc = PRIO_LABEL.get(t.get("prioridade","normal"), ("—","#fff","#000"))
                st.markdown(f"""
                <div style="background:#fff;border:1px solid #e2e8f0;border-left:6px solid #C9A84C;
                            border-radius:10px;padding:16px;margin-bottom:12px;">
                    <h3 style="margin:0;color:#2c3e50;">{t.get('assunto','—')}</h3>
                    <p style="color:#64778d;font-size:0.82rem;margin:6px 0;">
                        {pill(sv,sbg,sc)} {pill(pv,pbg,pc)}
                        &nbsp;·&nbsp; {t.get('categoria','—')} &nbsp;·&nbsp; {t.get('criado_em','')[:16]}
                    </p>
                    <p style="margin:10px 0;color:#2c3e50;">{t.get('descricao','—')}</p>
                </div>""", unsafe_allow_html=True)

                comentarios = t.get("comentarios",[])
                if comentarios:
                    st.markdown("#### 💬 Histórico de Comentários")
                    for c in comentarios:
                        st.markdown(
                            f'<div style="background:#f8f9fa;border-left:3px solid #C9A84C;'
                            f'padding:10px 14px;border-radius:6px;margin:6px 0;">'
                            f'<b>{c.get("autor","")}</b> · <span style="color:#64778d;">{c.get("data","")[:16]}</span>'
                            f'<br><span style="font-size:0.9rem;">{c.get("texto","")}</span></div>',
                            unsafe_allow_html=True)
            else:
                st.warning("Ticket não encontrado.")

    # ══ ABA SYNC ZENDESK ════════════════════════════════════════
    with abas[3]:
        st.markdown("### 🔄 Sincronização com Zendesk")

        if papel != "adm":
            st.warning("🔒 Apenas administradores podem acessar esta função.")
            return

        st.markdown("""
        <div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:10px;padding:14px;margin-bottom:16px;">
            <b style="color:#1D4ED8;">📋 Plano de Migração</b><br>
            <span style="font-size:0.85rem;color:#1e40af;">
            <b>Fase 1 (agora):</b> Sincronizar caixa TERMOS → Firestore automaticamente<br>
            <b>Fase 2 (paralelo):</b> Novos tickets abertos direto no sistema KingStar<br>
            <b>Fase 3 (virada):</b> Importar todo histórico → desligar Zendesk
            </span>
        </div>""", unsafe_allow_html=True)

        with st.expander("🔐 Credenciais Zendesk", expanded=True):
            zc1, zc2 = st.columns(2)
            z_sub   = zc1.text_input("Subdomínio", value="kingstarcolchoessupport", key="z_sub")
            z_email = zc2.text_input("E-mail", value="wendley.cunha@kingstarcolchoes.com.br", key="z_email")
            z_token = zc1.text_input("API Token", type="password", key="z_token")
            z_view  = zc2.text_input("View ID (TERMOS)", value="30824480549655", key="z_view")

        st.markdown("---")
        c1, c2 = st.columns(2)

        with c1:
            st.markdown("#### Fase 1 — Sync TERMOS")
            st.caption("Sincroniza a view TERMOS periodicamente")
            if st.button("🔄 Sincronizar Agora", key="btn_sync", type="primary", use_container_width=True):
                if not z_token:
                    st.error("Informe o API Token do Zendesk.")
                else:
                    with st.spinner("Sincronizando..."):
                        ok, qtd, msg = sync_zendesk_para_firestore(z_sub, z_email, z_token, z_view)
                    if ok:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ Erro: {msg}")

        with c2:
            st.markdown("#### Fase 3 — Importar Histórico")
            st.caption("⚠️ Importa TODOS os tickets antes de desligar a Zendesk")
            st.warning("Execute apenas uma vez, quando estiver pronto para migrar.")
            if st.button("📦 Importar Histórico Completo", key="btn_import", use_container_width=True):
                if not z_token:
                    st.error("Informe o API Token.")
                else:
                    prog = st.progress(0, text="Importando...")
                    with st.spinner("Pode demorar alguns minutos..."):
                        ok, qtd, msg = importar_historico_zendesk(z_sub, z_email, z_token)
                    prog.progress(1.0, text="Concluído")
                    if ok:
                        st.success(f"✅ {msg}")
                        st.balloons()
                    else:
                        st.error(f"❌ Erro: {msg}")

        st.markdown("---")
        st.markdown("#### 📊 Tickets no Firestore por origem")
        todos_tick = listar_tickets()
        if todos_tick:
            from collections import Counter
            origens = Counter(t.get("origem","interno") for t in todos_tick)
            df_orig = pd.DataFrame(origens.items(), columns=["Origem","Quantidade"])
            st.dataframe(df_orig, use_container_width=True, hide_index=True)
