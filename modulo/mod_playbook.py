"""
Plano de Eliminação de Custo — versão desktop (PyQt6)

Recriação do checklist "Ferramenta externa -> solução interna" como
aplicativo desktop, com estética retrô (Windows Classic / Motif, anos
90): fundo cinza-carvão, texto branco, acentos azul-petróleo/teal,
bordas em baixo-relevo (bevel) nítidas, sem sombras suaves nem cantos
arredondados, fonte monoespaçada sem anti-aliasing.

As notas internas ficam sempre visíveis no card do item (não exigem
clique pra aparecer), conforme pedido.

Dados salvos localmente em ./playbook_dados.json (ao lado deste script).
Rodar com:  python playbook_desktop.py
Requer:     pip install PyQt6
"""
import sys
import os
import json
import uuid

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QComboBox, QLineEdit, QScrollArea, QToolButton,
    QSizePolicy, QMessageBox, QInputDialog, QDoubleSpinBox, QGridLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QDoubleValidator

# ═══════════════════════════════════════════════════════════════════
# PALETA / ESTILO — Windows Classic / Motif escuro
# ═══════════════════════════════════════════════════════════════════
COR_FUNDO       = "#2c2c2c"   # cinza-carvão
COR_PAINEL      = "#343434"
COR_PAINEL_ALT  = "#3a3a3a"
COR_TEXTO       = "#e8e8e8"
COR_TEXTO_DIM   = "#9a9a9a"
COR_TEAL        = "#2f8f89"   # acento azul-petróleo
COR_TEAL_CLARO  = "#45b3ac"
COR_BEVEL_CLARO = "#6a6a6a"
COR_BEVEL_ESC   = "#141414"
COR_ALERTA      = "#b5564d"

STATUS_OPCOES = ["pendente", "andamento", "solicitado", "feito", "bloqueado", "na"]
STATUS_LABEL = {
    "pendente": "PENDENTE", "andamento": "EM ANDAMENTO", "solicitado": "SOLICITADO",
    "feito": "FEITO", "bloqueado": "BLOQUEADO", "na": "N/A",
}
STATUS_COR = {
    "pendente": COR_TEXTO_DIM, "andamento": "#c9962f", "solicitado": "#4f8fc9",
    "feito": COR_TEAL_CLARO, "bloqueado": COR_ALERTA, "na": "#6a6a6a",
}

ARQUIVO_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playbook_dados.json")


def _item(texto):
    return {"texto": texto, "status": "pendente", "nota_interna": ""}


