import math
from dataclasses import dataclass

from xrb_mcp.ingestion.pdf_parser import TextBlock


@dataclass(frozen=True)
class Chunk:
    text: str
    section: str
    page_start: int
    page_end: int
    token_count: int


def chunk_blocks(blocks: list[TextBlock], max_words: int = 350) -> list[Chunk]:
    """Pack paragraphs within sections; split oversized paragraphs as a final fallback.

    token_count is a documented whitespace-word estimate (ceil(words * 1.34)).
    Embedding backends independently handle their tokenizer window limits.
    """
    if max_words < 1:
        raise ValueError("max_words must be positive")
    output: list[Chunk] = []
    pending: list[TextBlock] = []
    count = 0

    def flush() -> None:
        nonlocal count
        if pending:
            output.append(
                Chunk(
                    text="\n\n".join(b.text for b in pending),
                    section=pending[0].section,
                    page_start=pending[0].page,
                    page_end=pending[-1].page,
                    token_count=math.ceil(count * 1.34),
                )
            )
            pending.clear()
            count = 0

    for block in blocks:
        words = block.text.split()
        if not words:
            continue
        if pending and (block.section != pending[0].section or count + len(words) > max_words):
            flush()
        if len(words) > max_words:
            for start in range(0, len(words), max_words):
                part = words[start : start + max_words]
                pending.append(TextBlock(" ".join(part), block.page, block.section))
                count = len(part)
                flush()
        else:
            pending.append(block)
            count += len(words)
    flush()
    return output
