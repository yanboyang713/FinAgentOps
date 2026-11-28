"""Small reproducible study of paid inspection for risk-aware cloud placement.

All infrastructure and price values below are illustrative simulation inputs, not
provider quotes. Run: python3 experiment.py [--episodes N] [--seed S]
"""
from __future__ import annotations

import argparse
import csv
import itertools
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Cloud:
    name: str
    compute_cost: float  # cost per stage per workflow episode
    latency_ms: float
    good_probability: float
    bad_latency_multiplier: float
    bad_availability: float


CLOUDS = (
    Cloud("On-prem", 3.2, 38, .82, 1.75, .91),
    Cloud("Cloud-A", 4.0, 25, .78, 1.85, .89),
    Cloud("Cloud-B", 5.4, 16, .90, 1.55, .95),
)
AGENTS = ("Planner", "Researcher", "Writer")
EDGES = ((0, 1, 2.0), (1, 2, 1.5))  # (from, to, transfer charge if cross-cloud)
INSPECTION_COST = 0.65
SLO_DEADLINE_MS = 115.0
MIN_RELIABILITY = .80
MAX_VIOLATION_PROB = .10
FAILURE_PENALTY = 20.0
CVaR_ALPHA = .90
RISK_WEIGHT = .50


def make_worlds():
    """Exact 2^9 prior over good/bad agent-resource performance states."""
    # State indexing is agent-major: pair (i, c) maps to i * n_clouds + c.
    probs = [CLOUDS[c].good_probability for _ in AGENTS
             for c in range(len(CLOUDS))]
    worlds = []
    for bits in itertools.product((0, 1), repeat=len(probs)):
        p = math.prod(q if bit else 1 - q for q, bit in zip(probs, bits))
        worlds.append((bits, p))
    return tuple(worlds)


WORLDS = make_worlds()
PLACEMENTS = tuple(itertools.product(range(len(CLOUDS)), repeat=len(AGENTS)))
PAIRS = tuple((i, c) for i in range(len(AGENTS)) for c in range(len(CLOUDS)))


def outcome(placement, bits):
    latency = 0.0
    reliability = 1.0
    cost = sum(CLOUDS[c].compute_cost for c in placement)
    for i, cidx in enumerate(placement):
        c = CLOUDS[cidx]
        good = bits[i * len(CLOUDS) + cidx]
        latency += c.latency_ms * (1.0 if good else c.bad_latency_multiplier)
        reliability *= 0.995 if good else c.bad_availability
    for i, j, transfer in EDGES:
        if placement[i] != placement[j]:
            latency += 7.0
            cost += transfer
    failed = latency > SLO_DEADLINE_MS or reliability < MIN_RELIABILITY
    return cost + (FAILURE_PENALTY if failed else 0), failed, latency, reliability


@lru_cache(maxsize=None)
def risk_stats(placement, worlds):
    values = [(outcome(placement, bits)[0], p) for bits, p in worlds]
    total_p = sum(p for _, p in values)
    if total_p <= 0:
        return math.inf, math.inf, 1.0
    values = [(v, p / total_p) for v, p in values]
    mean = sum(v * p for v, p in values)
    tail_mass = 1.0 - CVaR_ALPHA
    tail_left = tail_mass
    tail_sum = 0.0
    for value, p in sorted(values, reverse=True):
        take = min(p, tail_left)
        tail_sum += value * take
        tail_left -= take
        if tail_left <= 1e-12:
            break
    cvar = tail_sum / tail_mass
    violation = sum(p for bits, p in worlds if outcome(placement, bits)[1]) / total_p
    return mean, cvar, violation


def score(placement, worlds, risk_weight):
    mean, cvar, violation = risk_stats(placement, worlds)
    if violation > MAX_VIOLATION_PROB + 1e-12:
        return math.inf
    return mean + risk_weight * (cvar - mean)


def best_placement(worlds, risk_weight):
    scored = [(score(p, worlds, risk_weight), p) for p in PLACEMENTS]
    value, placement = min(scored)
    if math.isfinite(value):
        return value, placement
    # Explicit least-risk fallback if no mapping meets the chance constraint.
    return min((risk_stats(p, worlds)[2], risk_stats(p, worlds)[0], p)
               for p in PLACEMENTS)[1:]


@lru_cache(maxsize=None)
def posterior_worlds(observed):
    return tuple((bits, p) for bits, p in WORLDS
                 if all(bits[i * len(CLOUDS) + c] == v for (i, c), v in observed))