def modelo_base_fases():
    return [
        {"titulo": "1. ENQUADRAMENTO E DECISAO", "gate": False, "itens": [
            _item("Consolidar o custo atual da ferramenta externa vs. custo de construir e manter internamente"),
            _item("Buscar valor atualizado com o fornecedor/financeiro"),
            _item("Realizar o levantamento do investimento técnico com o TI"),
            _item("Levantar com o Jurídico o prazo de aviso prévio e cláusulas críticas do contrato atual"),
            _item("Coletar contratos e aditivos vigentes"),
            _item("Fornecer contratos/aditivos ao Jurídico com prazo definido para avaliação"),
            _item("Definir a arquitetura da solução interna"),
            _item("Validar e aprovar o enquadramento com os Heads"),
            _item("Registrar a decisão formalmente e iniciar a Fase 2"),
        ]},
        {"titulo": "2. DIAGNOSTICO E LEVANTAMENTO (AS IS)", "gate": False, "itens": [
            _item("Mapear todas as funcionalidades hoje usadas na ferramenta externa"),
            _item("Aplicar o formulário de diagnóstico ao administrador da ferramenta"),
            _item("Aplicar o formulário de levantamento aos usuários finais das áreas envolvidas"),
            _item("Levantar volumetria e indicadores de uso relevantes"),
            _item("Consultar o Financeiro para confirmar valores e cobranças adicionais"),
            _item("Consolidar o diagnóstico e submeter para aprovação"),
        ]},
        {"titulo": "3. DESENHO DA SOLUCAO (TO BE)", "gate": False, "itens": [
            _item("Desenhar o fluxo/jornada completa, com regras de disparo por canal e frequência"),
            _item("Construir a Matriz de Gaps (ferramenta externa x solução interna)"),
            _item("Desenhar a arquitetura de integração com os canais necessários"),
            _item("Desenhar o modelo de dados único atravessando as etapas"),
            _item("Desenhar o processo de tratativa/fechamento de loop"),
            _item("Submeter o desenho para revisão de LGPD/Jurídico"),
            _item("Aprovar o desenho"),
        ]},
        {"titulo": "4. DESENVOLVIMENTO/PARAMETRIZACAO", "gate": False, "itens": [
            _item("Priorizar as ondas de construção"),
            _item("Desenvolver/parametrizar cada onda conforme o desenho aprovado"),
            _item("Acompanhar o orçamento de desenvolvimento vs. TCO projetado"),
            _item("Testar cada onda antes de liberar para migração"),
            _item("Obter aprovação por onda entregue"),
        ]},
        {"titulo": "5. MIGRACAO E TESTES", "gate": False, "itens": [
            _item("Rodar cada etapa em paralelo com a ferramenta externa pelo período mínimo definido"),
            _item("Comparar indicadores entre as duas ferramentas"),
            _item("Migrar ou preservar acesso ao histórico de dados"),
            _item("Validar critérios de aceite por onda"),
            _item("Aprovar formalmente cada onda migrada"),
        ]},
        {"titulo": "6. IMPLANTACAO", "gate": False, "itens": [
            _item("Treinar cada área envolvida na nova ferramenta"),
            _item("Comunicar o RACI de quem trata cada frente"),
            _item("Ativar a ferramenta em produção, etapa por etapa"),
            _item("Validar que os dados estão sendo capturados corretamente após a ativação"),
        ]},
        {"titulo": "7. ESTABILIZACAO", "gate": False, "itens": [
            _item("Acompanhar indicadores de aderência"),
            _item("Coletar e tratar feedback das áreas usuárias nas primeiras semanas"),
            _item("Ajustar parametrizações/regras identificadas como problema"),
            _item("Obter aprovação final de estabilização — libera o cancelamento da ferramenta externa"),
        ]},
        {"titulo": "8. REVISAR CLAUSULAS CONTRATUAIS DO CONTRATO ANTERIOR", "gate": False, "itens": [
            _item("Localizar o contrato vigente e eventuais aditivos"),
            _item("Identificar o prazo de aviso prévio exigido"),
            _item("Identificar multa rescisória, se houver"),
            _item("Identificar vigência mínima e data de renovação automática"),
            _item("Identificar a forma exigida de notificação"),
            _item("Repassar o levantamento ao Financeiro"),
        ]},
        {"titulo": "9. LEVANTAR SITUACAO FINANCEIRA DO CONTRATO ANTERIOR", "gate": False, "itens": [
            _item("Levantar faturas em aberto e status de pagamento"),
            _item("Confirmar o ciclo de cobrança vigente"),
            _item("Calcular o valor de eventual multa rescisória"),
            _item("Consolidar o valor total do encerramento"),
        ]},
        {"titulo": "10. EXPORTAR E VALIDAR BACKUP DO HISTORICO DE DADOS", "gate": False, "itens": [
            _item("Levantar todos os dados históricos existentes"),
            _item("Executar a extração completa dos dados na plataforma"),
            _item("Validar a integridade do que foi exportado"),
            _item("Armazenar o backup em local definitivo e seguro"),
            _item("Confirmar formalmente que o backup está validado"),
        ]},
        {"titulo": "11. ENVIO DA NOTIFICACAO DE AVISO PREVIO", "gate": True, "itens": [
            _item("Confirmar que o backup do histórico já foi validado"),
            _item("Redigir a notificação conforme a forma exigida pelo contrato"),
            _item("Validar o texto com o Jurídico"),
            _item("Enviar a notificação dentro do prazo contratual de aviso prévio"),
            _item("Guardar o comprovante de envio/protocolo"),
        ]},
        {"titulo": "12. DESATIVAR USUARIOS, INTEGRACOES E CREDENCIAIS", "gate": True, "itens": [
            _item("Confirmar que a notificação já foi enviada e o prazo contratual está em curso"),
            _item("Levantar todos os usuários com acesso à plataforma"),
            _item("Remover/desativar integrações ativas"),
            _item("Revogar credenciais e acessos de API"),
            _item("Confirmar o encerramento técnico completo com TI"),
        ]},
        {"titulo": "13. CONFIRMAR AUSENCIA DE COBRANCAS E ARQUIVAR COMPROVANTE", "gate": True, "itens": [
            _item("Solicitar ao fornecedor o comprovante formal de cancelamento"),
            _item("Confirmar com o Financeiro que não há cobranças futuras programadas"),
            _item("Arquivar contrato, aditivos, notificação enviada e comprovante"),
            _item("Encerrar formalmente o processo junto ao Financeiro/Jurídico"),
        ]},
        {"titulo": "14. NOTIFICAR AREAS SOBRE A DESATIVACAO", "gate": True, "itens": [
            _item("Confirmar que a desativação técnica (Fase 12) foi concluída"),
            _item("Comunicar as áreas envolvidas sobre a desativação"),
            _item("Reforçar o canal de suporte para dúvidas sobre a ferramenta nova"),
            _item("Registrar o encerramento do processo de cancelamento como concluído"),
        ]},
    ]


