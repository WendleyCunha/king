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

[CORREÇÃO — cota do Firestore] A primeira versão usava `run_every=6`
(atualização automática a cada 6 segundos, o tempo TODO que a aba "📍 Ao
Vivo" ficasse aberta) — isso, somado ao chat (que já atualiza a cada 2s) e
a vários testes seguidos, estourou a cota diária gratuita do Firestore
("Spark", 50.000 leituras/dia), derrubando o app inteiro com
`ResourceExhausted`. Agora:
  - O intervalo subiu para 20s (bem menos leituras por minuto).
  - A atualização automática vem DESLIGADA por padrão — só liga com um
    toggle, e só enquanto alguém estiver de fato olhando a tela. Sem o
    toggle ligado, é preciso clicar em "🔄 Atualizar posição" manualmente.
Se mesmo assim a cota estourar de novo, o problema é volume de uso real
(vários motoristas/entregas simultâneas) — nesse caso o caminho é migrar
o projeto Firestore do plano Spark (gratuito) para o Blaze (pago por uso;
as primeiras 50k leituras/dia continuam grátis, só o excedente é cobrado).
"""
import streamlit as st
import streamlit.components.v1 as components

from database import obter_posicao_motorista_db, obter_config_entrega_live_db

# Intervalo de atualização automática, em segundos. Subido de 6 para 20 —
# ver nota de correção acima. Ajuste aqui se quiser mais rápido/lento.
_INTERVALO_AUTO_REFRESH = 20

_FRAGMENT_DECORATOR = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
_TEM_FRAGMENT = _FRAGMENT_DECORATOR is not None


def _desenhar_mapa(ticket_id, posicao, config):
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


def _renderizar_conteudo(ticket_id: str):
    """Uma única leitura do Firestore por chamada — usada tanto no modo
    manual (1 leitura por clique) quanto dentro do fragment auto-refresh
    (1 leitura a cada _INTERVALO_AUTO_REFRESH segundos, nunca mais que isso)."""
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

    _desenhar_mapa(ticket_id, posicao, config)


def _renderizar_conteudo_auto(ticket_id: str):
    _renderizar_conteudo(ticket_id)


def renderizar_mapa_ao_vivo(ticket_id: str):
    """
    [CORREÇÃO — cota do Firestore] Atualização automática agora é OPCIONAL
    e vem DESLIGADA por padrão (evita gastar cota de leitura enquanto
    ninguém está olhando a tela). Marque o toggle abaixo só quando
    quiser acompanhar em tempo real; sem ele, use o botão manual.
    """
    chave_toggle = f"live_auto_{ticket_id}"
    auto_ligado = st.toggle(
        f"🔄 Atualização automática a cada {_INTERVALO_AUTO_REFRESH}s "
        "(consome cota do Firestore continuamente — desligue quando não precisar)",
        value=st.session_state.get(chave_toggle, False),
        key=chave_toggle,
    )

    if auto_ligado and _TEM_FRAGMENT:
        _FRAGMENT_DECORATOR(run_every=_INTERVALO_AUTO_REFRESH)(_renderizar_conteudo_auto)(ticket_id)
        return

    if auto_ligado and not _TEM_FRAGMENT:
        st.caption(
            "⚠️ Sua versão do Streamlit não suporta `st.fragment` — não dá pra "
            "atualizar automaticamente sem recarregar a página inteira. "
            "Atualize `streamlit>=1.35.0` no requirements.txt, ou use o botão manual abaixo."
        )

    _renderizar_conteudo(ticket_id)
    if st.button("🔄 Atualizar posição agora", key=f"refresh_live_{ticket_id}"):
        st.rerun()