def adaptive_inspections(actual_bits, risk_weight):
    observed = {}
    spent = 0.0
    inspected = []
    while True:
        prior = posterior_worlds(tuple(sorted(observed.items())))
        current_value, _ = best_placement(prior, risk_weight)
        candidates = []
        for pair in PAIRS:
            if pair in observed:
                continue
            qidx = pair[0] * len(CLOUDS) + pair[1]
            expected_after = 0.0
            for state in (0, 1):
                branch = {**observed, pair: state}
                branch_worlds = posterior_worlds(tuple(sorted(branch.items())))
                branch_prob = sum(p for _, p in branch_worlds) / sum(p for _, p in prior)
                value, _ = best_placement(branch_worlds, risk_weight)
                expected_after += branch_prob * value
            net_value = current_value - expected_after - INSPECTION_COST
            candidates.append((net_value, pair))
        if not candidates:
            break
        net_value, pair = max(candidates)
        if net_value <= 1e-9:
            break
        observed[pair] = actual_bits[pair[0] * len(CLOUDS) + pair[1]]
        inspected.append(pair)
        spent += INSPECTION_COST
    _, placement = best_placement(posterior_worlds(tuple(sorted(observed.items()))), risk_weight)
    return placement, inspected, spent


@lru_cache(maxsize=None)
def exact_policy_value(observed, risk_weight, inspection_cost):
    """Dynamic program for the finite model's optimal adaptive inspection policy.

    It minimizes expected accumulated inspection charges plus the terminal
    posterior risk-adjusted placement score. This is an exact reference for
    the stated nested objective, not a global-CVaR-over-policy objective.
    """
    worlds = posterior_worlds(observed)
    stop_value, _ = best_placement(worlds, risk_weight)
    best_value, best_action = stop_value, None
    mass = sum(p for _, p in worlds)
    available = [q for q in range(len(PAIRS))
                 if q not in {i * len(CLOUDS) + c for (i, c), _ in observed}]
    for q in available:
        p_good = sum(p for bits, p in worlds if bits[q]) / mass
        state_good = tuple(sorted((*observed, (PAIRS[q], 1))))
        state_bad = tuple(sorted((*observed, (PAIRS[q], 0))))
        candidate_value = (inspection_cost
                           + p_good * exact_policy_value(state_good, risk_weight, inspection_cost)[0]
                           + (1 - p_good) * exact_policy_value(state_bad, risk_weight, inspection_cost)[0])
        if candidate_value < best_value - 1e-12:
            best_value, best_action = candidate_value, q
    return best_value, best_action


def exact_adaptive_inspections(actual_bits, risk_weight):
    observed, inspected, spent = (), [], 0.0
    while True:
        _, action = exact_policy_value(observed, risk_weight, INSPECTION_COST)
        if action is None:
            break
        pair = PAIRS[action]
        state = actual_bits[action]
        observed = tuple(sorted((*observed, (pair, state))))
        inspected.append(pair)
        spent += INSPECTION_COST
    _, placement = best_placement(posterior_worlds(observed), risk_weight)
    return placement, inspected, spent


