#!/usr/bin/env python3
"""Add Google-style docstrings to Python functions/classes missing them.

Usage:
    python scripts/add_google_docstrings.py [--dry-run] [paths...]

If no paths given, walks src/margin/ tests/ alembic/ by default.
"""

from __future__ import annotations

import ast
import os
import re
import sys


def _get_indent(line: str) -> str:
    """Return the leading whitespace of a line."""
    m = re.match(r"^(\s*)", line)
    return m.group(1) if m else ""


def _has_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """Return True when the node body starts with a string expression."""
    if not node.body:
        return False
    first = node.body[0]
    return isinstance(first, ast.Expr) and isinstance(
        first.value, ast.Constant
    )


def _flat_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str, str]]:
    """Return list of (arg_name, type_hint_str, default_str)."""
    args: list[tuple[str, str, str]] = []
    defaults_offset = len(node.args.args) - len(node.args.defaults)

    for i, arg in enumerate(node.args.args):
        name = arg.arg
        if name in ("self", "cls"):
            continue
        type_hint = ""
        if arg.annotation:
            try:
                type_hint = ast.unparse(arg.annotation)
            except Exception:
                type_hint = ""
        default_str = ""
        if i >= defaults_offset:
            idx = i - defaults_offset
            if idx < len(node.args.defaults):
                try:
                    d = ast.unparse(node.args.defaults[idx])
                    default_str = f" (default: {d})"
                except Exception:
                    default_str = ""
        args.append((name, type_hint, default_str))
    return args


