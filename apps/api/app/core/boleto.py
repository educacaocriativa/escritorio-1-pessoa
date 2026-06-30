"""Geração de um PDF de boleto (stub: layout de boleto sem registro bancário real).

Quando integrar um gateway (Asaas/Mercado Pago), substituir pela linha digitável/código de
barras reais retornados pela API. Por ora gera um documento legível com os dados da cobrança.
"""
from __future__ import annotations

from datetime import date

from fpdf import FPDF


def _brl(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def generate_boleto_pdf(
    *, payee: str, payer: str, amount_cents: int, due_date: date, code: str
) -> bytes:
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "BOLETO DE PAGAMENTO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(120, 68, 248)
    pdf.set_line_width(0.8)
    pdf.line(15, 30, 195, 30)
    pdf.ln(6)

    def row(label: str, value: str) -> None:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(45, 8, label)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 8, value, new_x="LMARGIN", new_y="NEXT")

    row("Beneficiário", payee or "-")
    row("Pagador", payer or "-")
    row("Vencimento", due_date.strftime("%d/%m/%Y"))
    row("Valor", _brl(amount_cents))
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 8, "Linha digitável", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Courier", "B", 12)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 8, code or "")
    pdf.ln(10)

    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(150, 150, 150)
    pdf.multi_cell(
        0, 6,
        "Documento gerado automaticamente pelo e1p. A compensação do pagamento é reconhecida "
        "automaticamente pelo gateway (Pix/cartão/boleto) e refletida no Financeiro.",
    )
    return bytes(pdf.output())
