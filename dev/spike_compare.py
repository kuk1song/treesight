#!/usr/bin/env python3
"""Compare repeated extractions of one session: how much the runs agree, and how much of a reference they find.

Two items are taken to be the same event when they cite a common message, or when their wording is
close (character bigram Jaccard of label and line) and their times are within three hours. Pairs are
matched greedily from the best score down. This is an approximation; print the pairs and check them by eye.

Usage:
  python3 dev/spike_compare.py RUN.json RUN.json ... [--expect SPEC.json] [--reference SESSION.json] [--show]
"""
import argparse
import itertools
import json
import re
from datetime import datetime


def _t(s):
    s = s if "T" in s else s + "T12:00:00Z"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _bigrams(s):
    s = re.sub(r"\s+", " ", s.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _text(x):
    return "%s %s" % (x["label"], x["line"])


def _msgs(x):
    return {x.get("msg")} | {e["msg"] for e in x.get("evidence", [])} - {None}


def _at(x):
    return x.get("at") or x.get("raised_at")


def score(a, b):
    shared = bool(_msgs(a) & _msgs(b))
    ba, bb = _bigrams(_text(a)), _bigrams(_text(b))
    jac = len(ba & bb) / max(1, len(ba | bb))
    window = 36 * 3600 if "T" not in _at(a) or "T" not in _at(b) else 3 * 3600   # a date alone is matched within a day
    near = abs((_t(_at(a)) - _t(_at(b))).total_seconds()) <= window
    if shared:
        return 1.0 + jac
    return jac if (near and jac >= 0.25) else 0.0


def match(xs, ys):
    cand = sorted(((score(a, b), i, j) for i, a in enumerate(xs) for j, b in enumerate(ys)), reverse=True)
    used_i, used_j, pairs = set(), set(), []
    for s, i, j in cand:
        if s <= 0:
            break
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            pairs.append((i, j, round(s, 2)))
    return pairs


def agreement(runs, key):
    out = []
    for (ia, a), (ib, b) in itertools.combinations(enumerate(runs, 1), 2):
        xs, ys = a[key], b[key]
        m = len(match(xs, ys))
        out.append({"pair": "%d-%d" % (ia, ib), "a": len(xs), "b": len(ys), "matched": m,
                    "jaccard": round(m / max(1, len(xs) + len(ys) - m), 2)})
    return out


def expect_recall(run, spec):
    def hit(item, pool):
        keys = [k.lower() for k in item["keys"]]
        for x in pool:
            blob = (_text(x) + " " + " ".join(x.get("twigs", []))).lower()
            if any(k in blob for k in keys) and (item["kind"] == x["kind"] or "kind" not in item):
                return x
        return None
    res = {}
    for key in ("nodes", "open"):
        items = spec["expect"][key]
        got = [(it, hit(it, run[key])) for it in items]
        req = [g for g in got if g[0].get("required")]
        res[key] = {"required_found": sum(1 for _, x in req if x), "required": len(req),
                    "all_found": sum(1 for _, x in got if x), "all": len(items),
                    "missed": [it["about"] for it, x in got if not x]}
    bad = []
    for it in spec["expect"]["not_open"]:
        for x in run["open"]:
            if any(k.lower() in _text(x).lower() for k in it["keys"]):
                bad.append(it["about"])
    res["false_open"] = bad
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--expect")
    ap.add_argument("--reference")
    ap.add_argument("--show", action="store_true", help="print matched and unmatched labels")
    a = ap.parse_args()
    runs = [json.load(open(p, encoding="utf-8")) for p in a.runs]
    summary = {"counts": [{"nodes": len(r["nodes"]), "open": len(r["open"]),
                           "top_nodes": sum(1 for n in r["nodes"] if n["score"] >= 4)} for r in runs],
               "nodes": agreement(runs, "nodes"), "open": agreement(runs, "open")}
    top = [dict(r, nodes=[n for n in r["nodes"] if n["score"] >= 4]) for r in runs]
    summary["top_nodes"] = agreement(top, "nodes")
    if a.expect:
        spec = json.load(open(a.expect, encoding="utf-8"))
        summary["expect"] = [expect_recall(r, spec) for r in runs]
    if a.reference:
        ref = json.load(open(a.reference, encoding="utf-8"))
        summary["reference"] = []
        for k, r in enumerate(runs, 1):
            row = {}
            for key in ("nodes", "open"):
                pairs = match(ref[key], r[key])
                row[key] = {"reference": len(ref[key]), "run": len(r[key]), "matched": len(pairs)}
                if a.show:
                    got = {i for i, _, _ in pairs}
                    print("run %d %s matched:" % (k, key))
                    for i, j, s in pairs:
                        print("   %-24s <-> %-24s %s" % (ref[key][i]["label"], r[key][j]["label"], s))
                    print("run %d %s only in reference:" % (k, key), [ref[key][i]["label"] for i in range(len(ref[key])) if i not in got])
                    print("run %d %s only in run:" % (k, key), [r[key][j]["label"] for j in range(len(r[key])) if j not in {j for _, j, _ in pairs}])
            summary["reference"].append(row)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
