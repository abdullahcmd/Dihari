"""Generates adversarial/posts.json: job posts with INJECTED violations and exact ground truth.
Deterministic (seeded). Mixed Urdu / English / romanised Urdu wording.   python -m adversarial.generate"""
import json
import random
from pathlib import Path

FLOOR_PLACEHOLDER = 1000   # ground truth uses the same placeholder rule the app ships with
MAX_H = 8

PLACES = ["G-13", "G-11", "F-10", "I-8", "E-11", "Saddar", "Chaklala"]
TRADES = [("tile", "tile work", "ٹائل کا کام", "tile ka kaam"), ("paint", "painting", "رنگ کا کام", "rang ka kaam"),
          ("mason", "mason work", "راج مستری کا کام", "mistri ka kaam"), ("plumber", "plumbing", "پلمبر کا کام", "plumber ka kaam")]
WORDS = {1: ("one", "ایک", "aik"), 2: ("two", "دو", "do"), 3: ("three", "تین", "teen"), 4: ("four", "چار", "chaar"), 5: ("five", "پانچ", "paanch")}


def render(spec: dict, style: str) -> str:
    n, place, tr = spec["headcount"], spec["place"], spec["trade"]
    t = next(x for x in TRADES if x[0] == tr)
    rate, hours = spec["rate"], spec["hours"]
    if style == "en":
        parts = [f"{WORDS[n][0]} workers needed tomorrow 8am for {t[1]} in {place}", f"{rate} a day", f"{hours} hours"]
        if spec["pay"]: parts.append(f"payment {spec['pay']}")
        if spec["ded"] == "hidden": parts.append("some deductions for food and tools")
        elif spec["ded"] == "big": parts.append(f"deduction {spec['ded_amt']} per day for food")
        elif spec["ded"] == "none": parts.append("no deductions")
        return ", ".join(parts)
    if style == "ur":
        parts = [f"{WORDS[n][1]} مزدور چاہئیں کل صبح 8 بجے {place} میں {t[2]}", f"روزانہ {rate} روپے", f"{hours} گھنٹے"]
        if spec["pay"]: parts.append(f"ادائیگی {spec['pay_ur']}")
        if spec["ded"] == "hidden": parts.append("کھانے اور اوزار کی کٹوتی ہو گی")
        elif spec["ded"] == "big": parts.append(f"کھانے کی کٹوتی {spec['ded_amt']} روزانہ")
        elif spec["ded"] == "none": parts.append("کٹوتی نہیں")
        return "، ".join(parts)
    parts = [f"kal subah 8 baje {place} mein {WORDS[n][2]} mazdoor chahiyen {t[3]}", f"{rate} rozana", f"{hours} ghantay"]
    if spec["pay"]: parts.append(f"payment {spec['pay']}")
    if spec["ded"] == "hidden": parts.append("katoti hogi khanay ki")
    elif spec["ded"] == "big": parts.append(f"khanay ki katoti {spec['ded_amt']} rozana")
    elif spec["ded"] == "none": parts.append("katoti nahi")
    return ", ".join(parts)


def labels(spec: dict) -> list[str]:
    out = []
    if spec["rate"] < FLOOR_PLACEHOLDER: out.append("below_min_wage")
    if spec["hours"] > MAX_H: out.append("hours_exceed_max")
    if not spec["pay"]: out.append("missing_payment_day")
    if spec["ded"] == "hidden": out.append("hidden_deduction")
    if spec["ded"] == "big" and spec["rate"] >= FLOOR_PLACEHOLDER and spec["rate"] - spec["ded_amt"] < FLOOR_PLACEHOLDER:
        out.append("net_below_min_wage")
    return sorted(out)


def main(seed: int = 11, per_class: int = 12):
    rng = random.Random(seed)
    posts = []
    def base():
        return {"headcount": rng.randint(2, 5), "place": rng.choice(PLACES), "trade": rng.choice(TRADES)[0],
                "rate": rng.randrange(1100, 2200, 100), "hours": 8, "pay": "friday", "pay_ur": "جمعہ", "ded": "none", "ded_amt": 0}
    injections = {
        "clean": lambda s: s,
        "below_min_wage": lambda s: {**s, "rate": rng.choice([500, 600, 700, 800, 900])},
        "no_payment_date": lambda s: {**s, "pay": None},
        "hidden_deduction": lambda s: {**s, "ded": "hidden"},
        "long_shift": lambda s: {**s, "hours": rng.choice([10, 12, 14])},
        "net_below_after_deduction": lambda s: {**s, "rate": 1100, "ded": "big", "ded_amt": rng.choice([300, 400])},
        "combo": lambda s: {**s, "rate": rng.choice([600, 700]), "hours": 12, "pay": None},
    }
    for cls, fn in injections.items():
        for i in range(per_class * (2 if cls == "clean" else 1)):
            s = fn(base()); style = ["en", "ur", "mixed"][i % 3]
            posts.append({"id": f"{cls}-{i:02d}", "class": cls, "style": style, "text": render(s, style), "spec": s, "labels": labels(s)})
    Path(__file__).with_name("posts.json").write_text(json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(posts)} posts")


if __name__ == "__main__":
    main()
