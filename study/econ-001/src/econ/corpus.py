"""Seeded task generator. Three families; each task is a module with THREE
distinct bugs composed (hardened twice: dev-002 showed 100% baseline on
single-bug tasks, dev-003 100% on two-bug tasks). Bugs include subtle
classes: order-of-operations, aliasing/mutation, shared state, boundary
conditions. Every task ships its reference (clean) code.
Integrity rule: reference PASSES hidden tests, buggy version FAILS them.
Packet cap: 3,000 tokens, enforced at build (reject, never truncate).
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass

TARGET_FILENAME = "target.py"
PACKET_CAP = 3000
N_BUGS = 3


@dataclass
class Task:
    task_id: str
    family: str
    template: str
    statement: str
    target_code: str      # buggy version shown to the worker
    reference_code: str   # clean version (never shown)
    hidden_tests: str
    support_files: dict

    def packet(self) -> str:
        from . import tokens as _t
        p = (f"TASK {self.task_id}\n\n{self.statement}\n\n"
             f"The file {TARGET_FILENAME} currently contains:\n"
             f"```python\n{self.target_code}\n```\n\n"
             f"Output contract: reply with exactly one ```python fenced block "
             f"containing the COMPLETE corrected file. No other text.")
        _t.enforce_cap(p, PACKET_CAP, f"packet {self.task_id}")
        return p

    def to_dict(self):
        return {"task_id": self.task_id, "family": self.family,
                "template": self.template, "statement": self.statement,
                "target_code": self.target_code,
                "reference_code": self.reference_code,
                "hidden_tests": self.hidden_tests,
                "support_files": self.support_files}


def _ht(body: str) -> str:
    indented = "\n".join("    " + ln if ln.strip() else ln
                         for ln in body.strip("\n").split("\n"))
    return "import target\n\ndef run():\n" + indented + "\n"


def _rep1(code: str, old: str, new: str) -> str:
    if code.count(old) != 1:
        raise ValueError(f"bug target not unique: {old!r} x{code.count(old)}")
    return code.replace(old, new)


# ---------------------------------------------------------------- family: logic
def _logic_clean(rng: random.Random):
    pct = rng.choice([5, 8, 10, 12])
    thr = rng.choice([100, 200, 500])
    disc = rng.choice([10, 15, 20])
    code = f'''"""Order processing module.

compute_subtotal(items): sum of qty*price over items.
apply_discount(subtotal): {disc}% off when subtotal is strictly greater than {thr}.
compute_tax(amount): {pct}% sales tax on the amount.
order_total(items): discount first, then tax on the discounted amount.
bulk_quote(items, n): n identical orders; 5% volume rebate when n >= 10,
  applied to the order total.
refund(items, returned_names): refund the subtotal (pre-discount, pre-tax)
  of the returned line items.
format_receipt(items): multi-line receipt string; totals must match the
functions above.
"""

def compute_subtotal(items):
    total = 0.0
    for it in items:
        total += it["qty"] * it["price"]
    return round(total, 2)

def apply_discount(subtotal):
    if subtotal > {thr}:
        return round(subtotal * (1 - {disc} / 100), 2)
    return subtotal

def compute_tax(amount):
    return round(amount * {pct} / 100, 2)

def order_total(items):
    sub = compute_subtotal(items)
    d = apply_discount(sub)
    return round(d + compute_tax(d), 2)

def bulk_quote(items, n):
    t = order_total(items) * n
    if n >= 10:
        t = t * 0.95
    return round(t, 2)

def refund(items, returned_names):
    base = sum(it["qty"] * it["price"] for it in items
               if it["name"] in returned_names)
    return round(base, 2)

def format_receipt(items):
    lines = []
    for it in items:
        lines.append(f"{{it['name']}} x{{it['qty']}} @ {{it['price']}}")
    lines.append(f"TOTAL: {{order_total(items)}}")
    return "\\n".join(lines)
'''
    tests = _ht(f'''
items = [{{"name": "a", "qty": 2, "price": 60.0}}, {{"name": "b", "qty": 1, "price": 30.0}}]
assert target.compute_subtotal(items) == 150.0, "subtotal"
assert target.apply_discount({thr}) == {thr}, "at threshold no discount"
assert target.apply_discount({thr + 1}) == round(({thr + 1}) * (1 - {disc}/100), 2), "discount"
assert target.compute_tax(200.0) == round(200.0 * {pct} / 100, 2), "tax"
d = target.apply_discount(150.0)
assert target.order_total(items) == round(d + target.compute_tax(d), 2), "order_total"
# discount-before-tax matters: use a subtotal above every threshold
big = [{{"name": "a", "qty": 20, "price": 60.0}}]
subb = target.compute_subtotal(big)
assert subb == 1200.0, "big subtotal"
db = target.apply_discount(subb)
assert target.order_total(big) == round(db + target.compute_tax(db), 2), "order_total big"
assert target.bulk_quote(items, 9) == round(target.order_total(items) * 9, 2), "bulk no rebate"
assert target.bulk_quote(items, 10) == round(target.order_total(items) * 10 * 0.95, 2), "bulk rebate at 10"
assert target.refund(items, ["a"]) == 120.0, "refund pre-tax"
r = target.format_receipt(items)
assert f"TOTAL: {{target.order_total(items)}}" in r, "receipt"
''')
    stmt = ("Fix the order-processing module so every function matches its "
            "docstring. There may be several defects, including subtle ones.")
    return code, tests, stmt, {}


def _logic_bugs():
    return [
        ("qty_plus_price",
         lambda c: _rep1(c, 'total += it["qty"] * it["price"]',
                         'total += it["qty"] + it["price"]')),
        ("threshold_inclusive",
         lambda c: _rep1(c, "if subtotal > ", "if subtotal >= ")),
        ("tax_per_mille",
         lambda c: _rep1(c, "/ 100, 2)", "/ 1000, 2)")),
        ("tax_on_prediscount",
         lambda c: _rep1(c, "    return round(d + compute_tax(d), 2)",
                         "    return round(d + compute_tax(sub), 2)")),
        ("refund_includes_tax",
         lambda c: _rep1(c, "    return round(base, 2)", "    return round(base + compute_tax(base), 2)")),
        ("bulk_rebate_threshold",
         lambda c: _rep1(c, "if n >= 10:", "if n > 10:")),
    ]


# ---------------------------------------------------------------- family: interface
def _interface_clean(rng: random.Random):
    code = '''"""Tiny event bus.

