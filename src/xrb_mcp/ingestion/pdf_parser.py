import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

HEADING = re.compile(
    r"^(?:(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+)?"
    r"(?:abstract|introduction|observations?(?:\s+and\s+data\s+reduction)?|"
    r"data\s+(?:analysis|reduction|availability)|methods?|results?|discussion|conclusions?|"
    r"summary(?:\s+and\s+conclusions)?|references|acknowledg(?:e)?ments)(?:\s*[:.]\s*)?$",
    re.I,
)
NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?|APPENDIX\s+[A-Z]:?)\s+\S.+$", re.I)
PARSER_METHOD = "pymupdf_native_order+styled_sections_v2"


def styled_heading(block: dict) -> str | None:
    """Recognize typeset headings, including separately positioned numbers/titles.

    Requiring bold/italic styling for arbitrary numbered headings avoids interpreting
    plot labels such as '5.5 GHz radio luminosity' as section boundaries.
    """
    spans = [span for line in block["lines"] for span in line["spans"] if span["text"].strip()]
    title = " ".join(span["text"].strip() for span in spans)
    if not title or len(title) > 200:
        return None
    emphasized = all(span["flags"] & (16 | 2) for span in spans)
    if HEADING.fullmatch(title) or (emphasized and NUMBERED_HEADING.fullmatch(title)):
        return title
    return None


@dataclass(frozen=True)
class TextBlock:
    text: str
    page: int
    section: str


@dataclass(frozen=True)
class ParsedPDF:
    blocks: list[TextBlock]
    metadata: dict
    page_count: int


def parse_pdf(path: Path) -> ParsedPDF:
    """Text PDFs only. Pages are 1-based PDF pages, not printed journal page labels."""
    blocks: list[TextBlock] = []
    section = "Front matter"
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("Encrypted PDF requires a decrypted local copy")
        metadata = dict(doc.metadata or {})
        page_count = len(doc)
        for page_number, page in enumerate(doc, start=1):
            # LaTeX PDFs commonly store columns in reading order. Sorting solely by y
            # interleaves their paragraphs and assigns right-column text to wrong sections.
            for block in page.get_text("dict", sort=False)["blocks"]:
                if block["type"] != 0:
                    continue
                heading = styled_heading(block)
                if heading:
                    section = heading
                    continue
                pending: list[str] = []
                for index, pdf_line in enumerate(block["lines"]):
                    line = "".join(span["text"] for span in pdf_line["spans"]).strip()
                    if not line:
                        continue
                    if index == 0 and len(line) < 100 and HEADING.fullmatch(line):
                        if pending:
                            blocks.append(TextBlock(" ".join(pending), page_number, section))
                            pending = []
                        section = line
                    else:
                        pending.append(line)
                if pending:
                    blocks.append(TextBlock(" ".join(pending), page_number, section))
    if not blocks:
        raise ValueError("No extractable text; OCR is not implemented in this framework")
    return ParsedPDF(blocks, metadata, page_count)
