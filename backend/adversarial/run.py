"""Detection recall/precision on adversarial job posts: Dihari (extraction + code) vs an LLM-only baseline.
    python -m adversarial.run [--llm mock-a]
Rows: (1) LLM-only baseline  (2) Dihari = LLM extraction + pure-code checks  (3) code checks on ORACLE fields (upper bound of the code layer).
With only the mock provider configured, (1) and the extraction in (2) are regex stand-ins: the numbers check the pipeline wiring,
NOT real LLM quality. Re-run with real providers once configured."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.ai import pipeline, registry, service, validation
from app.ai.chain import Chain
from app.country_config import get_country

CLASSES = ["below_min_wage", "missing_payment_day", "hidden_deduction", "hours_exceed_max", "net_below_min_wage"]
NOW = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


def baseline_flags(text: str, chain: Chain) -> set[str]:
    try:
        r, _ = chain.call("complete_json", task="flag_violations", system="List wage-law violations in this job post.",
                          prompt=json.dumps({"text": text}, ensure_ascii=False), schema={"type": "object"})
        return set(r.get("flags", []))
    except Exception:  # noqa: BLE001
        return set()


def dihari_flags(text: str, cfg) -> set[str]:
    d = pipeline.draft_from_text(text, cfg, "ur", None, NOW)
    out = {v["code"] for v in (d["wage"] or {}).get("violations", [])}
    if "payment_day" in d["missing"]:
        out.add("missing_payment_day")      # a missing payment date IS the violation for this test set
    return out


def oracle_flags(spec: dict, cfg) -> set[str]:
    f = {"task": spec["trade"], "headcount": spec["headcount"], "location_text": spec["place"],
         "start_at": "2026-06-02T08:00:00+05:00", "daily_rate": spec["rate"], "hours_per_day": spec["hours"],
         "payment_day": "2026-06-05" if spec["pay"] else None,
         "deductions": {"none": [], "hidden": [{"label": "x", "amount": None}], "big": [{"label": "food", "amount": spec["ded_amt"]}]}[spec["ded"]],
         "advance": 0, "transport_mode": "none"}
    rep = validation.validate(f, cfg, "ur", NOW)
    out = {v["code"] for v in (rep.wage or {}).get("violations", [])}
    if "payment_day" in rep.missing:
        out.add("missing_payment_day")
    return out


def prf(preds: list[set], gold: list[set]) -> dict:
    res = {}
    for c in CLASSES + ["ALL"]:
        tp = fp = fn = 0
        for p, g in zip(preds, gold):
            ps = p & set(CLASSES) if c == "ALL" else ({c} & p)
            gs = g & set(CLASSES) if c == "ALL" else ({c} & g)
            tp += len(ps & gs); fp += len(ps - gs); fn += len(gs - ps)
        pr = tp / (tp + fp) if tp + fp else None
        rc = tp / (tp + fn) if tp + fn else None
        f1 = 2 * pr * rc / (pr + rc) if pr and rc else (0.0 if pr is not None and rc is not None else None)
        res[c] = (pr, rc, f1, tp + fn)
    return res


def fmt(x): return "n/a" if x is None else f"{x:.2f}"


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--llm", default="mock-a"); ap.add_argument("--posts", default=str(Path(__file__).with_name("posts.json")))
    a = ap.parse_args(argv)
    posts = json.loads(Path(a.posts).read_text(encoding="utf-8"))
    cfg = get_country("PK")
    service._cache["extract"] = Chain("llm", registry.build("llm", [a.llm]))
    chain = service.get_chain("extract")
    gold = [set(p["labels"]) for p in posts]
    rows = {"LLM-only baseline": [baseline_flags(p["text"], chain) for p in posts],
            "Dihari (LLM extraction + code checks)": [dihari_flags(p["text"], cfg) for p in posts],
            "Code checks on oracle fields (upper bound)": [oracle_flags(p["spec"], cfg) for p in posts]}
    real = chain.has_real
    print("# Adversarial detection report\n")
    print(f"- posts: {len(posts)} ({sum(1 for g in gold if not g)} clean, {sum(1 for g in gold if g)} with injected violations), styles: Urdu / English / romanised mix")
    print(f"- LLM provider(s): {a.llm} — {'REAL' if real else 'MOCK: regex stand-in, NOT a real LLM. These numbers test the pipeline wiring only.'}")
    print("- wage floor used for ground truth: placeholder rule (verified=false)")
    print("- CAVEAT: the posts are template-generated and the mock extractor was written alongside the templates, so a perfect")
    print("  score for rows 2-3 is expected and is NOT evidence of real-world detection quality. Meaningful numbers need a real")
    print("  extractor and independently written posts (pass --posts your.json in the same format).\n")
    for name, preds in rows.items():
        res = prf(preds, gold)
        print(f"## {name}\n\n| violation | precision | recall | F1 | positives |\n|---|---|---|---|---|")
        for c in CLASSES + ["ALL"]:
            pr, rc, f1, n = res[c]
            print(f"| {c} | {fmt(pr)} | {fmt(rc)} | {fmt(f1)} | {n} |")
        print()
    return rows


if __name__ == "__main__":
    main()