subscribe(event, handler): register handler; returns an id.
emit(event, *args): call every handler registered for event, in order.
  A handler that raises does not prevent the remaining handlers.
unsubscribe(sub_id): remove that registration; unknown ids are ignored.
once(event, handler): handler fires on the next emit only.
map_emit(event, *args): like emit, but return the list of handler results.
clear(event): remove all registrations for event.
handler_count(event): number of live registrations for event.
"""

def _new_bus():
    return {"handlers": {}, "seq": 0}

_bus = _new_bus()

def reset():
    global _bus
    _bus = _new_bus()

def subscribe(event, handler):
    _bus["seq"] += 1
    sid = _bus["seq"]
    _bus["handlers"].setdefault(event, []).append((sid, handler))
    return sid

def emit(event, *args):
    for sid, handler in list(_bus["handlers"].get(event, [])):
        try:
            handler(*args)
        except Exception:
            continue

def map_emit(event, *args):
    return [handler(*args) for sid, handler in list(_bus["handlers"].get(event, []))]

def clear(event):
    _bus["handlers"][event] = []

def unsubscribe(sub_id):
    for event, regs in _bus["handlers"].items():
        for i, (sid, handler) in enumerate(regs):
            if sid == sub_id:
                del regs[i]
                return True
    return False

def once(event, handler):
    holder = {}
    def wrapper(*args):
        unsubscribe(holder["sid"])
        handler(*args)
    holder["sid"] = subscribe(event, wrapper)

def handler_count(event):
    return len(_bus["handlers"].get(event, []))
'''
    tests = _ht('''
target.reset()
calls = []
a = target.subscribe("e", lambda x: calls.append(("a", x)))
b = target.subscribe("e", lambda x: calls.append(("b", x)))
target.emit("e", 1)
assert calls == [("a", 1), ("b", 1)], f"emit order {calls}"
assert target.handler_count("e") == 2
assert target.unsubscribe(a) is True
target.emit("e", 2)
assert calls == [("a", 1), ("b", 1), ("b", 2)], f"after unsub {calls}"
assert target.handler_count("e") == 1
assert target.unsubscribe(99999) is False
# raising handler does not stop the rest
target.reset()
seen = []
def boom(x): raise RuntimeError("x")
target.subscribe("r", boom)
target.subscribe("r", lambda x: seen.append(x))
target.emit("r", 5)
assert seen == [5], f"emit continued {seen}"
# once fires exactly once even with two registrations
target.reset()
c1, c2 = [], []
target.once("ev", lambda v: c1.append(v))
target.once("ev", lambda v: c2.append(v))
target.emit("ev", "x")
target.emit("ev", "y")
assert c1 == ["x"] and c2 == ["x"], f"once {c1} {c2}"
assert target.handler_count("ev") == 0
# map_emit collects in order
target.reset()
target.subscribe("m", lambda x: x + 1)
target.subscribe("m", lambda x: x * 10)
assert target.map_emit("m", 2) == [3, 20], "map_emit"
target.clear("m")
assert target.handler_count("m") == 0
target.emit("m", 2)  # no handlers, no crash
''')
    stmt = ("Fix the event bus so every function matches its docstring. "
            "There may be several defects, including subtle ones.")
    return code, tests, stmt, {}


def _iface_shared_holder(code: str) -> str:
    code = _rep1(code, "def once(event, handler):\n    holder = {}",
                "def once(event, handler):")
    code = code.replace('holder["sid"]', '_ONCE_HOLDER["sid"]')
    return _rep1(code, "_bus = _new_bus()\n\ndef reset():",
                "_bus = _new_bus()\n_ONCE_HOLDER = {}\n\ndef reset():")


def _iface_bugs():
    return [
        ("emit_skips_first",
         lambda c: _rep1(c, "for sid, handler in list(_bus[\"handlers\"].get(event, [])):",
                         "for sid, handler in list(_bus[\"handlers\"].get(event, []))[1:]:")),
        ("unsubscribe_wrong_key",
         lambda c: _rep1(c, "if sid == sub_id:", "if handler == sub_id:")),
        ("once_never_removes",
         lambda c: _rep1(c, "        unsubscribe(holder[\"sid\"])\n", "")),
        ("count_off_by_one",
         lambda c: _rep1(c, "return len(_bus[\"handlers\"].get(event, []))",
                         "return len(_bus[\"handlers\"].get(event, [])) + 1")),
        ("emit_stops_on_exception",
         lambda c: _rep1(c, "        except Exception:\n            continue",
                         "        except Exception:\n            break")),
        ("once_shared_holder", _iface_shared_holder),
        ("map_emit_reversed",
         lambda c: _rep1(c, "return [handler(*args) for sid, handler in list(_bus[\"handlers\"].get(event, []))]",
                         "return [handler(*args) for sid, handler in list(reversed(_bus[\"handlers\"].get(event, [])))]")),
    ]


# ---------------------------------------------------------------- family: config
def _config_clean(rng: random.Random):
    lo, hi = rng.choice([(1, 10), (0, 100), (5, 50)])
    code = f'''"""Layered settings.

