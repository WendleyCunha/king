import os
import datetime
from fpdf import FPDF
from erp.db import get_db, agora_iso, proximo_numero
from erp.services import empresa_service

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTAS_DIR = os.path.join(BASE_DIR, "data", "notas")
os.makedirs(NOTAS_DIR, exist_ok=True)

COL_NOTAS = "notas_fiscais"
COL_PEDIDOS = "pedidos"
COL_CARGAS = "cargas"


def _gerar_pdf(numero: str, pedido: dict, empresa: dict) -> str:
    """
    PDF de controle interno. NÃO é uma NF-e válida perante a SEFAZ — para
    isso é preciso um provedor homologado (Focus NFe, eNotas, TecnoSpeed).
    Quando contratado, troca-se só o corpo desta função.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "NOTA FISCAL (controle interno)", ln=True)
    pdf.set_font("Helvetica", "", 11)
    if empresa:
        pdf.cell(0, 8, f"{empresa.get('razao_social','')} - CNPJ {empresa.get('cnpj','')}", ln=True)
        pdf.cell(0, 8, f"{empresa.get('endereco','')}, {empresa.get('cidade','')}/{empresa.get('estado','')}", ln=True)
    pdf.ln(4)
    pdf.cell(0, 8, f"Número: {numero}", ln=True)
    pdf.cell(0, 8, f"Pedido: {pedido['numero']}", ln=True)
    pdf.cell(0, 8, f"Cliente: {pedido['cliente_nome']}", ln=True)
    pdf.cell(0, 8, f"Produto: {pedido['produto_nome']} (SKU {pedido['produto_sku']})", ln=True)
    pdf.cell(0, 8, f"Valor: R$ {pedido['valor']:.2f}", ln=True)
    pdf.cell(0, 8, f"Forma de pagamento: {pedido['forma_pagamento']}", ln=True)
    pdf.cell(0, 8, f"Emitida em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)

    caminho = os.path.join(NOTAS_DIR, f"{numero}.pdf")
    pdf.output(caminho)
    return caminho


def faturar_pedido(numero_pedido: str) -> dict:
    db = get_db()
    pedido_ref = db.collection(COL_PEDIDOS).document(numero_pedido)
    pedido_doc = pedido_ref.get()
    if not pedido_doc.exists:
        raise ValueError("Pedido não encontrado.")
    pedido = pedido_doc.to_dict()
    if pedido["status"] != "EM_ROTA":
        raise ValueError("Só é possível faturar pedidos cuja carga já foi finalizada (motorista atribuído).")
    if pedido.get("nota_fiscal_numero"):
        raise ValueError("Este pedido já foi faturado.")

    numero_nota = proximo_numero("notas_fiscais", "NF")
    empresa = empresa_service.obter_dados_empresa()
    caminho_pdf = _gerar_pdf(numero_nota, pedido, empresa)

    nota = {
        "numero": numero_nota, "pedido_numero": numero_pedido, "valor": pedido["valor"],
        "pdf_path": caminho_pdf, "emitida_em": agora_iso(),
    }
    db.collection(COL_NOTAS).document(numero_nota).set(nota)
    pedido_ref.update({"status": "FATURADO", "nota_fiscal_numero": numero_nota, "atualizado_em": agora_iso()})
    return nota


def faturar_carga(carga_id: str) -> list:
    db = get_db()
    carga_doc = db.collection(COL_CARGAS).document(carga_id).get()
    if not carga_doc.exists:
        raise ValueError("Carga não encontrada.")
    carga = carga_doc.to_dict()
    if carga["status"] != "FINALIZADA":
        raise ValueError("Só é possível faturar cargas finalizadas (com motorista atribuído).")

    notas = []
    for numero in carga.get("pedidos", []):
        pedido_doc = db.collection(COL_PEDIDOS).document(numero).get()
        if pedido_doc.exists and not pedido_doc.to_dict().get("nota_fiscal_numero"):
            notas.append(faturar_pedido(numero))
    return notas


def listar_notas_por_dia(data: datetime.date = None) -> list:
    docs = get_db().collection(COL_NOTAS).stream()
    out = [d.to_dict() for d in docs]
    if data:
        out = [
            n for n in out
            if datetime.datetime.fromisoformat(n["emitida_em"]).date() == data
        ]
    return sorted(out, key=lambda n: n["emitida_em"], reverse=True)
