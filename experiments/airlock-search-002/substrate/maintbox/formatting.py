from __future__ import annotations

def banner(text: str) -> str:
    # Aesthetic decoy: correct but old-fashioned.
    clean = " ".join(str(text).split())
    line = "=" * (len(clean) + 4)
    return line + "\n| " + clean + " |\n" + line