Defaults < file config < environment overrides (later wins).
get(key, default=None): dotted lookup, e.g. "db.host".
set(key, value): dotted set, creating intermediate dicts.
load(file_cfg, env): build the effective settings dict.
validate(cfg): every "limits.*" value must satisfy {lo} <= v <= {hi}.
merge(base, override): deep merge; override wins; inputs not mutated.
snapshot(): deep copy of the effective settings.
restore(snap): replace effective settings with the snapshot.
"""

import copy

def _get_path(cfg, key, default=None):
    cur = cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur

def get(key, default=None):
    return _get_path(_EFFECTIVE, key, default)

def set(key, value):
    parts = key.split(".")
    cur = _EFFECTIVE
    for part in parts[:-1]:
        cur = cur.setdefault(part, {{}})
    cur[parts[-1]] = value

def load(file_cfg, env):
    global _EFFECTIVE
    merged = merge(_DEFAULTS, file_cfg)
    merged = merge(merged, env)
    _EFFECTIVE = merged
    return merged

def validate(cfg):
    for key in ("limits.rate", "limits.burst"):
        v = _get_path(cfg, key)
        if v is None:
            continue
        if not ({lo} <= v <= {hi}):
            return False
    return True

def merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out

def snapshot():
    return copy.deepcopy(_EFFECTIVE)

def restore(snap):
    global _EFFECTIVE
    _EFFECTIVE = copy.deepcopy(snap)

_DEFAULTS = {{"limits": {{"rate": {lo}, "burst": {hi}}}, "db": {{"host": "localhost"}}}}
_EFFECTIVE = copy.deepcopy(_DEFAULTS)
'''
    tests = _ht(f'''
target.load({{"limits": {{"rate": 5}}}}, {{"db": {{"host": "prod"}}}})
assert target.get("db.host") == "prod", "env wins"
assert target.get("limits.rate") == 5, "file value kept"
assert target.get("limits.burst") == {hi}, "default kept"
assert target.get("nope", "dflt") == "dflt", "default"
target.set("new.deep.key", 7)
assert target.get("new.deep.key") == 7, "dotted set"
assert target.validate({{"limits": {{"rate": {lo}, "burst": {hi}}}}}) is True
assert target.validate({{"limits": {{"rate": {lo - 1}}}}}) is False, "below lo"
assert target.validate({{"limits": {{"burst": {hi + 1}}}}}) is False, "above hi"
base = {{"a": {{"x": 1}}}}
m = target.merge(base, {{"a": {{"y": 2}}}})
assert m == {{"a": {{"x": 1, "y": 2}}}}, f"deep merge {{m}}"
assert base == {{"a": {{"x": 1}}}}, "merge must not mutate base"
target.load({{}}, {{}})
s = target.snapshot()
target.set("limits.rate", 999)
target.restore(s)
assert target.get("limits.rate") != 999, "snapshot/restore nested"
''')
    stmt = ("Fix the layered settings module so every function matches its "
            "docstring. Later layers win. There may be several defects, "
            "including subtle ones.")
    return code, tests, stmt, {}


def _config_bugs(clean: str):
    m = re.search(r"if not \((\d+) <= v <= (\d+)\):", clean)
    lo, hi = m.group(1), m.group(2)

    def _boundary_exclusive(code: str) -> str:
        return _rep1(code, f"if not ({lo} <= v <= {hi}):",
                     f"if not ({lo} < v <= {hi}):")

    return [
        ("precedence_flipped",
         lambda c: _rep1(c, "merged = merge(_DEFAULTS, file_cfg)\n    merged = merge(merged, env)",
                         "merged = merge(env, file_cfg)\n    merged = merge(merged, _DEFAULTS)")),
        ("dotted_split_wrong",
         lambda c: _rep1(c, 'key.split(".")', 'key.split("/")')),
        ("boundary_exclusive", _boundary_exclusive),
        ("shallow_merge",
         lambda c: _rep1(c, "            out[k] = merge(out[k], v)",
                         "            out[k] = v")),
        ("merge_mutates_base",
         lambda c: _rep1(c, "    out = dict(base)", "    out = base")),
        ("set_no_mkdir",
         lambda c: _rep1(c, "        cur = cur.setdefault(part, {})",
                         "        cur = cur[part]")),
        ("snapshot_shallow",
         lambda c: _rep1(c, "    return copy.deepcopy(_EFFECTIVE)",
                         "    return dict(_EFFECTIVE)")),
    ]


# ---------------------------------------------------------------- composition
def _compose_bugs(clean: str, bugs: list, rng: random.Random,
                   tries: int = 40) -> tuple[str, tuple[str, ...]]:
    by_name = dict(bugs)
    last_err = None
    for _ in range(tries):
        try:
            names = rng.sample([b[0] for b in bugs], N_BUGS)
            buggy = clean
            for n in names:
                new = by_name[n](buggy)
                if new == buggy:
                    raise ValueError(f"bug {n} did not change code")
                buggy = new
            return buggy, tuple(names)
        except ValueError as e:
            last_err = e
    raise ValueError(f"could not compose {N_BUGS} bugs: {last_err}")


def generate_task(family: str, rng: random.Random, task_id: str) -> Task:
    if family == "logic":
        clean, tests, stmt, support = _logic_clean(rng)
        bugs = _logic_bugs()
    elif family == "interface":
        clean, tests, stmt, support = _interface_clean(rng)
        bugs = _iface_bugs()
    elif family == "config":
        clean, tests, stmt, support = _config_clean(rng)
        bugs = _config_bugs(clean)
    else:
        raise ValueError(family)
    buggy, names = _compose_bugs(clean, bugs, rng)
    return Task(task_id=task_id, family=family, template="+".join(names),
                statement=stmt, target_code=buggy, reference_code=clean,
                hidden_tests=tests, support_files=support)


def build_corpus(master_seed: int, n_dev: int, n_eval: int,
                 n_calib: int) -> dict[str, list[Task]]:
    pools: dict[str, list[Task]] = {}
    families = ["logic", "interface", "config"]
    for pool, n in (("dev", n_dev), ("eval", n_eval), ("calib", n_calib)):
        rng = random.Random(f"{master_seed}:{pool}")
        tasks = []
        for i in range(n):
            fam = families[i % 3]
            tasks.append(generate_task(fam, rng, f"{pool[:3]}-{fam[:4]}-{i:04d}"))
        pools[pool] = tasks
    return pools


def corpus_hash(pools: dict[str, list[Task]]) -> dict[str, str]:
    out = {}
    for pool, tasks in pools.items():
        h = hashlib.sha256()
        for t in tasks:
            h.update(json.dumps(t.to_dict(), sort_keys=True).encode())
        out[pool] = h.hexdigest()
    return out


def freeze_corpus(pools: dict[str, list[Task]], path: str) -> dict:
    import os
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = {pool: [t.to_dict() for t in tasks]
            for pool, tasks in pools.items()}
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    return corpus_hash(pools)


def load_corpus(path: str) -> dict[str, list[Task]]:
    with open(path) as f:
        data = json.load(f)
    return {pool: [Task(**d) for d in tasks] for pool, tasks in data.items()}
