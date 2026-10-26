"""Stable identifiers and text spans for Beancount directives."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from beancount.core.data import Transaction
from beancount.parser import parser


@dataclass(frozen=True, slots=True)
class EntryId:
    """Stable identifier: file, starting line, directive text hash."""

    file: str
    line: int
    hash: str


@dataclass(frozen=True, slots=True)
class DirectiveSpan:
    """A directive's identifier, text, and offsets in its file."""

    entry_id: EntryId
    text: str
    start_offset: int
    end_offset: int


def sha256_text(text: str) -> str:
    """Return the hexadecimal SHA-256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_directive_spans(file: Path, text: str) -> list[DirectiveSpan]:
    """Split a Beancount file into directive spans.

    A directive starts at a non-empty, non-indented line and ends immediately
    before the next such line.
    """
    lines = text.splitlines(keepends=True)
    line_offsets: list[int] = []
    starts: list[int] = []
    offset = 0
    for index, line in enumerate(lines):
        line_offsets.append(offset)
        content = line.rstrip("\r\n")
        if content.strip() and not content[0].isspace():
            starts.append(index)
        offset += len(line)

    spans: list[DirectiveSpan] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        start_offset = line_offsets[start]
        end_offset = line_offsets[end] if end < len(lines) else len(text)
        span_text = text[start_offset:end_offset]
        spans.append(
            DirectiveSpan(
                entry_id=EntryId(
                    file=str(file),
                    line=start + 1,
                    hash=sha256_text(span_text),
                ),
                text=span_text,
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
    return spans


def find_span(spans: list[DirectiveSpan], line: int) -> DirectiveSpan | None:
    """Find the span whose directive starts at ``line``."""
    for span in spans:
        if span.entry_id.line == line:
            return span
    return None


def entry_id_to_dict(entry_id: EntryId) -> dict[str, str | int]:
    """Render an entry identifier as a JSON-compatible dictionary."""
    return {
        "file": entry_id.file,
        "line": entry_id.line,
        "hash": entry_id.hash,
    }


def is_transaction_span(span: DirectiveSpan) -> bool:
    """Return whether the span contains a transaction directive."""
    entries, _, _ = parser.parse_string(span.text)
    return any(isinstance(entry, Transaction) for entry in entries)


def replace_span(text: str, span: DirectiveSpan, new_text: str) -> str:
    """Replace a span, preserving the original trailing blank lines."""
    replacement = new_text.strip("\n")
    if not replacement:
        raise ValueError("La nuova direttiva è vuota.")
    replacement += "\n"

    original_lines = span.text.splitlines(keepends=True)
    last_content = -1
    for index, line in enumerate(original_lines):
        if line.strip():
            last_content = index
    trailing = "".join(original_lines[last_content + 1 :])
    return text[: span.start_offset] + replacement + trailing + text[span.end_offset :]


def delete_span(text: str, span: DirectiveSpan) -> str:
    """Remove a span from its file."""
    return text[: span.start_offset] + text[span.end_offset :]
