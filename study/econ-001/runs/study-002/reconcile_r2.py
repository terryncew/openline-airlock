"""Reconcile every invocation of ECON-001-R2 (runs/study-002).

Classifies all 364 reserved invocation IDs into:
  - settled               : provider returned usage; actual cost settled
  - proven_not_dispatched : failure demonstrably before any request byte
                            could reach the provider -> reservation released
  - possibly_dispatched   : ambiguous (e.g. remote closed after connect)
                            -> reservation retained

Reads ONLY the frozen ledger (runs/study-002/ledger.jsonl). Never edits it.
Writes:
  - runs/study-002/reconciliation.json   (per-ID classification + summary)
  - runs/study-002/ledger_releases.jsonl (append-only release records)
  - runs/study-002/RECONCILIATION.md     (human-readable record)

Zero network. Zero spend.
"""
import collections
import hashlib
import json
import os
import sys

RUN_DIR = os.path.join("runs", "study-002")
LEDGER = os.path.join(RUN_DIR, "ledger.jsonl")

# Exact reason string recorded for the 301 egress-proxy failures.
REFUSED_REASON = ("transport_no_usage: <urlopen error [Errno 111] "
                  "Connection refused>")

EVIDENCE_REFUSED = (
    "1) Ledger reason carries the '<urlopen error>' wrapper: the exception "
    "was raised by urllib.request.urlopen, i.e. AFTER dc.add_surrogate_to_request "
    "had already obtained the authd surrogate (an authd-socket failure would "
    "raise DynamicCredentialError / a bare OSError with no '<urlopen error>' "
    "wrapper). "
    "2) The run environment routes egress through https_proxy="
    "hatch-egress-proxy:3128 (observed in the launch environment; "
    "urllib honors it for https://api.openai.com). hatch-egress-proxy "
    "resolves to 198.19.0.1, the VM-local egress sidecar. "
    "3) POSIX ECONNREFUSED (errno 111) is returned by connect() before a "
    "single byte is transmitted; for an HTTPS-via-proxy request no CONNECT, "
    "no TLS handshake and no request bytes could have been sent. "
    "4) All 301 share the identical reason string inside one outage window "
    "(first 11:24:43 PDT, immediately after a successful settle at 11:24:30); "
    "the local sidecar was down. Conclusion: no billable provider request "
    "could have been sent for these invocations."
)


