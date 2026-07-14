from __future__ import annotations

import re
import sys
from importlib import metadata


def parse_requirement(line: str) -> tuple[str, str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    match = re.match(r"^([A-Za-z0-9_.\-]+)\s*(>=|==|<=|>|<)?\s*([0-9][0-9A-Za-z.\-]*)?$", line)
    if not match:
        return None
    name, op, version = match.groups()
    return name, op or "", version or ""


def version_tuple(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else (0,)


def satisfies(installed: str, op: str, required: str) -> bool:
    if not op:
        return True
    iv, rv = version_tuple(installed), version_tuple(required)
    if op == ">=":
        return iv >= rv
    if op == "==":
        return iv == rv
    if op == "<=":
        return iv <= rv
    if op == ">":
        return iv > rv
    if op == "<":
        return iv < rv
    return True


def main(requirements_path: str) -> int:
    with open(requirements_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        parsed = parse_requirement(line)
        if parsed is None:
            continue
        name, op, required_version = parsed
        try:
            installed_version = metadata.version(name)
        except metadata.PackageNotFoundError:
            print(f"MISSING: {name}")
            return 1
        if not satisfies(installed_version, op, required_version):
            print(f"OUTDATED: {name} (have {installed_version}, need {op}{required_version})")
            return 1

    return 0


if __name__ == "__main__":
    req_path = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
    sys.exit(main(req_path))
