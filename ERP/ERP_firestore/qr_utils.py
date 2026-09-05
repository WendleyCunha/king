"""
Geração de QR codes.

- gerar_qrcode_produto: um QR por PRODUTO (cadastro), aponta pro SKU.
- gerar_qrcode_item_venda: um QR único por ITEM VENDIDO, usado para
  rastrear aquela peça física específica (não o produto genérico).
"""
import os
import qrcode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QRCODE_DIR = os.path.join(BASE_DIR, "data", "qrcodes")
os.makedirs(QRCODE_DIR, exist_ok=True)


def _gerar_arquivo(conteudo: str, nome_arquivo: str) -> str:
    img = qrcode.make(conteudo)
    caminho = os.path.join(QRCODE_DIR, nome_arquivo)
    img.save(caminho)
    return caminho


def gerar_qrcode_produto(sku: str) -> str:
    conteudo = f"PRODUTO:{sku}"
    return _gerar_arquivo(conteudo, f"produto_{sku}.png")


def gerar_qrcode_item_venda(venda_id: int, sku: str) -> str:
    """Cada venda gera um QR próprio e único para controle daquele item físico."""
    conteudo = f"ITEM:{venda_id}:{sku}"
    return _gerar_arquivo(conteudo, f"item_venda_{venda_id}.png")
