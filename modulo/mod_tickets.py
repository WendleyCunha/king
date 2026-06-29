"""
KingStar — Módulo de Tickets
Visual inspirado no tickets.html: filas laterais, cards com SLA, badges por status.
Grava no Firestore. Token Zendesk preservado para sync.
"""
import streamlit as st
import pandas as pd
import time
import sys
import os
from datetime import datetime, timezone, timedelta

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _root not in sys.path:
    sys.path.insert(0, _root)

from database import get_db

BRT     = timezone(timedelta(hours=-3))
COLECAO = "tickets"

# ── Configurações ─────────────────────────────────────────────────
ZENDESK_SUBDOMAIN = "kingstarcolchoessupport"
ZENDESK_EMAIL     = "wendley.cunha@kingstarcolchoes.com.br"
ZENDESK_TOKEN     = "tXqPtSws0qZMh4uiZnADQbeqUd2t2UjHUFlliTP8"
ZENDESK_VIEW_ID   = "30824480549655"

CATEGORIAS = {
    "Garantia":       ["Troca de produto","Defeito de fabricação","Prazo vencido","Outros"],
    "Logística":      ["Atraso na entrega","Produto errado","Avaria no transporte","Outros"],
    "Financeiro":     ["Divergência de valor","Reembolso","Cobrança indevida","Outros"],
    "Pós-venda":      ["Dúvida sobre produto","Montagem","Limpeza e conservação","Outros"],
    "Administrativo": ["Documentação","Contrato","RH","Outros"],
    "TI":             ["Sistema fora do ar","Erro no sistema","Acesso bloqueado","Outros"],
}

STATUS_CFG = {
    "aberto":       ("Aberto",       "#FEF9C3","#854D0E","#CA8A04"),
    "em_andamento": ("Em Andamento", "#EFF6FF","#1D5FAE","#2563EB"),
    "aguardando":   ("Aguardando",   "#FFF7ED","#9A3412","#EA580C"),
    "resolvido":    ("Resolvido",    "#DCFCE7","#15803D","#16A34A"),
    "cancelado":    ("Cancelado",    "#F1F5F9","#475569","#64748B"),
}

PRIO_CFG = {
    "urgente": ("Urgente","#FEE2E2","#991B1B"),
    "alta":    ("Alta",   "#FFF7ED","#9A3412"),
    "normal":  ("Normal", "#F0FDF4","#166534"),
    "baixa":   ("Baixa",  "#F1F5F9","#475569"),
}

# ── Helpers ────────────────────────────────────────────────────────
def agora_brt() -> str:
    return datetime.now(BRT).strftime("%Y-%m-%d %H:%M:%S")

