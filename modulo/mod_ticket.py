import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- Mapeamento de Taxonomia e Skills-Based Routing ---
TAXONOMIA = {
    "Logística": ["Atraso na Entrega", "Avaria de Carga", "Extravio", "Troca de Veículo"],
    "Tecnologia (TI)": ["Sistema Fora do Ar", "Erro no App do Motorista", "Reset de Senha"],
    "Financeiro": ["Divergência de Frete", "Aprovação de Pedágio", "Reembolso"]
}

ESPECIALISTAS = {
    "Logística": "Equipe de Tráfego 🚚",
    "Tecnologia (TI)": "Suporte Nível 2 💻",
    "Financeiro": "Faturamento 💰"
}

def renderizar_tickets(papel):
    """Renderiza o módulo completo de Tickets de Alta Performance."""
    
    st.markdown("## 🎫 Central de Serviços Integrada")
    st.markdown("Gestão operacional e análise preditiva de chamados.")

    # Simulação de Banco de Dados local (para a tela funcionar imediatamente)
    if "tickets_db" not in st.session_state:
        st.session_state.tickets_db = []

    # Definição das abas por nível de acesso
    abas_nomes = ["📝 Novo Chamado", "📋 Fila Operacional"]
    if papel in ["supervisor", "adm"]:
        abas_nomes.append("📈 Inteligência (Projeção 90 dias)")
    
    abas = st.tabs(abas_nomes)

    # ══════════════════════════════════════════════════════════════════════════
    # ABA 1: FLUXO OPERACIONAL (ABERTURA COM ROTEAMENTO INTELIGENTE)
    # ══════════════════════════════════════════════════════════════════════════
    with abas[0]:
        st.markdown("### Abrir Novo Chamado")
        
        with st.form("form_novo_ticket"):
            c1, c2 = st.columns(2)
            
            # 1. Taxonomia Nível 1
            categoria = c1.selectbox("Categoria (Área de Negócio):", list(TAXONOMIA.keys()))
            
            # 2. Taxonomia Nível 2 (Dependente da categoria)
            assunto = c2.selectbox("Assunto Específico:", TAXONOMIA[categoria])
            
            # 3. Urgência e SLA
            prioridade = c1.select_slider("Nível de Urgência / SLA", 
                                          options=["Baixa (24h)", "Média (8h)", "Alta (2h)", "Crítica (15 min)"])
            
            # Informações adicionais
            descricao = st.text_area("Descrição detalhada do problema:", height=100)
            
            # Roteamento Inteligente (Skills-Based Routing) visual
            equipe_destino = ESPECIALISTAS[categoria]
            st.info(f"🤖 **Roteamento Inteligente:** Com base no assunto '{assunto}', este ticket será enviado automaticamente para a **{equipe_destino}**.")

            if st.form_submit_button("🚀 Gerar Ticket", use_container_width=True):
                if descricao.strip() == "":
                    st.warning("Por favor, insira uma descrição para o chamado.")
                else:
                    novo_ticket = {
                        "id": f"TK-{np.random.randint(1000, 9999)}",
                        "abertura": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "categoria": categoria,
                        "assunto": assunto,
                        "prioridade": prioridade.split(" ")[0],
                        "equipe": equipe_destino,
                        "status": "⏳ Aberto"
                    }
                    st.session_state.tickets_db.append(novo_ticket)
                    st.success(f"Ticket {novo_ticket['id']} criado e roteado com sucesso!")
                    st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # ABA 2: FILA OPERACIONAL
    # ══════════════════════════════════════════════════════════════════════════
    with abas[1]:
        st.markdown("### Backlog Atual")
        
        if not st.session_state.tickets_db:
            st.info("🎉 Nenhum ticket na fila. Operação zerada!")
        else:
            df_tickets = pd.DataFrame(st.session_state.tickets_db)
            
            # Métricas rápidas
            t1, t2, t3 = st.columns(3)
            t1.metric("Tickets Abertos", len(df_tickets))
            t2.metric("Alta Prioridade", len(df_tickets[df_tickets["prioridade"].isin(["Alta", "Crítica"])]))
            t3.metric("Tempo Médio Primeira Resposta", "12 min") # Mock métrica
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.dataframe(df_tickets, use_container_width=True, hide_index=True)
            
            if st.button("Limpar Fila (Reset)"):
                st.session_state.tickets_db = []
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # ABA 3: INTELIGÊNCIA ESTRATÉGICA (O DIFERENCIAL DO SISTEMA)
    # ══════════════════════════════════════════════════════════════════════════
    if "📈 Inteligência (Projeção 90 dias)" in abas_nomes:
        idx = abas_nomes.index("📈 Inteligência (Projeção 90 dias)")
        with abas[idx]:
            st.markdown("### Motor de Analytics e Projeção Linear")
            st.caption("Baseado no histórico de volume vs. taxa de resolução dos últimos 90 dias.")
            
            # --- Gerador de Dados Históricos Simulados (Para visualização) ---
            hoje = datetime.now()
            datas = [(hoje - timedelta(days=x)).strftime("%Y-%m-%d") for x in range(90, 0, -1)]
            
            # Simula uma tendência de leve aumento nos tickets (crescimento da operação)
            tendencia_entrada = np.linspace(40, 65, 90) + np.random.normal(0, 5, 90)
            # Simula a capacidade da equipe de resolver os chamados (estagnada)
            capacidade_resolucao = np.full(90, 50) + np.random.normal(0, 3, 90)
            
            df_hist = pd.DataFrame({
                "Data": pd.to_datetime(datas),
                "Demanda (Entrada)": tendencia_entrada.astype(int),
                "Capacidade (Resolvidos)": capacidade_resolucao.astype(int)
            }).set_index("Data")

            # --- Projeção Futura (Cálculo Preditivo Básico) ---
            media_entrada_recent = df_hist["Demanda (Entrada)"].tail(15).mean()
            capacidade_atual = df_hist["Capacidade (Resolvidos)"].mean()
            
            diferenca = media_entrada_recent - capacidade_atual
            
            # Layout do Painel de Saúde
            p1, p2 = st.columns([1, 2])
            
            with p1:
                # O Semáforo Estratégico
                st.markdown("#### Status da Operação")
                if diferenca > 5:
                    st.error("🔴 **ALERTA CRÍTICO**\nA projeção indica que a demanda ultrapassou a capacidade do time. Risco de colapso nos prazos de SLA em 14 dias.")
                    st.markdown("**Recomendação:** Contratar +2 analistas ou otimizar fluxo logístico raiz.")
                elif diferenca > 0:
                    st.warning("🟡 **ATENÇÃO**\nVolume de tickets em curva de crescimento. A equipe está operando no limite da capacidade instalada.")
                else:
                    st.success("🟢 **SAUDÁVEL**\nA capacidade de atendimento é superior à demanda. Operação rodando com folga.")

                st.markdown("---")
                st.metric("Demanda Projetada (30d)", f"+{int((diferenca/capacidade_atual)*100)}%")
                st.metric("Capacidade Atual", f"{int(capacidade_atual)} tickets/dia")

            with p2:
                # O Gráfico que os ADMs adoram
                st.line_chart(df_hist, use_container_width=True, height=350, 
                              color=["#e74c3c", "#2ecc71"]) # Vermelho para entrada, Verde para resolução
                
                st.info("💡 **Insights:** O gráfico acima mostra o histórico. Se a linha vermelha (Demanda) se afastar consistentemente para cima da linha verde (Resolução), o sistema dispara o alerta crítico.")
