"""Suno-style lyrics → YuE2's section format.

Suno lyrics mix section tags ("[Verse 1 - fast chat]", "[Chorus x2]") with production notes in brackets
("[Horn solo - 8 bars, mellow]"). Suno reads the notes; YuE2 does not, and in the bake-off leaving them in made
it follow the style worse (and once run to the 6-minute cap). So: tags normalised to [Intro] [Verse] [Pre-Chorus]
[Chorus] [Bridge] [Interlude] [Outro], notes dropped, instrumental passages kept as empty sections.
Copied from yue-bakeoff/harness/lyrics.py.
"""
from __future__ import annotations

import re

KINDS = [  # (pattern on the lowercased label, YuE2 tag); first match wins
    (r"pre[- ]?chorus|pre[- ]?hook", "Pre-Chorus"),
    (r"chorus|hook|refrain", "Chorus"),
    (r"verse|chat|toast|rap", "Verse"),
    (r"bridge", "Bridge"),
    (r"intro", "Intro"),
    (r"outro|coda|end", "Outro"),
    (r"break|solo|drop|instrumental|interlude|dub", "Interlude"),
]


def section_kind(label: str) -> str | None:
    l = label.lower()
    for pat, kind in KINDS:
        if re.search(pat, l):
            return kind
    return None


def parse(raw: str) -> list[tuple[str, list[str]]]:
    """[(kind, sung lines)]; bracket lines that are not section labels are production notes (dropped)."""
    out: list[tuple[str, list[str]]] = []
    for line in raw.splitlines():
        s = line.strip()
        m = re.fullmatch(r"\[([^\]]+)\]", s)
        if m:
            kind = section_kind(m.group(1))
            # "[Brass break 16 bars, building]" is both a note and an instrumental section → Interlude
            # a generic note right after an empty section label describes that section ("[Outro]" then
            # "[Brass stabs, drums drop out]"), it is not a new one
            if kind and not (kind == "Interlude" and out and not out[-1][1]):
                out.append((kind, []))
            continue
        if not s:
            continue
        s = re.sub(r"\[[^\]]*\]", "", s).strip()  # inline notes
        if not s:
            continue
        if not out:
            out.append(("Verse", []))
        out[-1][1].append(s)
    return out


def to_yue2(raw: str) -> str:
    return "\n\n".join(f"[{k}]" + ("\n" + "\n".join(ls) if ls else "") for k, ls in parse(raw))
