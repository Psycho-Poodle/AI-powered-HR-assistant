"""Bounded plain-text Markdown chunks using the embedding model's tokenizer."""

import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

CHUNKER_VERSION = "markdown-nfc-token200-overlap60-v1"
MAX_SOURCE_BYTES = 1024 * 1024


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "svg"}:
            self.blocked.append(tag)
        elif not self.blocked:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.blocked and tag == self.blocked[-1]:
            self.blocked.pop()
        elif not self.blocked:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def plain_markdown(source: str) -> str:
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Markdown source exceeds 1 MiB")
    source = unicodedata.normalize(
        "NFC", source.replace("\r\n", "\n").replace("\r", "\n")
    )
    parser = PlainText()
    parser.feed(source)
    parser.close()
    plain = "".join(parser.parts)
    plain = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", plain)
    return "".join(
        c for c in plain if c in "\n\t" or not unicodedata.category(c).startswith("C")
    ).strip()


@dataclass(frozen=True)
class Chunk:
    number: int
    text: str
    token_count: int


def chunk_markdown(
    source: str, tokenizer, max_tokens: int = 200, overlap: int = 60
) -> list[Chunk]:
    if not 0 <= overlap < max_tokens <= 254:
        raise ValueError("Invalid chunk token budget or overlap")
    plain = plain_markdown(source)
    if not plain:
        raise ValueError("Markdown source has no usable text")
    tokens = tokenizer(
        plain,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
        verbose=False,
    )["offset_mapping"]
    if not tokens:
        raise ValueError("Markdown source has no encodable text")
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        while end > start:
            excerpt = plain[tokens[start][0] : tokens[end - 1][1]].strip()
            count = len(tokenizer.encode(excerpt, add_special_tokens=False))
            if excerpt and count <= max_tokens:
                break
            end -= 1
        if end == start:
            raise ValueError("Cannot fit text inside chunk token budget")
        chunks.append(Chunk(len(chunks), excerpt, count))
        if end == len(tokens):
            break
        start = max(start + 1, end - overlap)
    return chunks
