"""Find bundled tool packages without importing their UI."""

from __future__ import annotations

import ast
from pathlib import Path

from core import paths
from core.marketplace import dirs


def bundled_modules_root() -> Path:
    return Path(paths.resource_path("modules"))


def _register_dict(init_path: Path) -> dict | None:
    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    except Exception:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if name != "register" or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Dict):
            out = {}
            for key, val in zip(arg.keys, arg.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if isinstance(val, ast.Constant):
                    out[key.value] = val.value
            if out.get("name"):
                return out
    return None


def iter_tool_packages(root: Path):
    if not root.exists():
        return
    for init in root.rglob("__init__.py"):
        if "__pycache__" in init.parts:
            continue
        meta = _register_dict(init)
        if not meta:
            continue
        package_dir = init.parent
        try:
            rel = package_dir.relative_to(root).as_posix()
        except ValueError:
            continue
        yield {
            "id": dirs.slug(meta.get("name") or package_dir.name),
            "root": package_dir,
            "relpath": rel,
            "meta": meta,
        }


def list_bundled_tools() -> list[dict]:
    return list(iter_tool_packages(bundled_modules_root()))
