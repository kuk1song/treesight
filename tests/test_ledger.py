"""The ledger: ids, appending, closing across sessions, and the user's edits winning. Run: python3 -m unittest discover -s tests"""
import copy
import glob
import json
import os
import multiprocessing
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ledger  # noqa: E402
import transcript  # noqa: E402

PROJECT = "-home-dev-tidepool"
S2 = "0a182a7b-3fd8-56b9-a6e6-9fc77576e221"
T1 = glob.glob(os.path.join(ROOT, "fixtures", "projects", PROJECT, "953c0ab1-*.jsonl"))[0]
T2 = glob.glob(os.path.join(ROOT, "fixtures", "projects", PROJECT, "0a182a7b-*.jsonl"))[0]
with open(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), encoding="utf-8") as f:
    EXTRACT1 = json.load(f)


def entry(entries, text):
    """The (msg, entry) whose text contains `text`."""
    return next((m, e) for m, e in entries.items() if text in e["text"])


def ev(entries, text, quote=None):
    m, e = entry(entries, text)
    return {"quote": quote or text, "kind": e["kind"], "msg": m, "at": e["at"]}


def extract2(digest, by_label):
    """A hand-made extraction of tidepool-2 that closes items from tidepool-1."""
    _, es = ledger.parse_digest(digest)
    sid = ledger.re.search(r"^session: (\S+)$", digest, ledger.re.M).group(1)
    pub = ev(es, "0.3.0 is now on PyPI")
    blog = ev(es, "Let's write a short blog post about the 0.3.0 release")
    stuck = ev(es, "The release workflow failed at the publish step")
    close = lambda label, status, sure, text: dict(ev(es, text), id=by_label[label], status=status, sure=sure)
    closes = [close("maya", "done", True, "keep the calendar feed private"),
              close("token", "done", False, "they set up trusted publishing for the repo instead"),
              close("release", "done", True, "0.3.0 is now on PyPI"),
              close("pycon", "expired", True, "I completely missed the PyCon proposal deadline")]
    for c in closes:
        c.pop("kind")
    return {"schema": "treesight/extract@1", "session": sid, "through": list(es)[-1],
            "nodes": [{"ref": "n1", "kind": "done", "label": "0.3.0 on PyPI", "line": "You released 0.3.0 with trusted publishing.",
                       "at": pub["at"], "msg": pub["msg"], "score": 5, "evidence": [pub],
                       "story": {"minutes": 18, "q": "about", "basis": "first failure to release",
                                 "steps": [{"role": "stuck", "text": "Workflow name did not match", "at": stuck["at"], "at_q": "exact"},
                                           {"role": "response", "text": "Renamed it to publish.yml", "at": pub["at"], "at_q": "exact"},
                                           {"role": "result", "text": "0.3.0 is on PyPI", "at": pub["at"], "at_q": "exact"}]}}],
            "open": [{"ref": "o1", "kind": "todo", "label": "Release blog post", "line": "You plan a newsletter post about 0.3.0 this weekend.",
                      "raised_at": blog["at"], "msg": blog["msg"], "evidence": [blog]}],
            "close": closes}


