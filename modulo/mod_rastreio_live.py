# ══════════════════════════════════════════════════════════════════
# RASTREIO AO VIVO (posição do motorista + alerta de proximidade)
# Coleções:
#   /posicoes_motoristas/{ticket_id} → { lat, lng, velocidade_kmh,
#                                         precisao_m, atualizado_em }
#       Gravado pelo motor_api.py (FastAPI/Render) a cada ping do celular
#       do motorista — o Streamlit NUNCA escreve aqui, só lê.
#
#   /entregas_rastreio_live/{ticket_id} → { destino_lat, destino_lng,
#                                            cliente_telefone,
#                                            alerta_5km_enviado,
#                                            ativado_em }
#       Criado quando o ADM/Supervisor ativa o rastreio ao vivo para
#       uma entrega específica (botão "Ativar rastreio ao vivo").
# ══════════════════════════════════════════════════════════════════

def iniciar_rastreio_live_db(ticket_id: str, destino_lat: float, destino_lng: float,
                              cliente_telefone: str = ""):
    """
    Ativa o rastreio ao vivo para uma entrega. Chame isso quando o ADM/
    Supervisor clicar em "Ativar rastreio ao vivo" na tela do Rastreio —
    é o que faz `renderizar_mapa_ao_vivo()` parar de mostrar
    "Aguardando o motorista iniciar" e passar a funcionar.

    destino_lat/destino_lng: coordenadas do endereço de entrega (vêm de
    geocodificação do campo 'address', feita uma vez na importação da
    planilha ou informada manualmente aqui).
    """
    get_db().collection("entregas_rastreio_live").document(ticket_id).set({
        "destino_lat": destino_lat,
        "destino_lng": destino_lng,
        "cliente_telefone": cliente_telefone,
        "alerta_5km_enviado": False,
        "ativado_em": datetime.now(BRT).isoformat(),
    })


def obter_config_entrega_live_db(ticket_id: str):
    """Retorna a config de rastreio ao vivo de uma entrega, ou None se o
    rastreio ainda não foi ativado para ela."""
    doc = get_db().collection("entregas_rastreio_live").document(ticket_id).get()
    return doc.to_dict() if doc.exists else None


def obter_posicao_motorista_db(ticket_id: str):
    """
    Retorna a última posição conhecida do motorista para esta entrega,
    ou None se ele ainda não começou a compartilhar localização.

    Sem cache de propósito: a posição muda a cada poucos segundos (o
    celular manda um ping novo), então um @st.cache_data aqui mostraria
    o motorista "parado" na tela mesmo ele já tendo avançado.
    """
    doc = get_db().collection("posicoes_motoristas").document(ticket_id).get()
    return doc.to_dict() if doc.exists else None


def marcar_alerta_5km_enviado_db(ticket_id: str):
    """Marca que o alerta de proximidade já foi disparado para esta
    entrega, para o gatilho não repetir o WhatsApp a cada refresh da tela."""
    get_db().collection("entregas_rastreio_live").document(ticket_id).update(
        {"alerta_5km_enviado": True}
    )


def desativar_rastreio_live_db(ticket_id: str):
    """Chame quando a entrega for concluída (baixa dada), para não deixar
    o mapa ao vivo 'aberto' indefinidamente para uma entrega já finalizada."""
    get_db().collection("entregas_rastreio_live").document(ticket_id).delete()
    get_db().collection("posicoes_motoristas").document(ticket_id).delete()