def sla_restante(criado_em: str, horas_sla: int = 24) -> tuple:
    """Retorna (texto, pct_usado, vencido)."""
    try:
        dt = datetime.fromisoformat(criado_em.replace(" ","T")).replace(tzinfo=BRT)
        limite = dt + timedelta(hours=horas_sla)
        agora  = datetime.now(BRT)
        diff   = limite - agora
        total  = timedelta(hours=horas_sla).total_seconds()
        decorrido = (agora - dt).total_seconds()
        pct    = min(decorrido / total * 100, 100)
        if diff.total_seconds() <= 0:
            return "Expirado", 100, True
        h = int(diff.total_seconds() // 3600)
        m = int((diff.total_seconds() % 3600) // 60)
        return (f"{h}h {m}m" if h > 0 else f"{m}min"), pct, False
    except:
        return "—", 0, False

def pill(texto, bg, cor):
    return (f'<span style="background:{bg};color:{cor};padding:2px 10px;'
            f'border-radius:12px;font-size:0.72rem;font-weight:700;">{texto}</span>')

# ── CRUD Firestore ─────────────────────────────────────────────────
def listar_tickets() -> list:
    docs = get_db().collection(COLECAO).stream()
    return sorted(
        [d.to_dict() for d in docs],
        key=lambda x: x.get("criado_em",""), reverse=True
    )

def criar_ticket(dados: dict) -> str:
    ref = get_db().collection(COLECAO).document()
    dados.update({
        "id": ref.id, "criado_em": agora_brt(),
        "atualizado_em": agora_brt(), "status": "aberto",
        "origem": "interno", "comentarios": [],
        "horas_sla": 24,
    })
    ref.set(dados)
    return ref.id

def atualizar_ticket(tid: str, dados: dict):
    dados["atualizado_em"] = agora_brt()
    get_db().collection(COLECAO).document(tid).update(dados)

def adicionar_comentario(tid: str, autor: str, texto: str):
    from google.cloud.firestore import ArrayUnion
    get_db().collection(COLECAO).document(tid).update({
        "comentarios": ArrayUnion([{
            "autor": autor, "texto": texto, "data": agora_brt()
        }]),
        "atualizado_em": agora_brt(),
    })

# ── Sync Zendesk ───────────────────────────────────────────────────
def sync_zendesk() -> tuple:
    import requests as req
    url  = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/views/{ZENDESK_VIEW_ID}/tickets.json?per_page=100"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
    try:
        r = req.get(url, auth=auth, timeout=15)
        if r.status_code != 200:
            return False, 0, f"Zendesk retornou {r.status_code}"
        tickets = r.json().get("tickets", [])
        db    = get_db()
        batch = db.batch()
        mapa  = {"new":"aberto","open":"em_andamento","pending":"aguardando",
                 "hold":"aguardando","solved":"resolvido","closed":"resolvido"}
        mprio = {"urgent":"urgente","high":"alta","normal":"normal","low":"baixa"}
        for t in tickets:
            ref = db.collection(COLECAO).document(f"zendesk_{t['id']}")
            batch.set(ref, {
                "id":           f"zendesk_{t['id']}",
                "id_zendesk":   t["id"],
                "assunto":      t.get("subject",""),
                "descricao":    t.get("description",""),
                "status":       mapa.get(t.get("status","open"),"aberto"),
                "prioridade":   mprio.get(t.get("priority","normal"),"normal"),
                "categoria":    "Zendesk/TERMOS",
                "criado_em":    t.get("created_at","")[:19].replace("T"," "),
                "atualizado_em":t.get("updated_at","")[:19].replace("T"," "),
                "origem":       "zendesk",
                "comentarios":  [],
                "horas_sla":    24,
            }, merge=True)
        batch.commit()
        return True, len(tickets), f"{len(tickets)} tickets sincronizados"
    except Exception as e:
        return False, 0, str(e)

# ── RENDERIZAÇÃO ───────────────────────────────────────────────────
def renderizar_tickets(papel: str, user: dict = None):
    if user is None:
        user = {"role": papel, "nome": "Usuário", "usuario": "user"}

    todos = listar_tickets()

    # ── Contagens por fila ────────────────────────────────────────
    ct = {
        "todos":       len(todos),
        "aberto":      sum(1 for t in todos if t.get("status")=="aberto"),
        "em_andamento":sum(1 for t in todos if t.get("status")=="em_andamento"),
        "aguardando":  sum(1 for t in todos if t.get("status")=="aguardando"),
        "resolvido":   sum(1 for t in todos if t.get("status")=="resolvido"),
        "urgente":     sum(1 for t in todos if t.get("prioridade")=="urgente"),
        "zendesk":     sum(1 for t in todos if "zendesk" in t.get("origem","")),
    }

    # ── CSS específico do módulo ──────────────────────────────────
    st.markdown("""
    <style>
    .tk-fila-btn { cursor:pointer; padding:10px 14px; border-radius:8px; margin-bottom:4px;
        display:flex; justify-content:space-between; align-items:center;
        font-size:0.88rem; font-weight:500; color:#2c3e50;
        background:#f8f9fa; border:1px solid #e2e8f0; transition:all .15s; }
    .tk-fila-btn:hover { background:#f0f2f5; border-color:#C9A84C; }
    .tk-fila-btn.ativa { background:rgba(201,168,76,.1); border-color:#C9A84C;
        color:#7a5f1a; font-weight:700; }
    .tk-badge { background:#e2e8f0; color:#475569; padding:2px 8px;
        border-radius:10px; font-size:0.72rem; font-weight:700; }
    .tk-badge-red { background:#FEE2E2; color:#991B1B; }
    .tk-card { background:#fff; border:1px solid #e2e8f0; border-radius:10px;
        padding:14px 16px; margin-bottom:8px; border-left:4px solid #C9A84C; }
    .tk-card-header { display:flex; justify-content:space-between;
        align-items:flex-start; margin-bottom:6px; }
    .tk-card-title { font-size:0.92rem; font-weight:700; color:#2c3e50; }
    .tk-card-meta { font-size:0.75rem; color:#64778d; margin-top:4px; }
    .tk-sla-bar { background:#e8ecf0; border-radius:4px; height:5px; margin:8px 0 4px; }
    .tk-sla-fill { height:5px; border-radius:4px; }
    .tk-sla-text { font-size:0.7rem; color:#64778d; }
    </style>
    """, unsafe_allow_html=True)

    # ── Layout: sidebar de filas + conteúdo ───────────────────────
    col_filas, col_main = st.columns([1, 3.5])

    # Fila selecionada
    if "tk_fila" not in st.session_state:
        st.session_state.tk_fila = "todos"
    if "tk_detalhe" not in st.session_state:
        st.session_state.tk_detalhe = None
    if "tk_modo" not in st.session_state:
        st.session_state.tk_modo = "lista"  # lista | novo | detalhe | sync

    with col_filas:
        st.markdown("**Filas de Trabalho**")

        filas = [
            ("todos",        f"Todos os Tickets",     ct["todos"],        False),
            ("aberto",       "Abertos",                ct["aberto"],       False),
            ("em_andamento", "Em Andamento",           ct["em_andamento"], False),
            ("aguardando",   "Aguardando",             ct["aguardando"],   False),
            ("resolvido",    "Resolvidos",             ct["resolvido"],    False),
            ("urgente",      "Urgentes",               ct["urgente"],      ct["urgente"]>0),
            ("zendesk",      "Zendesk / TERMOS",       ct["zendesk"],      False),
        ]

        for key, label, qtd, alerta in filas:
            ativa = "ativa" if st.session_state.tk_fila == key else ""
            badge_cls = "tk-badge-red" if alerta else "tk-badge"
            if st.button(
                f"{label}  ({qtd})",
                key=f"fila_{key}",
                use_container_width=True,
                type="primary" if st.session_state.tk_fila == key else "secondary"
            ):
                st.session_state.tk_fila  = key
                st.session_state.tk_modo  = "lista"
                st.session_state.tk_detalhe = None
                st.rerun()

        st.markdown("---")
        st.markdown("**Ações**")
        if st.button("➕ Novo Ticket", use_container_width=True, type="primary"):
            st.session_state.tk_modo = "novo"
            st.rerun()
        if papel == "adm":
            if st.button("🔄 Sync Zendesk", use_container_width=True):
                st.session_state.tk_modo = "sync"
                st.rerun()

    # ── Conteúdo principal ────────────────────────────────────────
    with col_main:

        # ══ MODO LISTA ══════════════════════════════════════════
        if st.session_state.tk_modo in ("lista", None):

            # Filtra por fila
            fila = st.session_state.tk_fila
            if fila == "todos":
                filtrados = todos
            elif fila == "urgente":
                filtrados = [t for t in todos if t.get("prioridade")=="urgente"]
            elif fila == "zendesk":
                filtrados = [t for t in todos if "zendesk" in t.get("origem","")]
            else:
                filtrados = [t for t in todos if t.get("status")==fila]

            # Busca rápida
            busca = st.text_input(
                "", placeholder="Buscar por ID, assunto, solicitante...",
                label_visibility="collapsed", key="tk_busca"
            )
            if busca:
                b = busca.lower()
                filtrados = [t for t in filtrados if
                    b in str(t.get("assunto","")).lower() or
                    b in str(t.get("id","")).lower() or
                    b in str(t.get("id_zendesk","")).lower() or
                    b in str(t.get("solicitante_nome","")).lower()
                ]

            if not filtrados:
                st.info("Nenhum ticket nesta fila.")
            else:
                st.markdown(f"**{len(filtrados)} ticket(s)**")
                for t in filtrados:
                    tid   = t.get("id","")
                    sl, spct, svenc = sla_restante(t.get("criado_em",""), t.get("horas_sla",24))
                    sv, sbg, sc, sbc = STATUS_CFG.get(t.get("status","aberto"),("—","#fff","#000","#000"))
                    pv, pbg, pc      = PRIO_CFG.get(t.get("prioridade","normal"),("—","#fff","#000"))
                    origem_icon = "🔗" if "zendesk" in t.get("origem","") else "🏠"
                    sla_cor = "#DC2626" if svenc else ("#CA8A04" if spct>70 else "#16A34A")
                    num_com = len(t.get("comentarios",[]))

                    st.markdown(f"""
                    <div class="tk-card">
                        <div class="tk-card-header">
                            <div>
                                <div class="tk-card-title">
                                    {origem_icon} #{t.get('id_zendesk', tid[:8])} — {t.get('assunto','Sem título')[:55]}
                                </div>
                                <div class="tk-card-meta">
                                    {t.get('categoria','—')} &nbsp;·&nbsp;
                                    {t.get('solicitante_nome', t.get('solicitante','—'))} &nbsp;·&nbsp;
                                    {t.get('criado_em','')[:16]}
                                    {"&nbsp;·&nbsp; 💬 " + str(num_com) if num_com else ""}
                                </div>
                            </div>
                            <div style="text-align:right;white-space:nowrap;">
                                {pill(sv,sbg,sc)} {pill(pv,pbg,pc)}
                            </div>
                        </div>
                        <div class="tk-sla-bar">
                            <div class="tk-sla-fill"
                                 style="width:{spct:.0f}%;background:{sla_cor};"></div>
                        </div>
                        <div class="tk-sla-text">
                            SLA: <b style="color:{sla_cor};">{sl}</b>
                        </div>
                    </div>""", unsafe_allow_html=True)

                    bc1, bc2 = st.columns([1, 5])
                    with bc1:
                        if st.button("Abrir", key=f"open_{tid}", use_container_width=True):
                            st.session_state.tk_detalhe = tid
                            st.session_state.tk_modo    = "detalhe"
                            st.rerun()

        # ══ MODO DETALHE ════════════════════════════════════════
        elif st.session_state.tk_modo == "detalhe":
            tid = st.session_state.tk_detalhe
            doc = get_db().collection(COLECAO).document(tid).get()
            if not doc.exists:
                st.error("Ticket não encontrado.")
            else:
                t   = doc.to_dict()
                sl, spct, svenc = sla_restante(t.get("criado_em",""), t.get("horas_sla",24))
                sv, sbg, sc, _  = STATUS_CFG.get(t.get("status","aberto"),("—","#fff","#000","#000"))
                pv, pbg, pc     = PRIO_CFG.get(t.get("prioridade","normal"),("—","#fff","#000"))
                sla_cor = "#DC2626" if svenc else ("#CA8A04" if spct>70 else "#16A34A")

                if st.button("← Voltar para a fila"):
                    st.session_state.tk_modo    = "lista"
                    st.session_state.tk_detalhe = None
                    st.rerun()

                st.markdown(f"""
                <div style="background:#fff;border:1px solid #e2e8f0;border-left:6px solid #C9A84C;
                            border-radius:12px;padding:18px 20px;margin-bottom:16px;">
                    <h3 style="margin:0 0 6px;color:#2c3e50;">
                        #{t.get('id_zendesk', tid[:8])} — {t.get('assunto','—')}
                    </h3>
                    <div style="margin-bottom:10px;">
                        {pill(sv,sbg,sc)} {pill(pv,pbg,pc)}
                        <span style="font-size:0.78rem;color:#64778d;margin-left:8px;">
                            {t.get('categoria','—')} · {t.get('criado_em','')[:16]}
                        </span>
                    </div>
                    <p style="color:#2c3e50;font-size:0.9rem;margin:8px 0;">
                        {t.get('descricao') or t.get('assunto','—')}
                    </p>
                    <div class="tk-sla-bar" style="margin-top:12px;">
                        <div class="tk-sla-fill"
                             style="width:{spct:.0f}%;background:{sla_cor};height:6px;border-radius:4px;"></div>
                    </div>
                    <span style="font-size:0.75rem;color:{sla_cor};font-weight:700;">
                        SLA: {sl}
                    </span>
                </div>""", unsafe_allow_html=True)

                # Ações — supervisor/adm
                if papel in ("supervisor","adm"):
                    da1, da2, da3 = st.columns(3)
                    novo_status = da1.selectbox(
                        "Status", list(STATUS_CFG.keys()),
                        index=list(STATUS_CFG.keys()).index(t.get("status","aberto")),
                        key="det_status"
                    )
                    nova_prio = da2.selectbox(
                        "Prioridade", list(PRIO_CFG.keys()),
                        index=list(PRIO_CFG.keys()).index(t.get("prioridade","normal")),
                        key="det_prio"
                    )
                    if da3.button("💾 Salvar", type="primary", use_container_width=True):
                        atualizar_ticket(tid, {"status": novo_status, "prioridade": nova_prio})
                        st.success("Atualizado!"); time.sleep(.4); st.rerun()

                # Histórico de comentários
                st.markdown("#### 💬 Histórico")
                comentarios = t.get("comentarios", [])
                if not comentarios:
                    st.caption("Nenhum comentário ainda.")
                else:
                    for c in comentarios:
                        alinha = "right" if c.get("autor") == user.get("nome") else "left"
                        bg_com = "#EFF6FF" if alinha == "right" else "#f8f9fa"
                        bord   = "#2563EB" if alinha == "right" else "#C9A84C"
                        st.markdown(
                            f'<div style="text-align:{alinha};margin:6px 0;">'
                            f'<div style="display:inline-block;background:{bg_com};'
                            f'border-left:3px solid {bord};padding:8px 12px;'
                            f'border-radius:8px;max-width:80%;text-align:left;">'
                            f'<b style="font-size:0.8rem;">{c.get("autor","")}</b>'
                            f'<span style="color:#64778d;font-size:0.72rem;margin-left:6px;">{c.get("data","")[:16]}</span>'
                            f'<br><span style="font-size:0.88rem;">{c.get("texto","")}</span>'
                            f'</div></div>', unsafe_allow_html=True)

                # Novo comentário
                st.markdown("---")
                with st.form(f"form_com_{tid}", clear_on_submit=True):
                    novo_com = st.text_area("Escrever resposta / comentário",
                                            height=80, placeholder="Digite a tratativa...")
                    cc1, cc2 = st.columns([3,1])
                    if cc2.form_submit_button("Enviar", type="primary", use_container_width=True):
                        if novo_com.strip():
                            adicionar_comentario(tid, user.get("nome",""), novo_com.strip())
                            st.success("Enviado!"); time.sleep(.3); st.rerun()

                    # Encerrar
                    if papel in ("supervisor","adm"):
                        if cc1.form_submit_button("✅ Encerrar Ticket"):
                            atualizar_ticket(tid, {"status":"resolvido"})
                            st.success("Ticket encerrado!")
                            time.sleep(.5)
                            st.session_state.tk_modo    = "lista"
                            st.session_state.tk_detalhe = None
                            st.rerun()

        # ══ MODO NOVO TICKET ════════════════════════════════════
        elif st.session_state.tk_modo == "novo":
            st.markdown("### ➕ Abrir Novo Chamado")
            if st.button("← Voltar"):
                st.session_state.tk_modo = "lista"; st.rerun()

            with st.form("form_novo_ticket", clear_on_submit=True):
                nc1, nc2 = st.columns([3,1])
                assunto    = nc1.text_input("Assunto *", placeholder="Descreva o problema")
                prioridade = nc2.selectbox("Prioridade", ["normal","alta","urgente","baixa"])

                nc3, nc4 = st.columns(2)
                categoria    = nc3.selectbox("Categoria", list(CATEGORIAS.keys()))
                subcategoria = nc4.selectbox("Subcategoria", CATEGORIAS.get(categoria,["Outros"]))

                descricao = st.text_area("Descrição *", height=120)

                nd1, nd2 = st.columns(2)
                sol_nome  = nd1.text_input("Solicitante", value=user.get("nome",""))
                sol_email = nd2.text_input("E-mail", placeholder="email@kingstar.com.br")
                atrib     = st.text_input("Atribuir para", placeholder="Nome do responsável (opcional)")

                if st.form_submit_button("🚀 Abrir Chamado", type="primary", use_container_width=True):
                    if not assunto.strip() or not descricao.strip():
                        st.error("Preencha Assunto e Descrição.")
                    else:
                        novo_id = criar_ticket({
                            "assunto": assunto.strip(), "descricao": descricao.strip(),
                            "categoria": categoria, "subcategoria": subcategoria,
                            "prioridade": prioridade,
                            "solicitante_nome": sol_nome, "solicitante_email": sol_email,
                            "atribuido_para": atrib, "aberto_por": user.get("usuario",""),
                        })
                        st.success(f"✅ Chamado **#{novo_id[:8]}** aberto!")
                        st.balloons()
                        time.sleep(1.5)
                        st.session_state.tk_modo = "lista"; st.rerun()

        # ══ MODO SYNC ZENDESK ═══════════════════════════════════
        elif st.session_state.tk_modo == "sync":
            st.markdown("### 🔄 Sincronização Zendesk")
            if st.button("← Voltar"):
                st.session_state.tk_modo = "lista"; st.rerun()

            st.info(f"API configurada: `{ZENDESK_SUBDOMAIN}` · View TERMOS: `{ZENDESK_VIEW_ID}`")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Fase 1 — Sync TERMOS**")
                st.caption("Copia os tickets da view TERMOS para o Firestore")
                if st.button("🔄 Sincronizar Agora", type="primary", use_container_width=True):
                    with st.spinner("Consultando Zendesk..."):
                        ok, qtd, msg = sync_zendesk()
                    if ok: st.success(f"✅ {msg}")
                    else:  st.error(f"❌ {msg}")

            with c2:
                st.markdown("**Fase 3 — Importar Histórico**")
                st.caption("Importa TODOS os tickets antes de desligar a Zendesk")
                st.warning("Execute uma única vez na migração final.")
                if st.button("📦 Importar Tudo", use_container_width=True):
                    import requests as req
                    url   = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets.json?per_page=100"
                    auth  = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
                    total = 0
                    prog  = st.progress(0, text="Importando...")
                    mapa  = {"new":"aberto","open":"em_andamento","pending":"aguardando",
                             "hold":"aguardando","solved":"resolvido","closed":"resolvido"}
                    mprio = {"urgent":"urgente","high":"alta","normal":"normal","low":"baixa"}
                    while url:
                        r = req.get(url, auth=auth, timeout=30)
                        if r.status_code != 200: break
                        data = r.json()
                        tickets = data.get("tickets",[])
                        db = get_db(); batch = db.batch()
                        for t in tickets:
                            ref = db.collection(COLECAO).document(f"zendesk_{t['id']}")
                            batch.set(ref, {
                                "id": f"zendesk_{t['id']}", "id_zendesk": t["id"],
                                "assunto": t.get("subject",""),
                                "status":  mapa.get(t.get("status","open"),"aberto"),
                                "prioridade": mprio.get(t.get("priority","normal"),"normal"),
                                "categoria": "Zendesk/Historico",
                                "criado_em": t.get("created_at","")[:19].replace("T"," "),
                                "atualizado_em": t.get("updated_at","")[:19].replace("T"," "),
                                "origem": "zendesk_historico", "comentarios": [], "horas_sla": 24,
                            }, merge=True)
                        batch.commit(); total += len(tickets)
                        prog.progress(min(total/500, 1.0), text=f"{total} importados...")
                        url = data.get("next_page")
                    prog.empty()
                    st.success(f"✅ {total} tickets importados para o Firestore!")

            st.markdown("---")
            st.markdown("#### Tickets no Firestore por origem")
            todos2 = listar_tickets()
            from collections import Counter
            df_orig = pd.DataFrame(
                Counter(t.get("origem","interno") for t in todos2).items(),
                columns=["Origem","Qtd"]
            )
            st.dataframe(df_orig, use_container_width=True, hide_index=True)
