from adversarial import run as A
from adversarial.generate import labels
import json
from pathlib import Path


def test_dataset_labels_are_consistent_with_specs():
    posts = json.loads((Path(A.__file__).with_name("posts.json")).read_text(encoding="utf-8"))
    assert len(posts) >= 90 and {p["style"] for p in posts} == {"en", "ur", "mixed"}
    assert all(sorted(p["labels"]) == labels(p["spec"]) for p in posts)


def test_code_layer_is_exact_and_beats_naive_baseline(capsys):
    rows = A.main([])
    posts = json.loads((Path(A.__file__).with_name("posts.json")).read_text(encoding="utf-8"))
    gold = [set(p["labels"]) for p in posts]
    oracle = A.prf(rows["Code checks on oracle fields (upper bound)"], gold)["ALL"]
    base = A.prf(rows["LLM-only baseline"], gold)["ALL"]
    assert oracle[0] == 1.0 and oracle[1] == 1.0          # pure-code validators are exact given correct fields
    assert base[2] < oracle[2]
    assert "MOCK" in capsys.readouterr().out               # the report never passes mock numbers off as real
