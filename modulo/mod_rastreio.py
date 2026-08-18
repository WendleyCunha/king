"""
modulo/mod_rastreio_live.py
Mapa ao vivo (visão do ADM/Supervisor, dentro do Streamlit) da posição do
motorista para UMA entrega específica. Usa Leaflet + OpenStreetMap (sem
chave de API), embutido via st.components.v1.html — mesmo motor de mapa
usado na página pública do cliente (GET /rastreio/{ticket_id} em
motor_api.py), só que esta versão fica dentro do painel autenticado.

Lê (nunca escreve) as coleções gravadas pelo motor_api.py:
  /posicoes_motoristas/{ticket_id}       → posição atual do motorista
  /entregas_rastreio_live/{ticket_id}    → destino + config da entrega

Ponto de entrada usado por modulo/mod_rastreio.py:
  renderizar_mapa_ao_vivo(ticket_id)
"""
import streamlit as st
import streamlit.components.v1 as components

from database import obter_posicao_motorista_db, obter_config_entrega_live_db

# Auto-atualização parcial (a cada 6s) se a versão do Streamlit suportar
# st.fragment — senão, cai num botão manual de atualizar, sem quebrar nada.
_FRAGMENT_DECORATOR = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
_TEM_FRAGMENT = _FRAGMENT_DECORATOR is not None


def _renderizar_mapa_ao_vivo_impl(ticket_id: str):
    config = obter_config_entrega_live_db(ticket_id)
    if not config:
        st.info("Rastreio ao vivo ainda não foi ativado para esta entrega.")
        return

    posicao = obter_posicao_motorista_db(ticket_id)
    if not posicao:
        st.info(
            "⏳ Aguardando o motorista iniciar o compartilhamento de localização "
            "(ele precisa abrir o link e permitir acesso ao GPS no celular)."
        )
        return

    lat_m = posicao.get("lat")
    lng_m = posicao.get("lng")
    lat_d = config.get("destino_lat")
    lng_d = config.get("destino_lng")

    if lat_m is None or lng_m is None or lat_d is None or lng_d is None:
        st.warning("Dados de posição/destino incompletos — não foi possível desenhar o mapa.")
        return

    html = f"""
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <div id="mapa_live_{ticket_id}" style="height:420px;border-radius:10px;overflow:hidden;"></div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
      var mapa = L.map('mapa_live_{ticket_id}');
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        attribution: '&copy; OpenStreetMap contributors'
      }}).addTo(mapa);

      var iconeMotorista = L.divIcon({{ html: '<div style="font-size:26px;">🚚</div>', className: '', iconSize: [26, 26] }});
      var iconeDestino   = L.divIcon({{ html: '<div style="font-size:26px;">📍</div>', className: '', iconSize: [26, 26] }});

      L.marker([{lat_m}, {lng_m}], {{ icon: iconeMotorista }}).addTo(mapa);
      L.marker([{lat_d}, {lng_d}], {{ icon: iconeDestino }}).addTo(mapa);
      mapa.fitBounds([[{lat_m}, {lng_m}], [{lat_d}, {lng_d}]], {{ padding: [30, 30] }});
    </script>
    """
    components.html(html, height=440)

    col1, col2, col3 = st.columns(3)
    vel = posicao.get("velocidade_kmh")
    precisao = posicao.get("precisao_m")
    col1.metric("🚚 Velocidade", f"{vel:.0f} km/h" if vel else "—")
    col2.metric("🎯 Precisão do GPS", f"{precisao:.0f} m" if precisao else "—")
    col3.metric("🚨 Alerta 5km", "✅ Já enviado" if config.get("alerta_5km_enviado") else "⏳ Ainda não")

    st.caption(f"📡 Última atualização recebida: {posicao.get('atualizado_em', '—')}")

    if not _TEM_FRAGMENT:
        st.caption(
            "⚠️ Sua versão do Streamlit não suporta atualização automática parcial "
            "(`st.fragment`). Atualize `streamlit>=1.35.0`, ou use o botão abaixo."
        )
        if st.button("🔄 Atualizar posição", key=f"refresh_live_{ticket_id}"):
            st.rerun()
    else:
        st.caption("🔄 Este mapa se atualiza sozinho a cada ~6 segundos.")


# Aplica o fragment (atualização parcial automática) se disponível na sua
# versão do Streamlit; senão, roda normal (só atualiza com o botão manual).
if _TEM_FRAGMENT:
    renderizar_mapa_ao_vivo = _FRAGMENT_DECORATOR(run_every=6)(_renderizar_mapa_ao_vivo_impl)
else:
    renderizar_mapa_ao_vivo = _renderizar_mapa_ao_vivo_impl
