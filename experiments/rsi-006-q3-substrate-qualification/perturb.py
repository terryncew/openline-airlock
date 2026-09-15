"""RSI-006-Q frozen perturbation generator.

Seeded AST mutation over untouched repository checkouts. The operator set is
fixed by RSI_006_Q_SPEC.md and defined without reference to any repository's
semantics. Same seed -> byte-identical mutant list.

A mutant is exactly one operator application at one site. Test directories
are never mutated.
"""

from __future__ import annotations

import ast
import hashlib
import random
from dataclasses import dataclass
from pathlib import Path

# Frozen operator set (mirrors RSI_006_Q_SPEC.md).
OPERATORS = (
    "CMP_SWAP",
    "ARITH_SWAP",
    "BOOL_FLIP",
    "NUM_DELTA",
    "LOGIC_SWAP",
    "NOT_DROP",
)

_CMP_MAP = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
}

_ARITH_MAP = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
}


def _is_cmp_candidate(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and type(node.ops[0]) in _CMP_MAP
    )


def _is_arith_candidate(node: ast.AST) -> bool:
    return isinstance(node, ast.BinOp) and type(node.op) in _ARITH_MAP


def _is_bool_candidate(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in (True, False)


def _is_num_candidate(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
        and abs(node.value) <= 1000
    )


def _is_logic_candidate(node: ast.AST) -> bool:
    return isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or))


def _is_not_candidate(node: ast.AST) -> bool:
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)


_PREDICATES = {
    "CMP_SWAP": _is_cmp_candidate,
    "ARITH_SWAP": _is_arith_candidate,
    "BOOL_FLIP": _is_bool_candidate,
    "NUM_DELTA": _is_num_candidate,
    "LOGIC_SWAP": _is_logic_candidate,
    "NOT_DROP": _is_not_candidate,
}


class _SiteMutator(ast.NodeTransformer):
    """Apply one operator at the site matching (lineno, col, operator)."""

    def __init__(self, lineno: int, col: int, operator: str):
        self._lineno = lineno
        self._col = col
        self._operator = operator
        self.applied = False

    def _match(self, node: ast.AST) -> bool:
        return (
            not self.applied
            and getattr(node, "lineno", None) == self._lineno
            and getattr(node, "col_offset", None) == self._col
            and _PREDICATES[self._operator](node)
        )

    def visit_Compare(self, node: ast.Compare):
        if self._match(node):
            node.ops = [_CMP_MAP[type(node.ops[0])]()]
            self.applied = True
            return node
        return self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        if self._match(node):
            node.op = _ARITH_MAP[type(node.op)]()
            self.applied = True
            return node
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if self._match(node):
            if self._operator == "BOOL_FLIP":
                node.value = not node.value
            else:  # NUM_DELTA
                node.value = node.value + 1
            self.applied = True
            return node
        return self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp):
        if self._match(node):
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            self.applied = True
            return node
        return self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp):
        if self._match(node):
            self.applied = True
            return ast.copy_location(self.generic_visit(node.operand), node)
        return self.generic_visit(node)


@dataclass(frozen=True)
class Site:
    relpath: str
    lineno: int
    col: int
    operator: str

    @property
    def key(self) -> str:
        return f"{self.relpath}:{self.lineno}:{self.col}:{self.operator}"


def enumerate_sites(package_dir: Path) -> list[Site]:
    """Deterministically enumerate every eligible mutation site."""
    sites: list[Site] = []
    for path in sorted(package_dir.rglob("*.py")):
        relpath = path.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(path.read_bytes(), filename=relpath)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", None)
            col = getattr(node, "col_offset", None)
            if lineno is None or col is None:
                continue
            for operator in OPERATORS:
                if _PREDICATES[operator](node):
                    sites.append(Site(relpath, lineno, col, operator))
    sites.sort(key=lambda s: (s.relpath, s.lineno, s.col, s.operator))
    return sites


def generate_mutants(
    package_dir: Path, seed: str, n: int, tag: str
) -> list[dict]:
    """Return n mutant descriptors, deterministically derived from seed."""
    sites = enumerate_sites(package_dir)
    rng = random.Random(seed)
    order = list(range(len(sites)))
    rng.shuffle(order)
    chosen = [sites[i] for i in order[:n]]
    mutants = []
    for index, site in enumerate(chosen):
        mutants.append(
            {
                "mutant_id": f"{tag}-{index:04d}",
                "relpath": site.relpath,
                "lineno": site.lineno,
                "col": site.col,
                "operator": site.operator,
                "site_key": site.key,
                "seed": seed,
            }
        )
    return mutants


def apply_mutant(package_dir: Path, mutant: dict, overlay_package_dir: Path) -> None:
    """Apply the mutant's single-site rewrite inside the overlay copy."""
    target = overlay_package_dir / mutant["relpath"]
    tree = ast.parse(target.read_bytes(), filename=mutant["relpath"])
    mutator = _SiteMutator(mutant["lineno"], mutant["col"], mutant["operator"])
    new_tree = mutator.visit(tree)
    if not mutator.applied:
        raise RuntimeError(f"mutant site did not apply: {mutant['site_key']}")
    ast.fix_missing_locations(new_tree)
    target.write_bytes(ast.unparse(new_tree).encode("utf-8"))


def spec_digest() -> str:
    """SHA-256 over the frozen generator-relevant constants."""
    h = hashlib.sha256()
    h.update("|".join(OPERATORS).encode())
    h.update(b"|")
    h.update(__doc__.encode() if __doc__ else b"")
    return h.hexdigest()
