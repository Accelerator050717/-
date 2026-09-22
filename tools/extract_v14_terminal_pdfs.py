"""Extract text from retained PDFs for the small v14 field check (needs pypdf)."""
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/private/universe/v14_public_sources'

for name in ('twtr_merger_issuer_pdf.pdf', 'sivb_cancellation_issuer_pdf.pdf'):
    reader = PdfReader(RAW / name)
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    target = RAW / (name + '.extracted.txt')
    if target.exists() and target.read_text(encoding='utf-8') != text:
        raise ValueError(f'Extraction changed; preserve old derivative: {name}')
    target.write_text(text, encoding='utf-8')
    print(name, len(reader.pages), 'pages; text extraction verified')
