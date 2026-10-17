"""House rule (Jim, H-14): section numbers are written 1, 2, 3 ... never 01, 02, 03.

It covers only how section numbers are written in the website and its docs; what a section shows
and how it is calculated stay with whoever owns it. When a merge brings back "01 ·", this fails.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"node_modules", "dist"}

# A zero-padded section number: "01 &middot;" / "01 ·" (a section label), "section 04" (a reference),
# "<b>05 " (a numbered list of sections). Times (06:15) and dates (2026-10-05) do not match.
PADDED = [
    re.compile(r"(?<![\d:./-])0[1-9]\s*(?:&middot;|·)"),
    re.compile(r"\b[Ss]ection\s+0[1-9]\b"),
    re.compile(r"<b>0[1-9]\s"),
]


def website_files():
    files = list((ROOT / "app").rglob("*.html")) + list((ROOT / "app" / "frontend" / "src").rglob("*.jsx"))
    return [f for f in files if not SKIP & set(f.relative_to(ROOT).parts)]


def padded_numbers(text):
    """(line number, text) of every zero-padded section number in text."""
    return [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1)
            if any(p.search(line) for p in PADDED)]


def test_known_answers():
    assert padded_numbers('<div class="eyebrow">01 &middot; Station status</div>')
    assert padded_numbers("02 · Today at each station")
    assert padded_numbers("priority in the van plan (section 04)")
    assert padded_numbers("<li><b>05 Tomorrow's bike plan</b>")
    assert not padded_numbers('<div class="eyebrow">1 &middot; Station status</div>')
    assert not padded_numbers("08:15 · MORNING")                     # a time, not a section
    assert not padded_numbers("Simulated 2026-10-05 · one reading")   # a date
    assert not padded_numbers("Week 2 · policy")


def test_there_are_files_to_check():
    names = {f.name for f in website_files()}
    assert {"index.html", "home.html"} <= names


@pytest.mark.parametrize("path", website_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_section_numbers_have_no_leading_zero(path):
    bad = padded_numbers(path.read_text(encoding="utf-8"))
    assert not bad, f"write section numbers as 1, 2, 3 (not 01, 02, 03): {bad[:5]}"
