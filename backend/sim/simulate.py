"""Agent-based simulation: (a) labour adda  (b) open bidding, no floor  (c) Dihari.
Every number in the report is produced by running this script. The model shows a MECHANISM under stated
assumptions — it is not a forecast and not evidence of real-world effect.

    python -m sim.simulate [--workers 500] [--hirers 100] [--days 20] [--seeds 5] [--out sim/report.md]
"""
import argparse
import math
import random
import statistics as st
from dataclasses import dataclass, field, asdict
from datetime import date

from app.modules import wage_floor


@dataclass
class P:
    # world
    n_workers: int = 500
    n_hirers: int = 100
    days: int = 20
    city_km: float = 20.0           # square city, km
    n_addas: int = 4
    # demand
    p_job_per_hirer_day: float = 0.40
    headcount_choices: tuple = (1, 2, 3, 4, 6)
    offer_mean: float = 1150.0      # hirer's initial offered daily rate
    offer_sd: float = 250.0
    wtp_uplift: tuple = (1.0, 1.6)  # hirer's max willingness to pay = offer * U(a,b)
    request_window_min: tuple = (0, 180)   # job requested between 06:00 and 09:00
    # supply
    reservation_mean: float = 1000.0
    reservation_sd: float = 150.0
    work_hours: float = 8.0
    window_start_h: float = 6.0
    # adda
    p_go_adda: float = 0.90
    adda_decay_per_hour: float = 0.06   # desperation: reservation falls this much per hour waited (min 70%)
    haggle_step: float = 0.05
    haggle_minutes: int = 10
    p_wage_cut_adda: float = 0.10       # hirer pays 80% of the agreed wage after the work
    # bidding
    bid_radius_km: float = 8.0
    bid_shading_per_competitor: float = 0.06   # race to the bottom: bid shaved per extra bidder per slot (max 30%)
    bid_window_min: int = 45
    # dihari
    dihari_radius_km: float = 8.0
    response_mean_min: float = 20.0
    p_abandon_if_below_floor_wtp: float = 1.0  # hirer whose max WTP < floor cannot post
    # payment risk
    frac_bad_hirers: float = 0.15
    p_unpaid_bad: float = 0.50
    p_unpaid_good: float = 0.03
    dihari_min_reports: int = 3
    dihari_avoid_below: float = 0.60    # workers skip hirers whose self-reported on-time rate is below this
    dihari_restrict_after: int = 3      # hirer restricted after this many unpaid reports
    # costs
    travel_cost_per_km: float = 15.0
    travel_min_per_km: float = 3.0


@dataclass
class Worker:
    x: float; y: float; r0: float; adda: int; goes_adda: bool
    busy: bool = False


@dataclass
class Hirer:
    x: float; y: float; bad: bool
    paid: int = 0; unpaid: int = 0; restricted: bool = False
    def rate(self): return self.paid / (self.paid + self.unpaid) if self.paid + self.unpaid else None


@dataclass
class Job:
    hirer: int; t0: float; n: int; offer: float; wtp: float; x: float; y: float


@dataclass
class Stats:
    fill_minutes: list = field(default_factory=list)
    filled_slots: int = 0
    wanted_slots: int = 0
    jobs_posted: int = 0
    jobs_fully_filled: int = 0
    jobs_abandoned: int = 0
    slot_rates: list = field(default_factory=list)
    job_all_at_floor: list = field(default_factory=list)
    idle_hours: float = 0.0
    take_home: float = 0.0
    worker_days: int = 0
    employed_days: int = 0
    unpaid_events: int = 0
    wage_cut_events: int = 0


def dist(ax, ay, bx, by): return math.hypot(ax - bx, ay - by)


def build_world(p: P, rng: random.Random):
    addas = [(rng.uniform(.2, .8) * p.city_km, rng.uniform(.2, .8) * p.city_km) for _ in range(p.n_addas)]
    workers = []
    for _ in range(p.n_workers):
        x, y = rng.uniform(0, p.city_km), rng.uniform(0, p.city_km)
        a = min(range(p.n_addas), key=lambda k: dist(x, y, *addas[k]))
        workers.append(Worker(x, y, max(600.0, rng.gauss(p.reservation_mean, p.reservation_sd)), a, False))
    hirers = [Hirer(rng.uniform(0, p.city_km), rng.uniform(0, p.city_km), rng.random() < p.frac_bad_hirers) for _ in range(p.n_hirers)]
    return addas, workers, hirers


def gen_jobs(p: P, rng: random.Random, hirers) -> list[Job]:
    jobs = []
    for i, h in enumerate(hirers):
        if rng.random() < p.p_job_per_hirer_day:
            offer = max(300.0, rng.gauss(p.offer_mean, p.offer_sd))
            jobs.append(Job(i, rng.uniform(*p.request_window_min), rng.choice(p.headcount_choices), offer,
                            offer * rng.uniform(*p.wtp_uplift), rng.uniform(0, p.city_km), rng.uniform(0, p.city_km)))
    return sorted(jobs, key=lambda j: j.t0)


