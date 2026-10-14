"""Export GAME_TAG and TAG_* constants from a local Hearthstone Mono assembly.

Uses ilspycmd to read metadata without executing the game assembly. Install the
tool separately, for example: dotnet tool install ilspycmd --tool-path <dir>
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]


def default_ilspy() -> str:
    found = shutil.which("ilspycmd")
    if found:
        return found
    temporary = Path(os.environ.get("TEMP", ".")) / "hs-inspect-tools" / "ilspycmd.exe"
    return str(temporary) if temporary.is_file() else "ilspycmd"


def parse_enum(code: str, name: str) -> dict[str, int]:
    """Accept numeric constants and earlier-member aliases; fail on other syntax."""
    declaration = re.search(r"\bpublic enum " + re.escape(name) + r"\b[^\{]*\{(.*?)\}", code, re.S)
    if not declaration:
        raise ValueError(f"Enum declaration not found: {name}")
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", declaration.group(1), flags=re.S)
    values: dict[str, int] = {}
    current = -1
    for entry in body.split(","):
        entry = entry.strip()
        if not entry:
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)(?:\s*=\s*(-?(?:0x[0-9A-Fa-f]+|[0-9]+)|[A-Za-z_][A-Za-z_0-9]*))?", entry)
        if not match:
            raise ValueError(f"Unsupported constant in {name}: {entry}")
        literal = match.group(2)
        if literal in values:
            current = values[literal]
        else:
            current = int(literal, 16 if "0x" in literal else 10) if literal else current + 1
        if match.group(1) in values:
            raise ValueError(f"Duplicate constant in {name}: {entry}")
        values[match.group(1)] = current
    if not values:
        raise ValueError(f"Empty enum: {name}")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path, default=Path(r"D:\游戏\Hearthstone"))
    parser.add_argument("--assembly", type=Path, help="Override the Assembly-CSharp.dll path.")
    parser.add_argument("--ilspy", default=default_ilspy(), help="Path to ilspycmd executable.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "schema")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    assembly = (args.assembly or args.install_dir / "Hearthstone_Data" / "Managed" / "Assembly-CSharp.dll").resolve()
    if not assembly.is_file():
        parser.error(f"Assembly does not exist: {assembly}")
    if args.workers < 1:
        parser.error("--workers must be positive")
    output_dir = args.output_dir.resolve()
    protected_roots = [args.install_dir.resolve()]
    if assembly.parent.name == "Managed" and assembly.parent.parent.name == "Hearthstone_Data":
        protected_roots.append(assembly.parent.parent.parent)
    for protected_root in protected_roots:
        if output_dir == protected_root or output_dir.is_relative_to(protected_root):
            parser.error("Output must be outside the Hearthstone installation directory.")
    for filename in ("enums.json", "enums.source.json"):
        target = (output_dir / filename).resolve()
        if any(target == root or target.is_relative_to(root) for root in protected_roots):
            parser.error("An output file resolves inside the Hearthstone installation directory.")

    def assembly_hash() -> str:
        with assembly.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()

    hash_before = assembly_hash()

    def run(*arguments: str) -> str:
        try:
            return subprocess.check_output([args.ilspy, *arguments], encoding="utf-8", stderr=subprocess.PIPE)
        except FileNotFoundError:
            parser.error("ilspycmd is unavailable; install it or supply --ilspy.")

    listing = run("-l", "e", str(assembly))
    names = [line[5:] for line in listing.splitlines() if line == "Enum GAME_TAG" or line.startswith("Enum TAG_")]
    if "GAME_TAG" not in names:
        raise ValueError("GAME_TAG not found in assembly")

    def extract(name: str) -> tuple[str, dict[str, int]]:
        return name, parse_enum(run("-t", name, str(assembly)), name)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        enums = dict(executor.map(extract, names))

    hash_after = assembly_hash()
    if hash_before != hash_after:
        raise RuntimeError("Assembly changed during extraction; no output written. Retry when the update has finished.")
    source = {
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "assembly_path": str(assembly),
        "assembly_size_bytes": assembly.stat().st_size,
        "assembly_sha256": hash_after,
        "assembly_sha256_before": hash_before,
        "assembly_sha256_after": hash_after,
        "extractor": "tools/extract_enums.py",
        "method": "Static ILSpy decompilation of GAME_TAG and TAG_* declarations; game assembly is not executed.",
        "ilspy_version": run("--version").strip(),
        "enum_count": len(enums),
        "member_counts": {name: len(values) for name, values in enums.items()},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [("enums.json", enums), ("enums.source.json", source)]:
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"enum_count": len(enums), "game_tag_count": len(enums["GAME_TAG"]), "output_dir": str(output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
