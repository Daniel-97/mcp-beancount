"""Stable identifiers and text spans for Beancount directives."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from beancount.core.data import Directive, Transaction
from beancount.parser import parser

NON_TRANSACTION_DIRECTIVES = frozenset(
    {
        "open",
        "close",
        "balance",
        "pad",
        "note",
        "document",
        "price",
        "event",
        "query",
        "custom",
        "commodity",
    }
)
_DIRECTIVE_HEAD_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\S+)")


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


def split_lines(text: str) -> list[str]:
    """Split on ``\\n`` only, keeping line endings.

    Beancount numbers lines by ``\\n``. ``str.splitlines`` also breaks on
    ``\\r``, form feed, U+2028 and others, which may legally appear inside
    strings and would shift every following line number.
    """
    lines = text.split("\n")
    last = lines.pop()
    result = [line + "\n" for line in lines]
    if last:
        result.append(last)
    return result


def span_matches_directive(span: DirectiveSpan, directive: Directive) -> bool:
    """Return whether ``span`` textually starts the given parsed directive.

    Spans and directives are paired by line number. This cheap check on the
    date and keyword refuses a pairing that would attach an identifier to the
    text of a different directive.
    """
    match = _DIRECTIVE_HEAD_RE.match(span.text)
    if match is None or match[1] != directive.date.isoformat():
        return False
    if isinstance(directive, Transaction):
        return match[2] not in NON_TRANSACTION_DIRECTIVES
    return bool(match[2] == type(directive).__name__.lower())


def extract_directive_spans(file: Path, text: str) -> list[DirectiveSpan]:
    """Split a Beancount file into directive spans.

    A directive starts at a non-empty, non-indented line and ends immediately
    before the next such line. Lines inside multiline strings are kept together.
    """
    lines = split_lines(text)
    line_offsets: list[int] = []
    starts: list[int] = []
    offset = 0
    for index, (line, in_string) in enumerate(source_lines(lines)):
        line_offsets.append(offset)
        content = line.rstrip("\r\n")
        if not in_string and content.strip() and not content[0].isspace():
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


def replacement_text(span: DirectiveSpan, new_text: str) -> str:
    """Return ``new_text`` followed by the span's original trailing blank lines."""
    replacement = new_text.strip("\n")
    if not replacement:
        raise ValueError("La nuova direttiva è vuota.")

    original_lines = split_lines(span.text)
    last_content = -1
    for index, line in enumerate(original_lines):
        if line.strip():
            last_content = index
    trailing = "".join(original_lines[last_content + 1 :])
    return replacement + "\n" + trailing


def replace_span(text: str, span: DirectiveSpan, new_text: str) -> str:
    """Replace a span, preserving the original trailing blank lines."""
    return text[: span.start_offset] + replacement_text(span, new_text) + text[span.end_offset :]


def delete_span(text: str, span: DirectiveSpan) -> str:
    """Remove a span from its file."""
    return text[: span.start_offset] + text[span.end_offset :]


def source_lines(lines: list[str]) -> Iterator[tuple[str, bool]]:
    """Track quoted strings across lines; comments cannot open strings."""
    in_string = False
    escaped = False
    for line in lines:
        starts_in_string = in_string
        # Org-mode headings and other unrecognized top-level text are comments
        # in Beancount; unmatched quotes there cannot open a multiline string.
        if (
            not in_string
            and line
            and not line[0].isspace()
            and re.match(
                r"(?:\d{4}-\d{2}-\d{2}\s|option\b|include\b|plugin\b|"
                r"pushtag\b|poptag\b|pushmeta\b|popmeta\b)",
                line,
            )
            is None
        ):
            yield line, False
            continue
        for char in line:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == ";":
                break
            elif char == '"':
                in_string = True
        yield line, starts_in_string
