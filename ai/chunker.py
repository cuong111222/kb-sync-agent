import re
from typing import List, Dict, Any


class MarkdownChunker:
    """
    Heading-aware Markdown chunker designed for technical support articles.
    Preserves document title and source URL in each chunk for precise RAG citations.
    """

    def __init__(self, max_chars: int = 1500, overlap_chars: int = 200):
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk_document(self, markdown_text: str, metadata: Dict[str, Any]) -> List[str]:
        """
        Splits markdown text into semantic chunks based on headings and paragraphs.
        Prepends metadata header to each chunk.
        """
        doc_header = (
            f"Title: {metadata.get('title', 'OptiSigns Guide')}\n"
            f"Article URL: {metadata.get('html_url', '')}\n\n"
        )

        # Split text by Markdown headers (## or ###)
        sections = re.split(r"(?m)(?=^#{1,3}\s+)", markdown_text)
        chunks: List[str] = []

        for section in sections:
            section = section.strip()
            if not section:
                continue

            if len(section) <= self.max_chars:
                chunks.append(doc_header + section)
            else:
                # Sub-split large sections by paragraphs
                paragraphs = section.split("\n\n")
                current_chunk = ""

                for p in paragraphs:
                    p = p.strip()
                    if not p:
                        continue

                    if len(current_chunk) + len(p) + 2 <= self.max_chars:
                        current_chunk = f"{current_chunk}\n\n{p}".strip()
                    else:
                        if current_chunk:
                            chunks.append(doc_header + current_chunk)
                        # Start new chunk with overlap if possible
                        current_chunk = p

                if current_chunk:
                    chunks.append(doc_header + current_chunk)

        return chunks if chunks else [doc_header + markdown_text]
