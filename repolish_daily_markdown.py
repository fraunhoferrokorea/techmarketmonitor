"""Strip redundant Fraunhofer phrasing from existing daily markdown files."""
from __future__ import annotations

import re
from pathlib import Path

from src.summarizer import strip_implicit_fraunhofer_subject

_DAILY_DIR = Path(__file__).resolve().parent / "output" / "daily"
_RD_TABLE_ROW = re.compile(r"^\| \*\*\d/5\*\* \|")
_RD_FIELD = re.compile(r"^(\s*- \*\*(?:제안 R&D 영역|접근 전략):\*\*\s*)(.+)$")
_ACCESS_IN_BULLET = re.compile(r"( \| 접근: )(.+?)( \()")


def _clean_field(body: str) -> str:
    return strip_implicit_fraunhofer_subject(body.strip())


def repolish_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    lines: list[str] = []
    changed = False

    for line in original.splitlines():
        new_line = line
        if _RD_TABLE_ROW.match(line):
            parts = line.split("|")
            if len(parts) >= 6:
                cleaned = _clean_field(parts[4])
                if cleaned != parts[4].strip():
                    parts[4] = f" {cleaned} "
                    new_line = "|".join(parts)
        else:
            field_match = _RD_FIELD.match(line)
            if field_match:
                prefix, body = field_match.groups()
                cleaned = _clean_field(body)
                if cleaned != body.strip():
                    new_line = f"{prefix}{cleaned}"
            elif "Fraunhofer" in line and "프라운호퍼 협력 관점" not in line:
                if line.lstrip().startswith("- "):
                    indent = line[: len(line) - len(line.lstrip())]
                    body = line.lstrip()[2:]
                    cleaned = _clean_field(body)
                    if cleaned != body.strip():
                        new_line = f"{indent}- {cleaned}"
                else:
                    access_match = _ACCESS_IN_BULLET.search(line)
                    if access_match:
                        prefix, body, suffix = access_match.groups()
                        cleaned = _clean_field(body)
                        if cleaned != body.strip():
                            new_line = _ACCESS_IN_BULLET.sub(
                                f"{prefix}{cleaned}{suffix}",
                                line,
                                count=1,
                            )
        if new_line != line:
            changed = True
        lines.append(new_line)

    if changed:
        path.write_text("\n".join(lines) + ("\n" if original.endswith("\n") else ""), encoding="utf-8")
    return changed


def main() -> None:
    updated = 0
    for path in sorted(_DAILY_DIR.glob("daily_*.md")):
        if repolish_file(path):
            print(f"updated {path.name}")
            updated += 1
        else:
            print(f"unchanged {path.name}")
    print(f"done: {updated} file(s) updated")


if __name__ == "__main__":
    main()