# ═══════════════════════════════════════════════════════════════════
# PERSISTÊNCIA (JSON local)
# ═══════════════════════════════════════════════════════════════════
class Armazenamento:
    def __init__(self, caminho):
        self.caminho = caminho

    def carregar(self):
        if not os.path.exists(self.caminho):
            return {"iniciativas": [], "ativa_id": None}
        try:
            with open(self.caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"iniciativas": [], "ativa_id": None}

    def salvar(self, estado):
        try:
            with open(self.caminho, "w", encoding="utf-8") as f:
                json.dump(estado, f, ensure_ascii=False, indent=2)
        except OSError as e:
            QMessageBox.warning(None, "Aviso", f"Não foi possível salvar os dados:\n{e}")


# ═══════════════════════════════════════════════════════════════════
# FOLHA DE ESTILO (QSS) — bordas em bevel, sem cantos arredondados
# ═══════════════════════════════════════════════════════════════════
def folha_de_estilo():
    return f"""
    QWidget {{
        background-color: {COR_FUNDO};
        color: {COR_TEXTO};
    }}
    QMainWindow {{ background-color: {COR_FUNDO}; }}

    QLabel {{ background: transparent; }}
    QLabel[papel="titulo_fase"] {{
        color: {COR_TEAL_CLARO}; font-weight: bold;
    }}
    QLabel[papel="kpi_label"] {{
        color: {COR_TEXTO_DIM}; font-size: 9pt;
    }}
    QLabel[papel="kpi_valor"] {{
        color: {COR_TEAL_CLARO}; font-size: 15pt; font-weight: bold;
    }}
    QLabel[papel="rotulo_campo"] {{
        color: {COR_TEXTO_DIM}; font-size: 8pt;
    }}
    QLabel[papel="gate"] {{
        color: {COR_ALERTA};
        border: 2px solid {COR_ALERTA};
        padding: 4px;
    }}

    QFrame[papel="painel"] {{
        background-color: {COR_PAINEL};
        border-style: outset;
        border-width: 2px;
        border-color: {COR_BEVEL_CLARO} {COR_BEVEL_ESC} {COR_BEVEL_ESC} {COR_BEVEL_CLARO};
    }}
    QFrame[papel="kpi_box"] {{
        background-color: {COR_PAINEL_ALT};
        border-style: inset;
        border-width: 2px;
        border-color: {COR_BEVEL_ESC} {COR_BEVEL_CLARO} {COR_BEVEL_CLARO} {COR_BEVEL_ESC};
        padding: 6px;
    }}
    QFrame[papel="item_card"] {{
        background-color: {COR_PAINEL_ALT};
        border-style: outset;
        border-width: 2px;
        border-color: {COR_BEVEL_CLARO} {COR_BEVEL_ESC} {COR_BEVEL_ESC} {COR_BEVEL_CLARO};
    }}

    QPushButton {{
        background-color: #454545;
        color: {COR_TEXTO};
        border-style: outset;
        border-width: 2px;
        border-color: {COR_BEVEL_CLARO} {COR_BEVEL_ESC} {COR_BEVEL_ESC} {COR_BEVEL_CLARO};
        padding: 5px 12px;
        border-radius: 0px;
    }}
    QPushButton:hover {{ background-color: #4d4d4d; }}
    QPushButton:pressed {{
        border-style: inset;
        border-color: {COR_BEVEL_ESC} {COR_BEVEL_CLARO} {COR_BEVEL_CLARO} {COR_BEVEL_ESC};
    }}
    QPushButton[papel="perigo"]:hover {{ background-color: {COR_ALERTA}; }}

    QToolButton {{
        background-color: #454545;
        border-style: outset;
        border-width: 2px;
        border-color: {COR_BEVEL_CLARO} {COR_BEVEL_ESC} {COR_BEVEL_ESC} {COR_BEVEL_CLARO};
        border-radius: 0px;
        padding: 3px;
        color: {COR_TEXTO};
    }}
    QToolButton:pressed {{
        border-style: inset;
        border-color: {COR_BEVEL_ESC} {COR_BEVEL_CLARO} {COR_BEVEL_CLARO} {COR_BEVEL_ESC};
    }}

    QComboBox {{
        background-color: #3a3a3a;
        color: {COR_TEXTO};
        border-style: inset;
        border-width: 2px;
        border-color: {COR_BEVEL_ESC} {COR_BEVEL_CLARO} {COR_BEVEL_CLARO} {COR_BEVEL_ESC};
        padding: 3px 6px;
        border-radius: 0px;
    }}
    QComboBox QAbstractItemView {{
        background-color: #3a3a3a; color: {COR_TEXTO};
        selection-background-color: {COR_TEAL};
        border: 2px solid {COR_BEVEL_ESC};
        border-radius: 0px;
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}

    QLineEdit, QDoubleSpinBox {{
        background-color: #262626;
        color: {COR_TEAL_CLARO};
        border-style: inset;
        border-width: 2px;
        border-color: {COR_BEVEL_ESC} {COR_BEVEL_CLARO} {COR_BEVEL_CLARO} {COR_BEVEL_ESC};
        padding: 4px 6px;
        border-radius: 0px;
    }}
    QLineEdit[papel="nota"] {{
        color: {COR_TEXTO};
        font-style: italic;
    }}
    QLineEdit[papel="nota"]:placeholder {{ color: {COR_TEXTO_DIM}; }}

    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{
        background: {COR_FUNDO}; width: 16px; border-left: 2px solid {COR_BEVEL_ESC};
    }}
    QScrollBar::handle:vertical {{
        background: #4d4d4d; min-height: 24px;
        border-style: outset; border-width: 1px;
        border-color: {COR_BEVEL_CLARO} {COR_BEVEL_ESC} {COR_BEVEL_ESC} {COR_BEVEL_CLARO};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    """