def settle(p, rng, S: Stats, w: Worker, h: Hirer, rate: float, travel_km: float, hired_min: float, regime: str):
    """Pay-day outcome for one hired worker (payment status is what the worker experiences)."""
    S.employed_days += 1
    paid_ok = rng.random() >= (p.p_unpaid_bad if h.bad else p.p_unpaid_good)
    pay = rate
    if regime == "adda" and rng.random() < p.p_wage_cut_adda:
        pay *= 0.8; S.wage_cut_events += 1
    if not paid_ok:
        pay = 0.0; S.unpaid_events += 1
        h.unpaid += 1
    else:
        h.paid += 1
    S.take_home += pay - travel_km * p.travel_cost_per_km
    S.idle_hours += hired_min / 60.0
    S.slot_rates.append(rate)


def run_day(p: P, rng: random.Random, regime: str, floor: float, addas, workers, hirers, S: Stats):
    for w in workers:
        w.busy = False
        w.goes_adda = rng.random() < p.p_go_adda
    S.worker_days += len(workers)
    for jb in gen_jobs(p, rng, hirers):
        h = hirers[jb.hirer]
        if regime == "dihari" and h.restricted:
            continue
        S.wanted_slots += jb.n; S.jobs_posted += 1
        picked: list[tuple[Worker, float, float]] = []   # (worker, rate, km travelled)
        fill_t = None
        if regime == "adda":
            ax, ay = addas[min(range(p.n_addas), key=lambda k: dist(jb.x, jb.y, *addas[k]))]
            a_idx = min(range(p.n_addas), key=lambda k: dist(jb.x, jb.y, *addas[k]))
            arrive = jb.t0 + dist(h.x, h.y, ax, ay) * p.travel_min_per_km
            crowd = [w for w in workers if not w.busy and w.goes_adda and w.adda == a_idx]
            price, k = jb.offer, 0
            while True:
                t = arrive + k * p.haggle_minutes
                hours_waited = max(0.0, (t / 60.0))
                acc = [w for w in crowd if w.r0 * max(0.7, 1 - p.adda_decay_per_hour * hours_waited) <= price]
                if len(acc) >= jb.n or price >= jb.wtp:
                    break
                price = min(jb.wtp, price * (1 + p.haggle_step)); k += 1
            acc.sort(key=lambda w: dist(w.x, w.y, ax, ay))
            for w in acc[:jb.n]:
                picked.append((w, price, dist(w.x, w.y, ax, ay) + dist(ax, ay, jb.x, jb.y)))
            fill_t = arrive + k * p.haggle_minutes
        elif regime == "bidding":
            near = [w for w in workers if not w.busy and dist(w.x, w.y, jb.x, jb.y) <= p.bid_radius_km]
            comp = max(0.0, len(near) / jb.n - 1)
            shade = min(0.30, p.bid_shading_per_competitor * comp)
            bids = [(w.r0 * (1 - shade), w) for w in near if w.r0 * (1 - shade) <= jb.offer]
            bids.sort(key=lambda b: (b[0], dist(b[1].x, b[1].y, jb.x, jb.y)))
            for b, w in bids[:jb.n]:
                picked.append((w, b, dist(w.x, w.y, jb.x, jb.y)))
            fill_t = jb.t0 + p.bid_window_min
        else:  # dihari
            offer = jb.offer
            if offer < floor:
                if jb.wtp < floor:
                    S.jobs_abandoned += 1
                    continue
                offer = floor                      # the hirer fixes the offer after being stopped by the floor
            cands = []
            for w in workers:
                if w.busy or dist(w.x, w.y, jb.x, jb.y) > p.dihari_radius_km:
                    continue
                r = h.rate()
                if r is not None and h.paid + h.unpaid >= p.dihari_min_reports and r < p.dihari_avoid_below:
                    continue                       # workers see the hirer's reputation and decline
                if offer >= w.r0:
                    rate = offer
                elif w.r0 <= min(2 * offer, jb.wtp):
                    rate = w.r0                    # upward-only counter, hirer can afford it
                else:
                    continue
                resp = rng.expovariate(1 / p.response_mean_min)
                cands.append((resp, rate, w))
            cands.sort(key=lambda c: c[0])
            window = [c for c in cands if c[0] <= p.bid_window_min]
            if len(window) >= jb.n:
                fill_t = jb.t0 + sorted(c[0] for c in window)[jb.n - 1]
            else:
                fill_t = jb.t0 + p.bid_window_min
            score = lambda c: (c[1] / offer) * 0.5 + dist(c[2].x, c[2].y, jb.x, jb.y) * 0.05 + c[0] / 600
            for resp, rate, w in sorted(window, key=score)[:jb.n]:
                picked.append((w, rate, dist(w.x, w.y, jb.x, jb.y)))
        if not picked:
            S.fill_minutes.append(720.0)
            continue
        for w, rate, km in picked:
            w.busy = True
            settle(p, rng, S, w, h, rate, km, fill_t - 0 + p.window_start_h * 0 + 0, regime)
        S.filled_slots += len(picked)
        S.jobs_fully_filled += len(picked) == jb.n
        S.fill_minutes.append(min(720.0, max(0.0, fill_t - jb.t0)))
        S.job_all_at_floor.append(all(r >= floor for _, r, _ in picked))
        if regime == "dihari":
            if h.unpaid >= p.dihari_restrict_after:
                h.restricted = True
    # unemployed worker-days: idle for the whole working window
    S.idle_hours += sum(p.work_hours for w in workers if not w.busy)