class Ledger(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="treesight-test-")
        os.environ["TREESIGHT_HOME"] = self.home
        self.d1 = transcript.digest(T1)

    def tearDown(self):
        os.environ.pop("TREESIGHT_HOME", None)
        shutil.rmtree(self.home)

    def first(self):
        probs, summary = ledger.apply(EXTRACT1, self.d1, PROJECT, model="test")
        self.assertEqual(probs, [])
        return summary

    def labels(self, state):
        by = {}
        for o in state["open"] + state["closed"]:
            low = o["label"].lower()
            for key, word in (("maya", "maya"), ("token", "token"), ("release", "0.3.0"), ("pycon", "pycon"), ("list", "station"), ("windows", "windows")):
                if word in low:
                    by[key] = o["id"]
        return by

    def test_home_follows_xdg(self):
        os.environ.pop("TREESIGHT_HOME")
        os.environ["XDG_DATA_HOME"] = "/tmp/xdg-test"
        try:
            self.assertEqual(ledger.home(), "/tmp/xdg-test/treesight")
        finally:
            os.environ.pop("XDG_DATA_HOME")

    def test_ids_and_refs(self):
        summary = self.first()
        self.assertEqual(sorted(summary["ids"].values())[:2], ["953c0ab1-n1", "953c0ab1-n2"])
        state = ledger.load(PROJECT)
        s = state["sessions"][EXTRACT1["session"]]
        self.assertEqual(s["through"], EXTRACT1["through"])
        self.assertEqual(len(s["nodes"]), len(EXTRACT1["nodes"]))
        self.assertEqual(len(state["open"]), len(EXTRACT1["open"]))
        ids = {n["id"] for n in s["nodes"]}
        for n in s["nodes"]:
            if "overturns" in n:
                self.assertIn(n["overturns"], ids)
        oids = {o["id"] for o in state["open"]}
        self.assertTrue(all(o["blocked_by"] in oids for o in state["open"] if "blocked_by" in o))

    def test_nothing_written_on_problems(self):
        bad = copy.deepcopy(EXTRACT1)
        bad["nodes"][0]["evidence"][0]["quote"] = "never said"
        probs, _ = ledger.apply(bad, self.d1, PROJECT)
        self.assertTrue(probs)
        self.assertFalse(os.path.exists(os.path.join(ledger.project_dir(PROJECT), "ledger.jsonl")))

    def test_same_digest_twice_is_refused(self):
        self.first()
        probs, _ = ledger.apply(EXTRACT1, self.d1, PROJECT)
        self.assertTrue(any("already read" in p for p in probs))

    def test_later_session_closes_earlier_items(self):
        self.first()
        by = self.labels(ledger.load(PROJECT))
        d2 = transcript.digest(T2, known=ledger.known_for(ledger.load(PROJECT), "0a182a7b-3fd8-56b9-a6e6-9fc77576e221"))
        self.assertIn("already in the ledger", d2)
        probs, _ = ledger.apply(extract2(d2, by), d2, PROJECT)
        self.assertEqual(probs, [])
        state = ledger.load(PROJECT)
        st = {o["id"]: o["state"] for o in state["open"]}
        self.assertNotIn(by["maya"], st)
        self.assertNotIn(by["release"], st)
        self.assertEqual(st[by["token"]], "confirm")
        self.assertEqual(st[by["pycon"]], "stale")
        self.assertEqual(st[by["list"]], "open")
        self.assertEqual({c["id"] for c in state["closed"]}, {by["maya"], by["release"]})
        self.assertTrue(any(o["id"].startswith("0a182a7b-o") for o in state["open"]))

    def test_a_run_reports_what_its_closes_did(self):
        self.first()
        by = self.labels(ledger.load(PROJECT))
        d2 = transcript.digest(T2, known=ledger.known_for(ledger.load(PROJECT), S2))
        probs, summary = ledger.apply(extract2(d2, by), d2, PROJECT)
        self.assertEqual(probs, [])
        # 4 closes proposed: maya and the release closed, the token unsure, the PyCon proposal no longer possible
        self.assertEqual((summary["close"], summary["closed"], summary["to_confirm"]), (4, 2, 2))
        self.assertEqual(summary["open_in_project"], len(EXTRACT1["open"]) - 2 + 1)
        lr = ledger.load(PROJECT)["sessions"][S2]["last_run"]
        self.assertEqual((lr["nodes"], lr["open"], lr["closed"], lr["flagged"]), (1, 1, 2, 2))

    def test_a_close_cannot_quote_something_said_before_the_item_was_raised(self):
        d2 = transcript.digest(T2)                       # the later session drawn first
        e2 = extract2(d2, dict.fromkeys(("maya", "token", "release", "pycon"), "x"))
        e2["close"] = []
        self.assertEqual(ledger.apply(e2, d2, PROJECT)[0], [])
        blog = next(o["id"] for o in ledger.load(PROJECT)["open"])
        d1 = transcript.digest(T1, known=ledger.known_for(ledger.load(PROJECT), EXTRACT1["session"]))
        e1 = copy.deepcopy(EXTRACT1)
        e1["close"] = [dict(ev(ledger.parse_digest(d1)[1], "Let's add ICS export"), id=blog, status="done", sure=True)]
        e1["close"][0].pop("kind")
        probs, _ = ledger.apply(e1, d1, PROJECT)
        self.assertTrue(any("from before %s was raised" % blog in p for p in probs), probs)

    def test_a_session_drawn_after_a_later_one_can_settle_its_new_items_by_that_ones_records(self):
        d2 = transcript.digest(T2)                       # the later session drawn first: nothing of the earlier one to close
        e2 = extract2(d2, dict.fromkeys(("maya", "token", "release", "pycon"), "x"))
        e2["close"] = []
        self.assertEqual(ledger.apply(e2, d2, PROJECT)[0], [])
        node = ledger.load(PROJECT)["sessions"][S2]["nodes"][0]
        known = ledger.known_for(ledger.load(PROJECT), EXTRACT1["session"])
        d1 = transcript.digest(T1, known=known)
        self.assertIn("later records", d1)
        self.assertIn("  later %s [done] %s 0.3.0 on PyPI: " % (node["id"], node["evidence"][0]["at"]), d1)
        release = next(o["ref"] for o in EXTRACT1["open"] if "0.3.0" in o["label"])

        def with_settled(*settled):
            e = copy.deepcopy(EXTRACT1)
            e["settled"] = [dict(zip(("ref", "by", "status", "sure"), s)) for s in settled]
            return e
        for bad, why in ((with_settled(("o9", node["id"], "done", True)), "not an open item of this output"),
                         (with_settled((release, S2[:8] + "-n9", "done", True)), "not one of the later records"),
                         (with_settled((release, node["id"], "done", True), (release, node["id"], "done", True)), "settled twice")):
            probs, _ = ledger.apply(bad, d1, PROJECT)
            self.assertTrue(any(why in p for p in probs), (why, probs))
        probs, summary = ledger.apply(with_settled((release, node["id"], "done", True)), d1, PROJECT)
        self.assertEqual(probs, [])
        self.assertEqual((summary["settled"], summary["closed"], summary["to_confirm"]), (1, 1, 0))
        state = ledger.load(PROJECT)
        rid = summary["ids"][release]
        self.assertNotIn(rid, {o["id"] for o in state["open"]})
        closed = next(c for c in state["closed"] if c["id"] == rid)
        self.assertEqual((closed["quote"], closed["msg"], closed["via"]), (node["evidence"][0]["quote"], node["evidence"][0]["msg"], node["id"]))

    def test_later_records_are_only_from_after_the_digest_starts_and_not_what_the_user_undid(self):
        self.first()
        by = self.labels(ledger.load(PROJECT))
        d2 = transcript.digest(T2, known=ledger.known_for(ledger.load(PROJECT), S2))
        self.assertNotIn("later records", d2)            # drawn in time order: nothing later to show
        ledger.apply(extract2(d2, by), d2, PROJECT)
        known = ledger.known_for(ledger.load(PROJECT), EXTRACT1["session"])
        self.assertEqual({r["id"] for r in known["later"] if r["what"].startswith("closed")}, {by["maya"], by["token"], by["release"], by["pycon"]})
        ledger.edit(PROJECT, "reopen", by["token"])       # the user said the unsure close was wrong
        ledger.edit(PROJECT, "hide", ledger.load(PROJECT)["sessions"][S2]["nodes"][0]["id"])
        known = ledger.known_for(ledger.load(PROJECT), EXTRACT1["session"])
        self.assertEqual({r["id"] for r in known["later"]}, {by["maya"], by["release"], by["pycon"]})
        many = [{"id": "%s-n%d" % (S2[:8], i), "what": "done", "label": "Step %d" % i, "line": "x " * 100, "quote": "q " * 150,
                 "at": "2026-09-23T10:%02d:00.000Z" % (i % 60)} for i in range(400)]
        lines = transcript._later_lines(sorted(many, key=lambda r: r["at"]), "2026-09-20T00:00:00.000Z")
        self.assertLessEqual(sum(len(x) + 1 for x in lines[1:]), transcript.LATER_CHARS)
        self.assertIn("older ones left out", lines[0])
        self.assertEqual(transcript._later_lines(many, "2026-09-24T00:00:00.000Z"), [])

    def test_a_close_must_carry_its_entrys_time(self):
        self.first()
        by = self.labels(ledger.load(PROJECT))
        d2 = transcript.digest(T2, known=ledger.known_for(ledger.load(PROJECT), S2))
        e = extract2(d2, by)
        e["close"][0]["at"] = "2026-12-31T00:00:00.000Z"
        probs, _ = ledger.apply(e, d2, PROJECT)
        self.assertTrue(any("close[0]: at 2026-12-31" in p for p in probs), probs)

    def test_settled_records_are_checked_against_the_header_the_ledger_and_the_time(self):
        rec = {"id": S2[:8] + "-n7", "what": "done", "label": "Windows build", "line": "x", "quote": "q", "msg": S2, "at": "2026-09-15T09:30:00.000Z"}
        known = {"nodes": [], "open": [], "later": [rec]}
        d1 = transcript.digest(T1, known=known)
        self.assertIn("  later %s " % rec["id"], d1)
        e = copy.deepcopy(EXTRACT1)
        windows = next(o for o in e["open"] if "Windows" in o["label"])      # raised at 09:45, after the record
        e["settled"] = [{"ref": windows["ref"], "by": rec["id"], "status": "done", "sure": True}]
        self.assertTrue(any("is from before %s was raised" % windows["ref"] in p for p in ledger.check(e, d1, known)))
        self.assertTrue(any("no longer in the ledger" in p for p in ledger.check(e, d1, dict(known, later=[]))))
        e["settled"][0]["ref"] = next(o["ref"] for o in e["open"] if o["raised_at"] < rec["at"])
        self.assertEqual(ledger.check(e, d1, known), [])

    def test_a_date_without_a_time_counts_from_its_earliest_start(self):
        self.assertFalse(ledger.before("2026-09-14T12:00:00.000Z", "2026-09-15"))   # already 09-15 in UTC+14
        self.assertTrue(ledger.before("2026-09-14T09:00:00.000Z", "2026-09-15"))
        self.assertTrue(ledger.before("2026-09-15T09:00:00Z", "2026-09-15T09:00:00.001Z"))
        self.assertFalse(ledger.before("2026-09-15T09:00:00Z", "2026-09-15T09:00:00.000Z"))

    def test_the_counts_of_a_run_follow_what_the_user_changed(self):
        item = {"id": "aaaaaaaa-o1", "kind": "todo", "label": "Token", "line": "x", "raised_at": "2026-09-15T09:00:00Z"}
        run = lambda sid, r: {"ev": "run", "session": sid, "run": r, "at": "2026-09-30T00:00:00Z", "through": sid}
        close = lambda sid, r, sure: {"ev": "close", "session": sid, "run": r,
                                      "close": {"id": item["id"], "status": "done", "sure": sure, "quote": "q", "msg": sid, "at": "2026-09-20T00:00:00Z"}}
        events = [run("a", "r1"), {"ev": "open", "session": "a", "run": "r1", "item": item},
                  run("b", "r2"), close("b", "r2", False), run("c", "r3"), close("c", "r3", True)]
        state = ledger.view(events, [{"ev": "reopen", "target": item["id"], "at": "2026-09-21T00:00:00Z"}])
        self.assertEqual([o["id"] for o in state["open"]], [item["id"]])          # the user's reopen wins
        self.assertEqual({k: state["sessions"]["c"]["last_run"][k] for k in ("closed", "flagged")}, {"closed": 0, "flagged": 0})
        self.assertEqual(state["closes"], [])
        state = ledger.view(events[:4])
        self.assertEqual(state["sessions"]["b"]["last_run"]["flagged"], 1)
        state = ledger.view(events[:4], [{"ev": "hide", "target": item["id"], "at": "2026-09-21T00:00:00Z"}])
        self.assertEqual((state["sessions"]["b"]["last_run"]["flagged"], state["closes"]), (0, []))   # hidden: neither counted nor evidence

    def test_items_raised_after_the_digest_starts_say_when(self):
        d2 = transcript.digest(T2)
        e2 = extract2(d2, dict.fromkeys(("maya", "token", "release", "pycon"), "x"))
        e2["close"] = []
        ledger.apply(e2, d2, PROJECT)
        d1 = transcript.digest(T1, known=ledger.known_for(ledger.load(PROJECT), EXTRACT1["session"]))
        self.assertIn(", after this digest starts)", d1)
        os.environ["TREESIGHT_HOME"] = tempfile.mkdtemp(dir=self.home)                # in time order: the header is as before
        self.first()
        d2 = transcript.digest(T2, known=ledger.known_for(ledger.load(PROJECT), S2))
        self.assertNotIn("after this digest starts", d2)
        self.assertNotIn("later records", d2)

    def test_close_of_an_unknown_item_is_refused(self):
        self.first()
        by = self.labels(ledger.load(PROJECT))
        d2 = transcript.digest(T2)
        e = extract2(d2, by)
        e["close"][0]["id"] = "953c0ab1-o99"
        probs, _ = ledger.apply(e, d2, PROJECT)
        self.assertTrue(any("not an open item" in p for p in probs))

    def test_user_edits_win(self):
        self.first()
        by = self.labels(ledger.load(PROJECT))
        d2 = transcript.digest(T2)
        ledger.apply(extract2(d2, by), d2, PROJECT)
        ledger.edit(PROJECT, "close", by["token"])
        ledger.edit(PROJECT, "reopen", by["maya"])
        ledger.edit(PROJECT, "set", by["list"], {"label": "Club station list", "who": "Maya"})
        node = ledger.load(PROJECT)["sessions"][EXTRACT1["session"]]["nodes"][0]["id"]
        ledger.edit(PROJECT, "hide", node)
        state = ledger.load(PROJECT)
        st = {o["id"]: o for o in state["open"]}
        self.assertNotIn(by["token"], st)
        self.assertEqual(st[by["maya"]]["state"], "open")
        self.assertEqual(st[by["list"]]["label"], "Club station list")
        self.assertNotIn(node, {n["id"] for n in state["sessions"][EXTRACT1["session"]]["nodes"]})
        with self.assertRaises(ValueError):
            ledger.edit(PROJECT, "set", by["list"], {"msg": "x"})
        with self.assertRaises(ValueError):
            ledger.edit(PROJECT, "close", "953c0ab1-o99")

    def test_edits_that_do_not_apply_or_would_break_the_page_are_refused(self):
        self.first()
        state = ledger.load(PROJECT)
        by = self.labels(state)
        node = state["sessions"][EXTRACT1["session"]]["nodes"][0]["id"]
        for action, target, fields in (("close", node, None), ("reopen", by["maya"], None), ("set", by["maya"], {"kind": "done"}),
                                       ("set", node, {"kind": "todo"}), ("set", by["maya"], {"due": "soon"}),
                                       ("set", by["maya"], {"blocked_by": by["maya"]}), ("set", by["maya"], {})):
            with self.assertRaises(ValueError, msg=(action, fields)):
                ledger.edit(PROJECT, action, target, fields)
        self.assertFalse(os.path.exists(os.path.join(ledger.project_dir(PROJECT), "edits.jsonl")))
        ledger.edit(PROJECT, "set", node, {"label": "Feed stays private", "score": 5})
        self.assertEqual(ledger.load(PROJECT)["sessions"][EXTRACT1["session"]]["nodes"][0]["label"], "Feed stays private")

    def test_reopen_rejects_an_unsure_close_and_old_blockers_do_not_lock_an_item(self):
        self.first()
        by = self.labels(ledger.load(PROJECT))
        d2 = transcript.digest(T2, known=ledger.known_for(ledger.load(PROJECT), "0a182a7b-3fd8-56b9-a6e6-9fc77576e221"))
        ledger.apply(extract2(d2, by), d2, PROJECT)
        st = {o["id"]: o["state"] for o in ledger.load(PROJECT)["open"]}
        self.assertEqual((st[by["token"]], st[by["pycon"]]), ("confirm", "stale"))
        ledger.edit(PROJECT, "reopen", by["token"])           # "looks done": no, it is not
        ledger.edit(PROJECT, "reopen", by["pycon"])           # "no longer possible": it still is
        st = {o["id"]: o["state"] for o in ledger.load(PROJECT)["open"]}
        self.assertEqual((st[by["token"]], st[by["pycon"]]), ("open", "open"))
        ledger.edit(PROJECT, "set", by["list"], {"blocked_by": by["windows"]})
        ledger.edit(PROJECT, "close", by["windows"])
        ledger.edit(PROJECT, "set", by["list"], {"when": "after the trip"})    # its blocker is closed now
        ledger.edit(PROJECT, "set", by["list"], {"blocked_by": "", "due": ""})  # empty clears a field
        item = next(o for o in ledger.load(PROJECT)["open"] if o["id"] == by["list"])
        self.assertNotIn("blocked_by", item)
        self.assertEqual(item["when"], "after the trip")

    def test_session_metadata_is_kept_with_the_run(self):
        meta = {"title": "ICS export", "custom_title": False, "first_at": "2026-09-14T09:02:11.000Z", "last_at": "2026-09-15T09:48:01.000Z",
                "prompts": {"total": 15, "substantive": 15}, "compactions": 1, "summary": "You added ICS export.", "cwd": "/home/dev/tidepool",
                "not kept": 1}
        probs, _ = ledger.apply(EXTRACT1, self.d1, PROJECT, meta=meta)
        self.assertEqual(probs, [])
        kept = ledger.load(PROJECT)["sessions"][EXTRACT1["session"]]["meta"]
        self.assertEqual(kept, {k: v for k, v in meta.items() if k != "not kept"})

    @unittest.skipUnless(ledger.fcntl, "no file locks on this system")
    def test_two_runs_at_once_cannot_number_items_from_the_same_state(self):
        ctx = multiprocessing.get_context("fork")
        start, results = ctx.Barrier(3), ctx.Queue()

        def worker():
            numbers = ledger._next_numbers

            def slow(*a):        # widen the window between reading the ledger and appending to it
                time.sleep(0.3)
                return numbers(*a)
            ledger._next_numbers = slow
            start.wait(10)
            results.put(ledger.apply(EXTRACT1, self.d1, PROJECT)[0])
        procs = [ctx.Process(target=worker) for _ in range(3)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(30)
        probs = [results.get(timeout=5) for _ in procs]
        self.assertEqual(sum(1 for p in probs if not p), 1, probs)
        self.assertTrue(all(any("already read" in x for x in p) for p in probs if p))
        events = ledger._read(os.path.join(ledger.project_dir(PROJECT), "ledger.jsonl"))
        ids = [e["node"]["id"] for e in events if e.get("ev") == "node"] + [e["item"]["id"] for e in events if e.get("ev") == "open"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(1 for e in events if e.get("ev") == "run"), 1)

    def test_ledger_only_grows(self):
        self.first()
        path = os.path.join(ledger.project_dir(PROJECT), "ledger.jsonl")
        with open(path, encoding="utf-8") as f:
            before = f.read()
        by = self.labels(ledger.load(PROJECT))
        d2 = transcript.digest(T2)
        ledger.apply(extract2(d2, by), d2, PROJECT)
        with open(path, encoding="utf-8") as f:
            after = f.read()
        self.assertTrue(after.startswith(before) and len(after) > len(before))


if __name__ == "__main__":
    unittest.main()