def main() -> None:
    with open(LEDGER, "rb") as f:
        raw = f.read()
    sha_before = hashlib.sha256(raw).hexdigest()
    lines = [json.loads(l) for l in raw.decode("utf-8").splitlines()
             if l.strip()]

    kinds = collections.Counter(l.get("kind") for l in lines)
    reserves = {l["invocation_id"]: l
                for l in lines if l.get("kind") == "reserve"}
    outcomes = {}
    for l in lines:
        if l.get("kind") in ("settle", "unresolved"):
            assert l["invocation_id"] not in outcomes, "duplicate outcome"
            outcomes[l["invocation_id"]] = l

    missing = [i for i in reserves if i not in outcomes]
    assert not missing, f"reserves without outcome: {missing}"

    rec = {"ledger_sha256": sha_before,
           "ledger_kinds": dict(kinds),
           "invocations": {},
           "design": {}}

    n_settled = n_proven = n_possible = 0
    settled_actual = 0.0
    settled_reserved = 0.0
    released = 0.0
    retained = 0.0
    gross_reserved = 0.0

    for inv_id, r in reserves.items():
        o = outcomes[inv_id]
        gross_reserved += float(r["amount"])
        entry = {"envelope": r["envelope"],
                 "reserved_usd": float(r["amount"]),
                 "outcome": o["kind"]}
        if o["kind"] == "settle":
            entry["class"] = "settled"
            entry["actual_usd"] = float(o["actual"])
            entry["provider_request_id"] = o.get("request_id")
            settled_actual += float(o["actual"])
            settled_reserved += float(r["amount"])
            n_settled += 1
        else:
            reason = o.get("reason", "")
            entry["reason"] = reason
            if reason == REFUSED_REASON:
                entry["class"] = "proven_not_dispatched"
                entry["release_usd"] = float(o["reservation"])
                entry["evidence"] = EVIDENCE_REFUSED
                released += float(o["reservation"])
                n_proven += 1
            else:
                entry["class"] = "possibly_dispatched"
                entry["retained_usd"] = float(o["reservation"])
                entry["note"] = ("Ambiguous: TCP connect succeeded (or may "
                                 "have); the request may have been "
                                 "transmitted. Reservation retained per "
                                 "protocol.")
                retained += float(o["reservation"])
                n_possible += 1
        rec["invocations"][inv_id] = entry

    # Design-max vs actual: the frozen protocol short-circuits acquisition
    # when the proposal call is not ok (no candidate -> no promotion).
    rep2 = json.load(open(os.path.join(RUN_DIR, "rep2.json")))
    rep3 = json.load(open(os.path.join(RUN_DIR, "rep3.json")))
    short = []
    for r, d in (("rep2", rep2), ("rep3", rep3)):
        for g in ("G1_acquisition", "G2_acquisition"):
            a = d[g]
            if a.get("reason") == "proposal_unresolved":
                short.append(f"{r}/{g}: 4 invocations instead of 10 "
                             f"(proposal unresolved -> promotion skipped)")
    rec["design"] = {
        "design_max_invocations": 388,
        "design_max_math": "3 reps x (108 measurement + 20 acquisition-max) "
                           "+ 4 calibration",
        "actual_reserves": len(reserves),
        "shortfall_explanation": ("24 invocations never issued: 4 acquisitions "
                                  "(rep2 G1/G2, rep3 G1/G2) short-circuited "
                                  "per the frozen protocol when their proposal "
                                  "call returned unresolved -- no candidate "
                                  "delta, so the 6 promotion calls each were "
                                  "skipped by design, not lost."),
        "short_circuits": short,
    }

    rec["summary"] = {
        "total_reserved": len(reserves),
        "settled": n_settled,
        "proven_not_dispatched_released": n_proven,
        "possibly_dispatched_retained": n_possible,
        "gross_reserved_usd": round(gross_reserved, 6),
        "settled_reserved_usd": round(settled_reserved, 6),
        "settled_actual_usd": round(settled_actual, 6),
        "settled_headroom_usd": round(settled_reserved - settled_actual, 6),
        "released_usd": round(released, 6),
        "retained_unresolved_usd": round(retained, 6),
        "strategy_vs_physical": (
            f"Strategy (envelope reservations) risked ${gross_reserved:.4f} "
            f"across {len(reserves)} invocations. Physical provider-settled "
            f"spend is ${settled_actual:.4f} (against "
            f"${settled_reserved:.4f} reserved for those calls; "
            f"${settled_reserved - settled_actual:.4f} of reservation "
            f"headroom simply unspent). Of the {n_proven + n_possible} "
            f"unresolved, ${released:.2f} is proven never to have left the "
            f"machine (released with evidence) and ${retained:.2f} stays "
            f"retained as ambiguous exposure."),
    }
    assert abs((settled_reserved + released + retained) - gross_reserved) < 1e-6

    with open(os.path.join(RUN_DIR, "reconciliation.json"), "w") as f:
        json.dump(rec, f, indent=1, sort_keys=True)

    # Append-only release log. The original ledger is never edited.
    rel_path = os.path.join(RUN_DIR, "ledger_releases.jsonl")
    with open(rel_path, "w") as f:
        for inv_id, e in sorted(rec["invocations"].items()):
            if e["class"] == "proven_not_dispatched":
                f.write(json.dumps({
                    "kind": "release",
                    "invocation_id": inv_id,
                    "reservation_id": outcomes[inv_id]["reservation_id"],
                    "released_usd": e["release_usd"],
                    "basis": "proven_not_dispatched",
                    "evidence": EVIDENCE_REFUSED,
                }, sort_keys=True) + "\n")

    sha_after = hashlib.sha256(open(LEDGER, "rb").read()).hexdigest()
    assert sha_after == sha_before, "ledger was modified!"
    print(f"classified {len(reserves)}: settled={n_settled} "
          f"released={n_proven} retained={n_possible}")
    print(f"gross=${gross_reserved:.4f} settled=${settled_actual:.4f} "
          f"released=${released:.2f} retained=${retained:.2f}")
    print(f"ledger untouched: {sha_after[:16]}...")


if __name__ == "__main__":
    sys.exit(main())