def run(p: P, regime: str, floor: float, seed: int) -> dict:
    rng = random.Random(seed)
    addas, workers, hirers = build_world(p, rng)
    S = Stats()
    for _ in range(p.days):
        run_day(p, rng, regime, floor, addas, workers, hirers, S)
    emp = max(S.employed_days, 1)
    return {
        "time_to_fill_h": st.mean(S.fill_minutes) / 60 if S.fill_minutes else float("nan"),
        "fill_rate": S.filled_slots / max(S.wanted_slots, 1),
        "idle_h_per_worker_day": S.idle_hours / S.worker_days,
        "share_slots_at_floor": sum(r >= floor for r in S.slot_rates) / max(len(S.slot_rates), 1),
        "share_jobs_all_at_floor": sum(S.job_all_at_floor) / max(len(S.job_all_at_floor), 1),
        "avg_take_home_per_worker_day": S.take_home / S.worker_days,
        "avg_take_home_per_employed_day": S.take_home / emp,
        "mean_agreed_rate": st.mean(S.slot_rates) if S.slot_rates else float("nan"),
        "unpaid_share_of_hires": S.unpaid_events / emp,
        "jobs_abandoned": S.jobs_abandoned / max(S.jobs_posted + S.jobs_abandoned, 1) if regime == "dihari" else 0.0,
    }


REGIMES = [("adda", "(a) Labour adda"), ("bidding", "(b) Bidding, no floor"), ("dihari", "(c) Dihari")]
METRICS = [("time_to_fill_h", "Time to fill (h, per job)", "{:.2f}"), ("fill_rate", "Share of requested slots filled", "{:.1%}"),
           ("idle_h_per_worker_day", "Worker idle hours / worker-day", "{:.2f}"), ("share_slots_at_floor", "Hired slots at/above floor", "{:.1%}"),
           ("share_jobs_all_at_floor", "Jobs with ALL slots at/above floor", "{:.1%}"), ("mean_agreed_rate", "Mean agreed daily rate", "{:.0f}"),
           ("unpaid_share_of_hires", "Hires ending unpaid", "{:.1%}"),
           ("avg_take_home_per_employed_day", "Avg take-home / employed day (after unpaid, wage cuts, travel)", "{:.0f}"),
           ("avg_take_home_per_worker_day", "Avg take-home / worker-day (incl. unemployed days)", "{:.0f}"),
           ("jobs_abandoned", "Jobs abandoned by hirer because of the floor", "{:.1%}")]


def report(p: P, seeds: int, floor_rule) -> str:
    out = []
    out.append("# Dihari simulation report (generated by `python -m sim.simulate` — do not edit by hand)\n")
    out.append("## Assumptions (all invented for illustration; change them in `sim/simulate.py:P`)\n")
    for k, v in asdict(p).items():
        out.append(f"- `{k}` = {v}")
    out.append(f"- wage floor = **{floor_rule.min_daily_wage}** from rule `{floor_rule.version}` "
               f"(verified={floor_rule.verified}, placeholder={floor_rule.placeholder}) — a placeholder, not a legal figure")
    out.append(f"- replications: {seeds} seeds (mean ± sd across seeds)")
    out.append("- Dihari does NOT create jobs: demand is identical in all three regimes. Differences come only from matching, "
               "the floor, upward-only counters and reputation, under the behavioural assumptions above.")
    out.append("- Payment risk, wage cuts, bid-shading and desperation decay are modelling choices; a different choice can change the ranking.\n")
    res = {k: [run(p, k, floor_rule.min_daily_wage, 1000 + s) for s in range(seeds)] for k, _ in REGIMES}
    out.append("## Results\n")
    out.append("| Metric | " + " | ".join(n for _, n in REGIMES) + " |")
    out.append("|---|" + "---|" * len(REGIMES))
    for key, label, fmt in METRICS:
        cells = []
        for k, _ in REGIMES:
            vals = [r[key] for r in res[k]]
            m = st.mean(vals); sd = st.pstdev(vals)
            cells.append(f"{fmt.format(m)} ± {fmt.format(sd)}")
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    out.append("\nThe simulation shows a mechanism under stated assumptions, not real-world results.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=500); ap.add_argument("--hirers", type=int, default=100)
    ap.add_argument("--days", type=int, default=20); ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--country", default="PK"); ap.add_argument("--region", default=None)
    ap.add_argument("--out", default="sim/report.md")
    a = ap.parse_args(argv)
    from app.country_config import get_country
    cfg = get_country(a.country)
    rule = wage_floor.find_rule(cfg.code, a.region or cfg.default_region, date.today())
    p = P(n_workers=a.workers, n_hirers=a.hirers, days=a.days)
    text = report(p, a.seeds, rule)
    print(text)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")


if __name__ == "__main__":
    main()