def fonte_monoespacada(tamanho=9, negrito=False):
    fam = ["Consolas", "Courier New", "Lucida Console", "monospace"]
    fonte = QFont(fam[0], tamanho)
    fonte.setStyleHint(QFont.StyleHint.Monospace)
    fonte.setFamilies(fam)
    fonte.setBold(negrito)
    # Pedido explícito: renderização "não suavizada" — desliga antialiasing da fonte.
    fonte.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    return fonte


# ═══════════════════════════════════════════════════════════════════
# WIDGETS
# ═══════════════════════════════════════════════════════════════════
class CardItem(QFrame):
    alterado = pyqtSignal()

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.setProperty("papel", "item_card")
        self.setFont(fonte_monoespacada(9))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        linha1 = QHBoxLayout()
        rotulo_texto = QLabel(item["texto"])
        rotulo_texto.setWordWrap(True)
        rotulo_texto.setFont(fonte_monoespacada(9))
        linha1.addWidget(rotulo_texto, stretch=1)

        self.combo_status = QComboBox()
        self.combo_status.setFont(fonte_monoespacada(8))
        for s in STATUS_OPCOES:
            self.combo_status.addItem(STATUS_LABEL[s], s)
        self.combo_status.setCurrentIndex(STATUS_OPCOES.index(item["status"]))
        self.combo_status.currentIndexChanged.connect(self._mudou_status)
        self.combo_status.setFixedWidth(150)
        linha1.addWidget(self.combo_status)
        layout.addLayout(linha1)

        # Nota interna — SEMPRE visível no card (não fica escondida atrás de clique).
        self.campo_nota = QLineEdit(item.get("nota_interna", ""))
        self.campo_nota.setProperty("papel", "nota")
        self.campo_nota.setFont(fonte_monoespacada(8))
        self.campo_nota.setPlaceholderText("Nota interna...")
        self.campo_nota.editingFinished.connect(self._mudou_nota)
        layout.addWidget(self.campo_nota)

        self._atualizar_cor_status()

    def _mudou_status(self):
        self.item["status"] = self.combo_status.currentData()
        self._atualizar_cor_status()
        self.alterado.emit()

    def _mudou_nota(self):
        self.item["nota_interna"] = self.campo_nota.text()
        self.alterado.emit()

    def _atualizar_cor_status(self):
        cor = STATUS_COR[self.item["status"]]
        self.combo_status.setStyleSheet(f"QComboBox {{ color: {cor}; }}")


