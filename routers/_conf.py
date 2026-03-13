"""Shared helpers for reading/writing legacy .conf files."""
from pathlib import Path
from typing import Dict


def read_conf(path: Path) -> Dict[str, str]:
    d: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def write_conf(path: Path, data: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{k}="{v}"' for k, v in data.items() if v is not None]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_true(v: str | None) -> bool:
    return (v or "").strip().lower() == "true"


def bool_str(v: bool) -> str:
    return "true" if v else "false"
