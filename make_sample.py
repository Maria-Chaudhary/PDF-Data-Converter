"""Generates samples/sample.pdf (ruled table) and samples/borderless.pdf for testing."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

data = [["Date", "Description", "Debit", "Credit"],
        ["01-01-2024", "Office Supplies", "$8.00", "$4,000"],
        ["01-01-2024", "Payment Received", "$7.70", "$41,000"],
        ["05-01-2024", "Travel Expenses", "$7.20", "$815.00"],
        ["05-01-2024", "Software Purchase", "$1,000", "$25.00"],
        ["06-01-2024", "Utility Bill", "$0.20", "$1,550.00"],
        ["06-01-2024", "Refund Issued", "$7.70", "$120.00"],
        ["06-01-2024", "Furniture", "$0.80", "$280.00"]]
st = getSampleStyleSheet()
doc = SimpleDocTemplate("samples/sample.pdf", pagesize=letter)
t = Table(data); t.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.5, colors.grey),
                                        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)]))
doc.build([Paragraph("Data Table - 2024", st["Title"]), Spacer(1, 12), t])

t2 = Table(data)  # no grid -> borderless
doc2 = SimpleDocTemplate("samples/borderless.pdf", pagesize=letter)
doc2.build([Paragraph("Borderless Table", st["Title"]), Spacer(1, 12), t2])