class PainelFase(QFrame):
    alterado = pyqtSignal()

    def __init__(self, fase: dict, indice: int, parent=None):
        super().__init__(parent)
        self.fase = fase
        self.indice = indice
        self.setProperty("papel", "painel")

        layout_externo = QVBoxLayout(self)
        layout_externo.setContentsMargins(2, 2, 2, 2)
        layout_externo.setSpacing(4)

        cabecalho = QHBoxLayout()
        self.botao_toggle = QToolButton()
        self.botao_toggle.setText("-")
        self.botao_toggle.setFixedWidth(24)
        self.botao_toggle.clicked.connect(self._alternar)
        cabecalho.addWidget(self.botao_toggle)

        titulo = QLabel(fase["titulo"])
        titulo.setProperty("papel", "titulo_fase")
        titulo.setFont(fonte_monoespacada(10, negrito=True))
        cabecalho.addWidget(titulo, stretch=1)

        self.rotulo_progresso = QLabel("")
        self.rotulo_progresso.setFont(fonte_monoespacada(9))
        cabecalho.addWidget(self.rotulo_progresso)
        layout_externo.addLayout(cabecalho)

        self.rotulo_gate = QLabel("BLOQUEADO ATE APROVACAO DA FASE 7 - ESTABILIZACAO")
        self.rotulo_gate.setProperty("papel", "gate")
        self.rotulo_gate.setFont(fonte_monoespacada(8, negrito=True))
        self.rotulo_gate.setVisible(False)
        layout_externo.addWidget(self.rotulo_gate)

        self.corpo = QWidget()
        layout_corpo = QVBoxLayout(self.corpo)
        layout_corpo.setContentsMargins(16, 2, 2, 2)
        layout_corpo.setSpacing(6)
        self.cards = []
        for item in fase["itens"]:
            card = CardItem(item)
            card.alterado.connect(self._propagar)
            layout_corpo.addWidget(card)
            self.cards.append(card)
        layout_externo.addWidget(self.corpo)

        self.atualizar_progresso(fase7_completa=True)

    def _alternar(self):
        visivel = not self.corpo.isVisible()
        self.corpo.setVisible(visivel)
        self.botao_toggle.setText("-" if visivel else "+")

    def _propagar(self):
        self.alterado.emit()

    def progresso(self):
        total = len(self.fase["itens"])
        feitos = sum(1 for i in self.fase["itens"] if i["status"] in ("feito", "na"))
        return feitos, total

    def atualizar_progresso(self, fase7_completa: bool):
        feitos, total = self.progresso()
        marca = " [OK]" if total and feitos == total else ""
        self.rotulo_progresso.setText(f"{feitos:02d}/{total:02d}{marca}")
        mostrar_gate = self.fase.get("gate") and not fase7_completa
        self.rotulo_gate.setVisible(mostrar_gate)


class JanelaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.armazenamento = Armazenamento(ARQUIVO_DADOS)
        self.estado = self.armazenamento.carregar()

        self.setWindowTitle("PLANO DE ELIMINACAO DE CUSTO")
        self.resize(880, 760)

        central = QWidget()
        self.setCentralWidget(central)
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(10, 10, 10, 10)
        raiz.setSpacing(8)

        # ── Cabeçalho / seletor de iniciativa ──
        titulo_id = QLabel("PLAYBOOK :: REDUCAO DE CUSTO POR INTERNALIZACAO")
        titulo_id.setFont(fonte_monoespacada(8))
        titulo_id.setStyleSheet(f"color: {COR_TEXTO_DIM};")
        raiz.addWidget(titulo_id)

        barra_iniciativa = QHBoxLayout()
        self.combo_iniciativas = QComboBox()
        self.combo_iniciativas.setFont(fonte_monoespacada(9))
        self.combo_iniciativas.currentIndexChanged.connect(self._trocar_iniciativa)
        barra_iniciativa.addWidget(self.combo_iniciativas, stretch=1)

        btn_nova = QPushButton("+ NOVA")
        btn_nova.setFont(fonte_monoespacada(9))
        btn_nova.clicked.connect(self._nova_iniciativa)
        barra_iniciativa.addWidget(btn_nova)

        btn_renomear = QPushButton("RENOMEAR")
        btn_renomear.setFont(fonte_monoespacada(9))
        btn_renomear.clicked.connect(self._renomear_iniciativa)
        barra_iniciativa.addWidget(btn_renomear)

        btn_excluir = QPushButton("EXCLUIR")
        btn_excluir.setProperty("papel", "perigo")
        btn_excluir.setFont(fonte_monoespacada(9))
        btn_excluir.clicked.connect(self._excluir_iniciativa)
        barra_iniciativa.addWidget(btn_excluir)
        raiz.addLayout(barra_iniciativa)

        # ── Campos de contexto ──
        painel_meta = QFrame()
        painel_meta.setProperty("papel", "painel")
        grade_meta = QGridLayout(painel_meta)
        grade_meta.setContentsMargins(10, 8, 10, 8)

        def _campo(rotulo_txt, col):
            rotulo = QLabel(rotulo_txt)
            rotulo.setProperty("papel", "rotulo_campo")
            rotulo.setFont(fonte_monoespacada(8))
            grade_meta.addWidget(rotulo, 0, col)
            campo = QLineEdit()
            campo.setFont(fonte_monoespacada(9))
            campo.editingFinished.connect(self._salvar_meta)
            grade_meta.addWidget(campo, 1, col)
            return campo

        self.campo_ferramenta = _campo("FERRAMENTA ATUAL", 0)
        self.campo_solucao = _campo("SOLUCAO INTERNA", 1)
        self.campo_responsavel = _campo("RESPONSAVEL", 2)

        rotulo_custo = QLabel("CUSTO ATUAL (R$/MES)")
        rotulo_custo.setProperty("papel", "rotulo_campo")
        rotulo_custo.setFont(fonte_monoespacada(8))
        grade_meta.addWidget(rotulo_custo, 0, 3)
        self.campo_custo = QDoubleSpinBox()
        self.campo_custo.setFont(fonte_monoespacada(9))
        self.campo_custo.setMaximum(10_000_000)
        self.campo_custo.setDecimals(2)
        self.campo_custo.setPrefix("R$ ")
        self.campo_custo.editingFinished.connect(self._salvar_meta)
        grade_meta.addWidget(self.campo_custo, 1, 3)
        raiz.addWidget(painel_meta)

        # ── KPIs ──
        faixa_kpi = QHBoxLayout()
        self.kpi_fase = self._criar_kpi("FASE ATUAL", faixa_kpi)
        self.kpi_progresso = self._criar_kpi("PROGRESSO GERAL", faixa_kpi)
        self.kpi_fases = self._criar_kpi("FASES CONCLUIDAS", faixa_kpi)
        self.kpi_economia = self._criar_kpi("ECONOMIA ANUAL PROJETADA", faixa_kpi)
        raiz.addLayout(faixa_kpi)

        # ── Lista de fases (scroll) ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.conteudo_scroll = QWidget()
        self.layout_fases = QVBoxLayout(self.conteudo_scroll)
        self.layout_fases.setSpacing(6)
        self.layout_fases.addStretch()
        self.scroll.setWidget(self.conteudo_scroll)
        raiz.addWidget(self.scroll, stretch=1)

        self.paineis_fase = []
        self._carregar_seletor()

    def _criar_kpi(self, rotulo_txt, layout_pai):
        caixa = QFrame()
        caixa.setProperty("papel", "kpi_box")
        v = QVBoxLayout(caixa)
        rotulo = QLabel(rotulo_txt)
        rotulo.setProperty("papel", "kpi_label")
        rotulo.setFont(fonte_monoespacada(7))
        valor = QLabel("--")
        valor.setProperty("papel", "kpi_valor")
        valor.setFont(fonte_monoespacada(13, negrito=True))
        v.addWidget(rotulo)
        v.addWidget(valor)
        layout_pai.addWidget(caixa)
        return valor

    # ── Iniciativas ──
    def _carregar_seletor(self):
        self.combo_iniciativas.blockSignals(True)
        self.combo_iniciativas.clear()
        for ini in self.estado["iniciativas"]:
            self.combo_iniciativas.addItem(ini["nome"], ini["id"])
        self.combo_iniciativas.blockSignals(False)

        if self.estado["iniciativas"]:
            idx = 0
            for i, ini in enumerate(self.estado["iniciativas"]):
                if ini["id"] == self.estado.get("ativa_id"):
                    idx = i
                    break
            self.combo_iniciativas.setCurrentIndex(idx)
            self.estado["ativa_id"] = self.combo_iniciativas.currentData()
            self._renderizar_iniciativa()
        else:
            self._limpar_tela()

    def _iniciativa_ativa(self):
        for ini in self.estado["iniciativas"]:
            if ini["id"] == self.estado.get("ativa_id"):
                return ini
        return None

    def _trocar_iniciativa(self):
        novo_id = self.combo_iniciativas.currentData()
        if novo_id:
            self.estado["ativa_id"] = novo_id
            self._renderizar_iniciativa()

    def _nova_iniciativa(self):
        nome, ok = QInputDialog.getText(self, "Nova iniciativa", "Nome da iniciativa:")
        if ok and nome.strip():
            nova = {
                "id": str(uuid.uuid4()), "nome": nome.strip(), "ferramenta": "",
                "solucao": "", "responsavel": "", "custo_mensal": 0.0,
                "fases": modelo_base_fases(),
            }
            self.estado["iniciativas"].append(nova)
            self.estado["ativa_id"] = nova["id"]
            self.armazenamento.salvar(self.estado)
            self._carregar_seletor()

    def _renomear_iniciativa(self):
        ini = self._iniciativa_ativa()
        if not ini:
            return
        novo_nome, ok = QInputDialog.getText(self, "Renomear iniciativa", "Novo nome:", text=ini["nome"])
        if ok and novo_nome.strip():
            ini["nome"] = novo_nome.strip()
            self.armazenamento.salvar(self.estado)
            self._carregar_seletor()

    def _excluir_iniciativa(self):
        ini = self._iniciativa_ativa()
        if not ini:
            return
        resposta = QMessageBox.question(
            self, "Excluir iniciativa",
            f"Excluir '{ini['nome']}' e todo o progresso? Não é possível desfazer.",
        )
        if resposta == QMessageBox.StandardButton.Yes:
            self.estado["iniciativas"] = [i for i in self.estado["iniciativas"] if i["id"] != ini["id"]]
            self.estado["ativa_id"] = self.estado["iniciativas"][0]["id"] if self.estado["iniciativas"] else None
            self.armazenamento.salvar(self.estado)
            self._carregar_seletor()

    def _limpar_tela(self):
        for p in self.paineis_fase:
            p.setParent(None)
        self.paineis_fase = []
        for kpi in (self.kpi_fase, self.kpi_progresso, self.kpi_fases, self.kpi_economia):
            kpi.setText("--")
        self.campo_ferramenta.clear()
        self.campo_solucao.clear()
        self.campo_responsavel.clear()
        self.campo_custo.setValue(0)

    # ── Meta ──
    def _salvar_meta(self):
        ini = self._iniciativa_ativa()
        if not ini:
            return
        ini["ferramenta"] = self.campo_ferramenta.text()
        ini["solucao"] = self.campo_solucao.text()
        ini["responsavel"] = self.campo_responsavel.text()
        ini["custo_mensal"] = self.campo_custo.value()
        self.armazenamento.salvar(self.estado)
        self._atualizar_kpis(ini)

    # ── Render principal ──
    def _renderizar_iniciativa(self):
        ini = self._iniciativa_ativa()
        if not ini:
            self._limpar_tela()
            return

        self.campo_ferramenta.setText(ini.get("ferramenta", ""))
        self.campo_solucao.setText(ini.get("solucao", ""))
        self.campo_responsavel.setText(ini.get("responsavel", ""))
        self.campo_custo.setValue(ini.get("custo_mensal", 0.0))

        for p in self.paineis_fase:
            p.setParent(None)
        self.paineis_fase = []

        self.layout_fases.takeAt(self.layout_fases.count() - 1)  # remove o stretch
        for idx, fase in enumerate(ini["fases"]):
            painel = PainelFase(fase, idx)
            painel.alterado.connect(lambda i=ini: self._on_item_alterado(i))
            self.layout_fases.addWidget(painel)
            self.paineis_fase.append(painel)
        self.layout_fases.addStretch()

        self._atualizar_kpis(ini)

    def _on_item_alterado(self, ini):
        self.armazenamento.salvar(self.estado)
        self._atualizar_kpis(ini)

    def _atualizar_kpis(self, ini):
        fases = ini["fases"]
        progressos = [p.progresso() for p in self.paineis_fase]
        total_itens = sum(t for _, t in progressos)
        total_feitos = sum(f for f, _ in progressos)
        pct_geral = round(100 * total_feitos / total_itens) if total_itens else 0
        fases_completas = sum(1 for f, t in progressos if t > 0 and f == t)
        fase_atual_idx = next((i for i, (f, t) in enumerate(progressos) if f < t), None)
        fase7_completa = progressos[6][0] == progressos[6][1] if len(progressos) > 6 else True

        for p in self.paineis_fase:
            p.atualizar_progresso(fase7_completa)

        if fase_atual_idx is not None:
            self.kpi_fase.setText(fases[fase_atual_idx]["titulo"].split(". ", 1)[-1][:22])
        else:
            self.kpi_fase.setText("CONCLUIDO")
        self.kpi_progresso.setText(f"{pct_geral}%")
        self.kpi_fases.setText(f"{fases_completas}/{len(fases)}")
        economia = (ini.get("custo_mensal", 0) or 0) * 12
        self.kpi_economia.setText(f"R$ {economia:,.0f}".replace(",", "."))


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(folha_de_estilo())
    janela = JanelaPrincipal()
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