def run_episode(rng, risk_weight, include_exact=False):
    actual_bits = tuple(int(rng.random() < CLOUDS[c].good_probability)
                        for _ in AGENTS for c in range(len(CLOUDS)))
    # Evaluate the policy's pre-inspection decision under the prior.
    _, no_inspect_placement = best_placement(WORLDS, risk_weight)
    adaptive_place, adaptive_list, adaptive_spend = adaptive_inspections(actual_bits, risk_weight)
    if include_exact:
        exact_place, exact_list, exact_spend = exact_adaptive_inspections(actual_bits, risk_weight)

    all_observed = {(i, c): actual_bits[i * len(CLOUDS) + c] for i, c in PAIRS}
    _, all_place = best_placement(posterior_worlds(tuple(sorted(all_observed.items()))), risk_weight)
    # Random inspection uses the adaptive policy's inspection count for a matched budget.
    random_pairs = list(PAIRS)
    rng.shuffle(random_pairs)
    random_observed = {pair: actual_bits[pair[0] * len(CLOUDS) + pair[1]]
                       for pair in random_pairs[:len(adaptive_list)]}
    _, random_place = best_placement(posterior_worlds(tuple(sorted(random_observed.items()))), risk_weight)
    if include_exact:
        random_exact_observed = {pair: actual_bits[pair[0] * len(CLOUDS) + pair[1]]
                                 for pair in random_pairs[:len(exact_list)]}
        _, random_exact_place = best_placement(
            posterior_worlds(tuple(sorted(random_exact_observed.items()))), risk_weight)

    methods = {
        "no_inspection": (no_inspect_placement, 0.0, 0),
        "random_matched": (random_place, len(random_observed) * INSPECTION_COST, len(random_observed)),
        "inspect_all": (all_place, len(PAIRS) * INSPECTION_COST, len(PAIRS)),
        "adaptive_voi": (adaptive_place, adaptive_spend, len(adaptive_list)),
    }
    if include_exact:
        methods["exact_adaptive"] = (exact_place, exact_spend, len(exact_list))
        methods["random_exact_matched"] = (
            random_exact_place, len(random_exact_observed) * INSPECTION_COST,
            len(random_exact_observed))
    rows = []
    for method, (placement, inspection, count) in methods.items():
        realized, failed, latency, reliability = outcome(placement, actual_bits)
        rows.append({
            "method": method,
            "deployment_cost": round(realized - (FAILURE_PENALTY if failed else 0), 4),
            "inspection_cost": round(inspection, 4),
            "total_cost": round(realized + inspection, 4),
            "slo_violation": int(failed),
            "latency_ms": round(latency, 3),
            "reliability": round(reliability, 4),
            "inspections": count,
            "placement": ";".join(f"{AGENTS[i]}={CLOUDS[c].name}" for i, c in enumerate(placement)),
        })
    return rows


def summarize(rows):
    methods = sorted({r["method"] for r in rows})
    result = []
    for method in methods:
        data = [r for r in rows if r["method"] == method]
        costs = sorted(r["total_cost"] for r in data)
        n = len(data)
        tail_n = max(1, math.ceil((1 - CVaR_ALPHA) * n))
        result.append({
            "method": method,
            "mean_total_cost": round(sum(costs) / n, 4),
            "cvar90_total_cost": round(sum(costs[-tail_n:]) / tail_n, 4),
            "slo_violation_rate": round(sum(r["slo_violation"] for r in data) / n, 4),
            "mean_inspections": round(sum(r["inspections"] for r in data) / n, 3),
            "mean_latency_ms": round(sum(r["latency_ms"] for r in data) / n, 3),
            "mean_deployment_cost": round(sum(r["deployment_cost"] for r in data) / n, 4),
            "mean_inspection_cost": round(sum(r["inspection_cost"] for r in data) / n, 4),
        })
    return result


def summarize_by_seed(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault((row["seed"], row["method"]), []).append(row)
    result = []
    for (seed, method), data in sorted(grouped.items()):
        n = len(data)
        result.append({
            "seed": seed,
            "method": method,
            "mean_total_cost": sum(r["total_cost"] for r in data) / n,
            "slo_violation_rate": sum(r["slo_violation"] for r in data) / n,
            "mean_inspections": sum(r["inspections"] for r in data) / n,
        })
    return result


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    global INSPECTION_COST
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=60)
    parser.add_argument("--seed", type=int, default=6111)
    parser.add_argument("--replicates", type=int, default=1, help="number of independent seeds")
    parser.add_argument("--risk-weight", type=float, default=RISK_WEIGHT)
    parser.add_argument("--inspection-cost", type=float, default=INSPECTION_COST)
    parser.add_argument("--include-exact-adaptive", action="store_true")
    parser.add_argument("--output-dir", default="results")
    args = parser.parse_args()
    INSPECTION_COST = args.inspection_cost
    rows = []
    for replicate in range(args.replicates):
        episode_seed = args.seed + replicate
        rng = random.Random(episode_seed)
        for episode in range(args.episodes):
            rows.extend({"seed": episode_seed, "episode": episode, **row}
                        for row in run_episode(rng, args.risk_weight, args.include_exact_adaptive))
    summary = summarize(rows)
    out = Path(args.output_dir)
    out.mkdir(exist_ok=True)
    write_csv(out / "episode_results.csv", rows)
    write_csv(out / "summary.csv", summary)
    write_csv(out / "seed_summary.csv", summarize_by_seed(rows))
    print(f"episodes={args.episodes} seeds={args.seed}..{args.seed + args.replicates - 1} "
          f"risk_weight={args.risk_weight} inspection_cost={args.inspection_cost}")
    for row in summary:
        print(row)
    print(f"Wrote episode, aggregate, and per-seed results to {out}")


if __name__ == "__main__":
    main()
