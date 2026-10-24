from ai.chunker import MarkdownChunker


def test_chunker_preserves_metadata_and_sections():
    chunker = MarkdownChunker(max_chars=300, overlap_chars=50)

    sample_md = """
## Section 1: Overview
This is a short overview section of the tutorial.

## Section 2: Instructions
Here are detailed instructions for configuring your device. Make sure you connect to the internet.
"""
    meta = {
        "title": "YouTube Setup Guide",
        "html_url": "https://support.example.com/youtube",
    }

    chunks = chunker.chunk_document(sample_md, meta)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert "Title: YouTube Setup Guide" in chunk
        assert "Article URL: https://support.example.com/youtube" in chunk
