from datetime import date

from sim import simulate as S
from app.modules import wage_floor


def test_sim_small_run_is_deterministic_and_prints_assumptions_first():
    rule = wage_floor.find_rule("PK", "ICT", date.today())
    p = S.P(n_workers=60, n_hirers=15, days=3)
    a = S.run(p, "dihari", rule.min_daily_wage, 1)
    b = S.run(p, "dihari", rule.min_daily_wage, 1)
    assert a == b
    assert a["share_slots_at_floor"] == 1.0           # the floor holds by construction in the Dihari regime
    txt = S.report(p, 2, rule)
    assert txt.index("## Assumptions") < txt.index("## Results")
    assert "placeholder" in txt and "not real-world results" in txt
    for key in ("adda", "bidding", "dihari"):
        assert S.run(p, key, rule.min_daily_wage, 2)["fill_rate"] >= 0
