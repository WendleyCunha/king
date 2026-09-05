import streamlit as st
import pandas as pd
from erp.db import get_db
from erp.services import diretoria_service as svc
from erp.services import produto_service, rh_service
from erp.services import notificacao_service as notif
from erp.auth import ABAS, NIVEIS, definir_permissao
from database import listar_usuarios  # usuários já existem no Painel principal


def render(pode_editar: bool, usuario_login: str):
    st.header("🏛️ Diretoria")

    notificacoes = notif.listar_notificacoes("DIRETORIA")
    if notificacoes:
        with st.expander(f"🔔 {len(notificacoes)} notificação(ões)", expanded=True):
            for n in notificacoes:
                st.write(f"- {n['mensagem']}")
                if st.button("Marcar como lida", key=f"lida_dir_{n['id']}"):
                    notif.marcar_como_lida(n["id"])
                    st.rerun()

    if not pode_editar:
        st.warning("Você não tem permissão de edição nesta aba.")
        return

    abas = st.tabs(["Eliminar pedido", "Ajustar estoque", "Salários e comissão", "Usuários e permissões"])

    with abas[0]:
        st.caption(
            "Só a DIRETORIA pode eliminar um pedido. Se estava LIBERADO, o saldo volta "
            "ao estoque. Se estava BLOQUEADO, sai da fila de compras. Pedidos com carga "
            "já travada (motorista atribuído) ou já faturados não podem mais ser eliminados."
        )
        pedidos = [
            p for p in get_db().collection("pedidos").stream()
            if p.to_dict()["status"] not in ("EM_ROTA", "FATURADO", "CANCELADO")
        ]
        if pedidos:
            opcoes = {f"{p.to_dict()['numero']} [{p.to_dict()['status']}]": p.to_dict()["numero"] for p in pedidos}
            escolha = st.selectbox("Pedido", list(opcoes.keys()))
            if st.button("🗑️ Eliminar pedido"):
                try:
                    svc.eliminar_pedido(opcoes[escolha], usuario_login)
                    st.success(f"Pedido {opcoes[escolha]} eliminado.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        else:
            st.info("Nenhum pedido elegível para eliminação no momento.")

    with abas[1]:
        st.caption("Correção de saldo quando o SKU foi digitado errado na entrada de estoque.")
        produtos = produto_service.listar_produtos()
        if produtos:
            opcoes = {f"{p['sku']} - {p['nome']} (saldo atual: {p['saldo_estoque']})": p["sku"] for p in produtos}
            escolha = st.selectbox("Produto", list(opcoes.keys()))
            novo_saldo = st.number_input("Novo saldo correto", min_value=0, step=1)
            motivo = st.text_input("Motivo do ajuste")
            if st.button("Ajustar saldo"):
                try:
                    svc.ajustar_saldo_produto(opcoes[escolha], int(novo_saldo), motivo, usuario_login)
                    st.success("Saldo ajustado.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    with abas[2]:
        st.subheader("Regras de comissão")
        with st.form("form_regra_comissao", clear_on_submit=True):
            tipo = st.selectbox("Tipo", ["INDIVIDUAL", "LOJA", "REDE"])
            percentual = st.number_input("Percentual (%)", min_value=0.0, max_value=100.0, step=0.5)
            if st.form_submit_button("Cadastrar regra"):
                svc.cadastrar_regra_comissao(tipo, percentual)
                st.success("Regra de comissão cadastrada.")
                st.rerun()

        regras = [r.to_dict() for r in get_db().collection("regras_comissao").where("ativo", "==", True).stream()]
        if regras:
            st.dataframe(pd.DataFrame([{"Tipo": r["tipo"], "Percentual": r["percentual"]} for r in regras]),
                         use_container_width=True, hide_index=True)
            opcoes_desativar = {f"{r['tipo']} - {r['percentual']}%": r["id"] for r in regras}
            escolha = st.selectbox("Desativar regra", list(opcoes_desativar.keys()))
            if st.button("Desativar"):
                svc.desativar_regra_comissao(opcoes_desativar[escolha])
                st.rerun()

        st.subheader("Salários")
        funcionarios = rh_service.listar_funcionarios()
        if funcionarios:
            opcoes = {f["nome"]: f["id"] for f in funcionarios}
            escolha = st.selectbox("Funcionário", list(opcoes.keys()))
            novo_salario = st.number_input("Novo salário (R$)", min_value=0.0, step=100.0)
            if st.button("Atualizar salário"):
                svc.definir_salario(opcoes[escolha], novo_salario)
                st.success("Salário atualizado.")
                st.rerun()

    with abas[3]:
        st.caption(
            "Os usuários (login/senha) continuam sendo criados no Painel, em "
            "Configurações → Usuários. Aqui você só define o que cada um pode "
            "fazer dentro do ERP, aba por aba. Quem tem nível ADM no Painel já "
            "tem acesso total ao ERP automaticamente, sem precisar configurar nada."
        )
        usuarios = [u for u in listar_usuarios() if u.get("role") != "motorista"]
        if usuarios:
            opcoes_user = {f"{u['nome']} ({u['usuario']}) - {u.get('role','')}": u["usuario"] for u in usuarios}
            usuario_escolhido = st.selectbox("Usuário", list(opcoes_user.keys()))
            aba_escolhida = st.selectbox("Aba", ABAS)
            nivel = st.selectbox("Nível", NIVEIS)
            if st.button("Salvar permissão"):
                definir_permissao(opcoes_user[usuario_escolhido], aba_escolhida, nivel)
                st.success("Permissão atualizada.")
                st.rerun()
        else:
            st.info("Nenhum usuário encontrado no Painel.")