def _return_type(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return the return-type annotation string, or empty when absent/None."""
    if node.returns:
        try:
            rt = ast.unparse(node.returns)
            return rt if rt != "None" else ""
        except Exception:
            return ""
    return ""


def _build_func_docstring(
    node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str
) -> list[str]:
    """Build Google-style docstring lines for a function/method."""
    name = node.name
    is_dunder = name.startswith("__") and name.endswith("__")

    # Build brief summary
    if name == "__init__":
        summary = "Initialize instance."
    elif is_dunder:
        summary = f"{name}."
    else:
        summary = f"{name}."

    lines: list[str] = [f'{indent}"""{summary}']
    params = _flat_args(node)

    if params:
        lines.append(f"{indent}")
        lines.append(f"{indent}Args:")
        for arg_name, arg_type, default_str in params:
            type_tag = f" ({arg_type})" if arg_type else ""
            lines.append(
                f"{indent}    {arg_name}{type_tag}: Description{default_str}."
            )

    rt = _return_type(node)
    if rt:
        lines.append(f"{indent}")
        lines.append(f"{indent}Returns:")
        lines.append(f"{indent}    {rt}: Description.")

    # Try to detect Raises from raise statements (simple heuristic)
    raises: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and child.exc:
            if isinstance(child.exc, ast.Call) and isinstance(child.exc.func, ast.Name):
                exc_name = child.exc.func.id
                if exc_name.endswith("Error") or exc_name.endswith("Warning"):
                    raises.add(exc_name)
            elif isinstance(child.exc, ast.Name):
                exc_name = child.exc.id
                if exc_name.endswith("Error") or exc_name.endswith("Warning"):
                    raises.add(exc_name)

    if raises:
        lines.append(f"{indent}")
        lines.append(f"{indent}Raises:")
        for exc_name in sorted(raises):
            lines.append(f"{indent}    {exc_name}: Description.")

    lines.append(f"{indent}\"\"\"")
    return lines


def _build_class_docstring(node: ast.ClassDef, indent: str) -> list[str]:
    """Build Google-style docstring lines for a class."""
    name = node.name
    lines: list[str] = [f'{indent}"""{name}.']

    # Check for attributes in __init__
    attrs: list[str] = []
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "__init__":
            for stmt in child.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                            if target.value.id == "self":
                                attrs.append(target.attr)

    if attrs:
        lines.append(f"{indent}")
        lines.append(f"{indent}Attributes:")
        for attr_name in sorted(attrs):
            lines.append(f"{indent}    {attr_name}: Description.")

    lines.append(f"{indent}\"\"\"")
    return lines


def _find_sig_end_line(source_lines: list[str], def_lineno_0idx: int) -> int:
    """Find the 0-indexed line where the function/class signature ends.

    Handles multi-line signatures like:
        def foo(
            arg1: str,
            arg2: int,
        ) -> bool:
    """
    for i in range(def_lineno_0idx, min(def_lineno_0idx + 40, len(source_lines))):
        raw = source_lines[i]
        stripped = raw.strip()
        # If line ends with '):' or ':' (for classes), it's the sig end
        # But be careful: ':' could also be dict literal or type hint
        if stripped.endswith("):") or stripped == ":":
            return i
        # Single-line function: def foo(): ...
        if "):" in stripped or stripped.endswith(":"):
            return i
    return def_lineno_0idx  # fallback


def _find_body_line_0idx(source_lines: list[str], sig_end: int) -> int:
    """Find where the body starts (first non-blank after ':', handling single-line bodies)."""
    for i in range(sig_end + 1, len(source_lines)):
        stripped = source_lines[i].strip()
        if stripped == "":
            continue
        return i
    return sig_end + 1


def process_file(filepath: str, dry_run: bool = False) -> bool:
    """Process one .py file, adding docstrings where missing. Returns True if changed."""
    with open(filepath, encoding="utf-8") as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    # Collect targets
    targets: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not _has_docstring(node):
                targets.append(node)

    if not targets:
        return False

    # Sort by position descending so insertions don't shift offsets
    targets.sort(key=lambda n: (n.lineno, n.col_offset), reverse=True)

    source_lines = source.split("\n")

    for node in targets:
        # Determine the actual def/class line ignoring decorators
        def_line = source_lines[node.lineno - 1]
        indent = _get_indent(def_line)

        # Find the first body node
        if not node.body:
            continue
        first_body = node.body[0]

        if isinstance(first_body, ast.Expr) and isinstance(
            first_body.value, ast.Constant
        ):
            # Has docstring, shouldn't be in targets
            continue

        # Check if body starts on same line as signature (single-line)
        first_body_line = first_body.lineno

        # For multi-line functions, use body indentation
        if first_body_line != node.lineno:
            body_line = source_lines[first_body_line - 1]
            body_indent = _get_indent(body_line)
        else:
            body_indent = indent + "    "

        # Use body indentation for the docstring
        doc_indent = body_indent

        if first_body_line == node.lineno:
            # Single-line function: `def foo(): pass`
            sig_end_line = node.lineno - 1
            sig_line = source_lines[sig_end_line]

            colon_pos = len(sig_line)
            for c in ["):", ":"]:
                idx = sig_line.find(c)
                if idx != -1:
                    colon_pos = idx + len(c) if c == "):" else idx + len(c)
                    break

            before_sig = sig_line[:colon_pos]
            after_sig = sig_line[colon_pos:].lstrip()

            if isinstance(node, ast.ClassDef):
                doc_lines = _build_class_docstring(node, doc_indent)
            else:
                doc_lines = _build_func_docstring(node, doc_indent)

            body_line = doc_indent + after_sig if after_sig else ""
            replacement = [before_sig]
            for dl in doc_lines:
                replacement.append(dl)
            if body_line:
                replacement.append(body_line)

            source_lines[sig_end_line : sig_end_line + 1] = replacement
        else:
            # Multi-line: body starts on a later line
            if isinstance(node, ast.ClassDef):
                doc_lines = _build_class_docstring(node, doc_indent)
            else:
                doc_lines = _build_func_docstring(node, doc_indent)

            insert_idx = first_body_line - 1
            for dl in reversed(doc_lines):
                source_lines.insert(insert_idx, dl)

    new_source = "\n".join(source_lines)

    # Normalize line endings
    if new_source == source:
        return False

    if not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_source)

    # Report
    relpath = os.path.relpath(filepath)
    count = len(targets)
    action = "WOULD ADD" if dry_run else "Added"
    print(f"  [{action}] {relpath}: {count} docstring(s)")
    return True


def main() -> None:
    """Walk Python source trees and add missing Google-style docstrings.

    Walks ``src/margin/``, ``tests/`` and ``alembic/`` by default, or the
    paths provided on the command line, inserting docstrings for every public
    or private function/class that lacks one.
    """
    dry_run = "--dry-run" in sys.argv

    # Determine paths
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if args:
        paths = args
    else:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        paths = [
            os.path.join(repo_root, "src", "margin"),
            os.path.join(repo_root, "tests"),
            os.path.join(repo_root, "alembic"),
        ]

    total_changed = 0
    total_files = 0

    for p in paths:
        if os.path.isfile(p):
            files = [p]
        else:
            files = []
            for root, dirs, fnames in os.walk(p):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for fn in fnames:
                    if fn.endswith(".py"):
                        files.append(os.path.join(root, fn))

        for fp in sorted(files):
            total_files += 1
            changed = process_file(fp, dry_run=dry_run)
            if changed:
                total_changed += 1

    action = "Would touch" if dry_run else "Modified"
    print(f"\n{action} {total_changed} of {total_files} files.")


if __name__ == "__main__":
    main()
