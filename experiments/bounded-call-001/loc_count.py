"""BOUNDED-CALL-001 LOC counter: frozen method (AST-based).

Counts non-test executable LOC: every non-blank, non-comment line that is
not part of a docstring. Docstrings are detected via AST (first-statement
string expressions in module/class/function bodies), the same convention
used for ROOT-BIND-001.
"""
import ast
import sys


def count_file(path):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    doc_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                d = body[0]
                doc_lines.update(range(d.lineno, (d.end_lineno or d.lineno) + 1))
    n = 0
    for i, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if i in doc_lines:
            continue
        n += 1
    return n


if __name__ == "__main__":
    total = 0
    for path in sys.argv[1:]:
        c = count_file(path)
        print("%4d  %s" % (c, path))
        total += c
    print("%4d  TOTAL" % total)
