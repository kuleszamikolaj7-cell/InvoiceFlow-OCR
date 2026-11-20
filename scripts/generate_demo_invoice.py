"""Generate a fully fictional two-page PDF fixture for OCR demos.

Optional dependency: pip install reportlab
Usage: python scripts/generate_demo_invoice.py
"""
from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'examples' / 'demo_invoice.pdf'


def draw_page(pdf, page, entries):
    width, height = A4
    pdf.setFillColorRGB(0.12, 0.19, 0.33)
    pdf.setFont('Helvetica-Bold', 22)
    pdf.drawString(30, height - 75, 'InvoiceFlow OCR  -  DEMO')
    pdf.setFillColorRGB(0.35, 0.35, 0.35)
    pdf.setFont('Helvetica', 11)
    pdf.drawString(32, height - 100, 'Fictional sample - not a real invoice')
    pdf.drawString(32, height - 122, f'Sample invoice IF-2026-TEST-01 | Page {page} of 2')
    pdf.drawString(32, height - 180, 'Seller: Example Shop (fictional)')
    pdf.drawString(32, height - 197, 'Buyer: Demo Customer (fictional)')
    pdf.setStrokeColorRGB(0.72, 0.77, 0.84)
    pdf.line(30, height - 253, width - 30, height - 253)
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(32, 570, 'Product')
    pdf.drawString(450, 570, 'Qty')
    pdf.drawString(532, 570, 'Total')
    pdf.line(30, 560, width - 30, 560)
    pdf.setFont('Helvetica', 12)
    for row_index, (product, qty, total) in enumerate(entries):
        baseline = 545 - 18 * row_index
        pdf.drawString(35, baseline, product)
        pdf.drawString(450, baseline, qty)
        pdf.drawString(532, baseline, total)
        pdf.setStrokeColorRGB(0.9, 0.92, 0.95)
        pdf.line(30, baseline - 9, width - 30, baseline - 9)
    pdf.setFont('Helvetica', 10)
    pdf.setFillColorRGB(0.35, 0.35, 0.35)
    pdf.drawString(32, 110, 'All data on this PDF is synthetic and safe to publish.')
    pdf.drawString(32, 95, 'The demo uses a fixed-coordinate OCR template, not universal table detection.')
    pdf.showPage()


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    pdf = Canvas(str(TARGET), pagesize=A4)
    draw_page(pdf, 1, [('Product A', '2', '15.50'), ('Product B', '1', '12.00')])
    draw_page(pdf, 2, [('Product C', '1', '9.90')])
    pdf.save()
    print(TARGET)


if __name__ == '__main__':
    main()
