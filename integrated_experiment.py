"""Integrated trace-driven placement, link inspection, and topology experiment.

Workloads come from oat_reconstruct.py. Network/provider parameters are explicit
synthetic scenario assumptions because Open Agent Traces contains no cloud-link
or infrastructure price measurements.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import statistics
import zlib
from collections import defaultdict
from pathlib import Path

from oat_reconstruct import reconstruct_dataset

SITES = ("OnPrem", "CloudA", "CloudB")
SITE_HOURLY_USD = (0.20, 0.42, 0.78)  # small agent-runtime VM class; assumption
SITE_AVAIL = (0.997, 0.999, 0.9995)  # assumption
EGRESS_USD_PER_GB = (0.02, 0.09, 0.08)  # origin-specific assumption
FAILURE_PENALTY_USD = 0.05
LINKS = {
    (0, 1): {"bw_mbps": 200.0, "latency_ms": 25.0, "prob": (0.90, 0.08, 0.02)},
    (0, 2): {"bw_mbps": 120.0, "latency_ms": 48.0, "prob": (0.84, 0.12, 0.04)},
    (1, 2): {"bw_mbps": 300.0, "latency_ms": 18.0, "prob": (0.92, 0.07, 0.01)},
}
STATE_AVAIL = (0.999, 0.97, 0.0)  # good, degraded, failed
STATE_BW_FACTOR = (1.0, 0.25, 0.0)
STATE_LAT_FACTOR = (1.0, 2.5, math.inf)
TOPOLOGIES = {
    "full_mesh": ((0, 1), (0, 2), (1, 2)),
    "hub_and_spoke": ((0, 1), (0, 2)),  # OnPrem is the hub
    "selective_peering": ((0, 1), (1, 2)),  # CloudA brokers the selected peers
}


def load_workflows(data_dir: Path, limit: int | None = None) -> tuple[list[dict], dict]:
    workflows, audit = reconstruct_dataset(data_dir)
    if limit is not None:
        workflows = workflows[:limit]
    return workflows, audit


def load_cloudsim_profile(path: Path) -> tuple[float, ...]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing CloudSim Plus profile {path}; build cloudsim-fullmesh and run "
            "CloudSimComputeProfile to generate it."
        )
    with path.open(newline="", encoding="utf-8") as stream:
        by_site = {row["site"]: float(row["speed_factor"]) for row in csv.DictReader(stream)}
    if set(by_site) != set(SITES) or any(v <= 0 for v in by_site.values()):
        raise ValueError(f"CloudSim profile must contain positive speed factors for {SITES}")
    return tuple(by_site[site] for site in SITES)


def state_scenarios(topology: str, observations: tuple[tuple[int, int, int], ...]):
    edges = TOPOLOGIES[topology]
    observed = {(a, b): state for a, b, state in observations}
    unknown = [edge for edge in edges if edge not in observed]
    domains = [range(3) for _ in unknown]
    for vals in itertools.product(*domains):
        state_map = dict(observed)
        state_map.update(zip(unknown, vals))
        probability = 1.0
        for edge, state in zip(unknown, vals):
            probability *= LINKS[edge]["prob"][state]
        if probability > 0:
            yield tuple((edge, state_map[edge]) for edge in edges), probability


def shortest_route(src: int, dst: int, payload_bytes: float, state_map: dict, topology_edges: tuple):
    if src == dst:
        return 0.0, 0.0, ()
    graph = defaultdict(list)
    for edge in topology_edges:
        state = state_map[edge]
        if state == 2:
            continue
        a, b = edge
        profile = LINKS[edge]
        bw = profile["bw_mbps"] * STATE_BW_FACTOR[state]
        lat = profile["latency_ms"] * STATE_LAT_FACTOR[state]
        serialization_ms = payload_bytes * 8.0 / (bw * 1_000_000) * 1000.0
        delay = lat + serialization_ms
        graph[a].append((b, delay))
        graph[b].append((a, delay))
    # Dijkstra is tiny here (three sites) and tie-breaks deterministically.
    pending = [(0.0, src, ())]
    best = {src: 0.0}
    while pending:
        pending.sort(reverse=True)
        dist, node, path = pending.pop()
        if node == dst:
            egress = sum(EGRESS_USD_PER_GB[u] for u, _ in path)
            gb = payload_bytes / 1_000_000_000.0
            return dist, gb * egress, path
        if dist > best.get(node, math.inf):
            continue
        for nxt, delay in graph[node]:
            nd = dist + delay
            if nd < best.get(nxt, math.inf):
                best[nxt] = nd
                pending.append((nd, nxt, path + ((node, nxt),)))
    return math.inf, 0.0, ()


class PlacementSolver:
    def __init__(self, workflow: dict, topology: str, risk_weight: float,
                 alpha: float, max_violation: float, deadline_factor: float,
                 payload_scale: float, site_speed: tuple[float, ...]):
        self.workflow = workflow
        self.topology = topology
        self.edges = TOPOLOGIES[topology]
        self.risk_weight = risk_weight
        self.site_speed = site_speed
        self.alpha = alpha
        self.max_violation = max_violation
        self.deadline = max(1.0, workflow["observed_service_latency_ms"] * deadline_factor)
        self.nodes = workflow["nodes"]
        self.node_ids = [n["id"] for n in self.nodes]
        self.index = {nid: i for i, nid in enumerate(self.node_ids)}
        self.order = self._topological_order()
        self.incoming = [[] for _ in self.nodes]
        self.work_edges = []
        for edge in workflow["edges"]:
            si, ti = self.index[edge["source"]], self.index[edge["target"]]
            self.incoming[ti].append((si, float(edge["payload_bytes"]) * payload_scale))
            self.work_edges.append((si, ti, float(edge["payload_bytes"]) * payload_scale))
        self.api_cost = float(workflow["api_cost_usd"])
        self.eval_cache = {}
        self.best_cache = {}
        self.route_cache = {}

    def _topological_order(self):
        ins = {nid: 0 for nid in self.node_ids}
        children = defaultdict(list)
        for edge in self.workflow["edges"]:
            ins[edge["target"]] += 1
            children[edge["source"]].append(edge["target"])
        ready = [nid for nid in self.node_ids if ins[nid] == 0]
        order = []
        while ready:
            nid = ready.pop(0)
            order.append(self.index[nid])
            for child in children[nid]:
                ins[child] -= 1
                if ins[child] == 0:
                    ready.append(child)
        if len(order) != len(self.node_ids):
            raise ValueError(f"workflow {self.workflow['run_id']} dependency graph contains a cycle")
        return order

    def _route(self, src: int, dst: int, payload: float, state_tuple: tuple):
        key = (src, dst, round(payload, 3), state_tuple)
        if key not in self.route_cache:
            state_map = dict(state_tuple)
            self.route_cache[key] = shortest_route(src, dst, payload, state_map, self.edges)
        return self.route_cache[key]

    def _infrastructure_cost(self, mapping: tuple[int, ...]) -> float:
        return sum((n["service_ms"] / 1000 / self.site_speed[mapping[i]]) * SITE_HOURLY_USD[mapping[i]] / 3600
                   for i, n in enumerate(self.nodes))

    def _scenario(self, mapping: tuple[int, ...], state_tuple: tuple):
        key = (mapping, state_tuple)
        if key in self.eval_cache:
            return self.eval_cache[key]
        end_time = [0.0] * len(self.nodes)
        network_cost = 0.0
        selected_link_availability = 1.0
        for i in self.order:
            transfer_ready = 0.0
            for parent, payload in self.incoming[i]:
                if mapping[parent] == mapping[i]:
                    delay, charge, path = 0.0, 0.0, ()
                else:
                    delay, charge, path = self._route(mapping[parent], mapping[i], payload, state_tuple)
                if math.isinf(delay):
                    transfer_ready = math.inf
                    continue
                transfer_ready = max(transfer_ready, end_time[parent] + delay)
                network_cost += charge
                for hop in path:
                    edge = tuple(sorted(hop))
                    selected_link_availability *= STATE_AVAIL[dict(state_tuple)[edge]]
            start_time = max(transfer_ready, 0.0)
            end_time[i] = start_time + self.nodes[i]["service_ms"] / self.site_speed[mapping[i]]
        latency = max(end_time)
        compute_cost = self._infrastructure_cost(mapping)
        base_cost = self.api_cost + compute_cost + network_cost
        node_availability = math.prod(SITE_AVAIL[site] for site in mapping)
        if math.isinf(latency):
            failure_probability = 1.0
            latency = self.deadline * 10
        elif latency > self.deadline:
            failure_probability = 1.0
        else:
            failure_probability = 1.0 - node_availability * selected_link_availability
        result = {
            "latency_ms": latency, "base_cost": base_cost,
            "compute_cost": compute_cost, "network_cost": network_cost,
            "failure_probability": min(1.0, max(0.0, failure_probability)),
        }
        self.eval_cache[key] = result
        return result

    def _mapping_score(self, mapping: tuple[int, ...], observations: tuple):
        worlds = list(state_scenarios(self.topology, observations))
        outcomes, chance = [], 0.0
        mean, second_moment, expected_latency = 0.0, 0.0, 0.0
        for state_tuple, probability in worlds:
            m = self._scenario(mapping, state_tuple)
            p_fail = m["failure_probability"]
            chance += probability * p_fail
            expected_latency += probability * m["latency_ms"]
            mean += probability * (m["base_cost"] + FAILURE_PENALTY_USD * p_fail)
            second_moment += probability * (
                m["base_cost"] ** 2 * (1 - p_fail)
                + (m["base_cost"] + FAILURE_PENALTY_USD) ** 2 * p_fail
            )
            outcomes.append((m["base_cost"], probability * (1 - p_fail)))
            outcomes.append((m["base_cost"] + FAILURE_PENALTY_USD, probability * p_fail))
        outcomes = [(v, p) for v, p in outcomes if p > 0]
        tail_mass = 1.0 - self.alpha
        remaining = tail_mass
        tail_sum = 0.0
        for value, probability in sorted(outcomes, reverse=True):
            take = min(remaining, probability)
            tail_sum += take * value
            remaining -= take
            if remaining <= 1e-12:
                break
        cvar = tail_sum / tail_mass
        score = mean + self.risk_weight * (cvar - mean)
        std_cost = math.sqrt(max(0.0, second_moment - mean ** 2))
        return score, mean, cvar, chance, std_cost, expected_latency

    def best(self, observations: tuple, criterion: str = "risk_aware"):
        obs_key = tuple(sorted(observations))
        cache_key = (obs_key, criterion)
        if cache_key in self.best_cache:
            return self.best_cache[cache_key]
        scored = []
        for mapping in itertools.product(range(len(SITES)), repeat=len(self.nodes)):
            if criterion == "single_site" and len(set(mapping)) != 1:
                continue
            score, mean, cvar, chance, std_cost, expected_latency = self._mapping_score(mapping, obs_key)
            scored.append((mapping, score, mean, cvar, chance, std_cost, expected_latency))
        feasible = [x for x in scored if x[4] <= self.max_violation + 1e-12]
        if criterion == "latency_first":
            selected = (min(feasible, key=lambda x: (x[6], x[2])) if feasible
                        else min(scored, key=lambda x: (x[4], x[6], x[2])))
        elif criterion == "deterministic_slo":
            # Point-profile comparator: use mean latency plus expected availability,
            # rather than requiring the full posterior chance constraint.
            point_feasible = [x for x in scored
                              if x[6] <= self.deadline and x[4] <= self.max_violation + 1e-12]
            selected = (min(point_feasible, key=lambda x: (x[2], x[6])) if point_feasible
                        else min(scored, key=lambda x: (max(0.0, x[6] - self.deadline), x[4], x[2])))
        elif criterion == "cheapest_feasible":
            selected = (min(feasible, key=lambda x: (x[2], x[1])) if feasible
                        else min(scored, key=lambda x: (x[4], x[2])))
        elif criterion == "mean_variance":
            selected = (min(feasible, key=lambda x: (x[2] + self.risk_weight * x[5], x[2])) if feasible
                        else min(scored, key=lambda x: (x[4], x[2] + self.risk_weight * x[5])))
        elif feasible:
            selected = min(feasible, key=lambda x: (x[1], x[2]))
        else:
            selected = min(scored, key=lambda x: (x[4], x[1], x[2]))
        self.best_cache[cache_key] = selected
        return selected

    def greedy_taskwise(self, observations: tuple) -> tuple[int, ...]:
        """Assign tasks in DAG order, committing to the cheapest feasible site."""
        assignment = [2] * len(self.nodes)  # CloudB is the provisional completion site.
        for task in self.order:
            candidates = []
            for site in range(len(SITES)):
                trial = assignment.copy()
                trial[task] = site
                score, mean, cvar, chance, std_cost, expected_latency = self._mapping_score(
                    tuple(trial), tuple(sorted(observations))
                )
                candidates.append((tuple(trial), score, mean, cvar, chance, std_cost, expected_latency))
            feasible = [candidate for candidate in candidates
                        if candidate[4] <= self.max_violation + 1e-12]
            if feasible:
                selected = min(feasible, key=lambda candidate: (candidate[2], candidate[6]))
            else:
                selected = min(candidates, key=lambda candidate: (candidate[4], candidate[2], candidate[6]))
            assignment[task] = selected[0][task]
        return tuple(assignment)

    def inspect_greedily(self, true_states: dict, inspection_cost: float):
        observations = {}
        inspections = []
        while True:
            current = self.best(tuple((a, b, s) for (a, b), s in observations.items()))[1]
            candidates = []
            for edge in self.edges:
                if edge in observations:
                    continue
                expected_after = 0.0
                for state, p in enumerate(LINKS[edge]["prob"]):
                    if p <= 0:
                        continue
                    obs = tuple(sorted((*((a, b, v) for (a, b), v in observations.items()), (*edge, state))))
                    expected_after += p * self.best(obs)[1]
                candidates.append((current - expected_after - inspection_cost, edge))
            if not candidates:
                break
            net_value, edge = max(candidates)
            if net_value <= 1e-12:
                break
            observations[edge] = true_states[edge]
            inspections.append(edge)
        obs = tuple((a, b, state) for (a, b), state in observations.items())
        return self.best(obs)[0], inspections, obs

    def score_actual(self, mapping: tuple[int, ...], true_states: dict):
        state_tuple = tuple((edge, true_states[edge]) for edge in self.edges)
        return self._scenario(mapping, state_tuple)


def evaluate_workflow(workflow: dict, seed: int, risk_weight: float, inspection_cost: float,
                      alpha: float, max_violation: float, deadline_factor: float,
                      payload_scale: float, site_speed: tuple[float, ...]):
    all_results = []
    rng = random.Random(seed ^ zlib.crc32(workflow["run_id"].encode("utf-8")))
    true_states = {}
    for edge, profile in LINKS.items():
        u = rng.random()
        true_states[edge] = 0 if u < profile["prob"][0] else (1 if u < profile["prob"][0] + profile["prob"][1] else 2)
    failure_uniform = rng.random()
    for topology in TOPOLOGIES:
        solver = PlacementSolver(workflow, topology, risk_weight, alpha, max_violation,
                                 deadline_factor, payload_scale, site_speed)
        initial_obs = ()
        no_inspection = solver.best(initial_obs)
        cheapest_feasible = solver.best(initial_obs, "cheapest_feasible")
        greedy_taskwise = solver.greedy_taskwise(initial_obs)
        mean_variance = solver.best(initial_obs, "mean_variance")
        latency_first = solver.best(initial_obs, "latency_first")
        deterministic_slo = solver.best(initial_obs, "deterministic_slo")
        single_site = solver.best(initial_obs, "single_site")
        adaptive, inspected, adaptive_obs = solver.inspect_greedily(true_states, inspection_cost)
        random_edges = list(TOPOLOGIES[topology])
        rng.shuffle(random_edges)
        random_edges = random_edges[:len(inspected)]
        random_obs = tuple((a, b, true_states[(a, b)]) for a, b in random_edges)
        random_choice = solver.best(random_obs)
        all_obs = tuple((a, b, true_states[(a, b)]) for a, b in TOPOLOGIES[topology])
        inspect_all = solver.best(all_obs)
        perfect_information = solver.best(all_obs)
        policy_choices = {
            "no_inspection": (no_inspection[0], (), 0, initial_obs),
            "cheapest_feasible": (cheapest_feasible[0], (), 0, initial_obs),
            "greedy_taskwise": (greedy_taskwise, (), 0, initial_obs),
            "mean_variance_cost": (mean_variance[0], (), 0, initial_obs),
            "latency_first": (latency_first[0], (), 0, initial_obs),
            "deterministic_slo": (deterministic_slo[0], (), 0, initial_obs),
            "single_site": (single_site[0], (), 0, initial_obs),
            "random_matched": (random_choice[0], random_edges, len(random_edges), random_obs),
            "adaptive_voi": (adaptive, inspected, len(inspected), adaptive_obs),
            "inspect_all": (inspect_all[0], list(TOPOLOGIES[topology]), len(TOPOLOGIES[topology]), all_obs),
            # Counterfactual: reveals every current link state for free.
            "perfect_information_bound": (perfect_information[0], (), 0, all_obs),
        }
        for policy, (mapping, measured_edges, count, observations) in policy_choices.items():
            actual = solver.score_actual(mapping, true_states)
            failed = actual["latency_ms"] > solver.deadline or failure_uniform < actual["failure_probability"]
            inspection_spend = count * inspection_cost
            realized_cost = actual["base_cost"] + inspection_spend + (FAILURE_PENALTY_USD if failed else 0.0)
            expected_score, expected_mean, expected_cvar, expected_violation, _, _ = solver._mapping_score(mapping, observations)
            all_results.append({
                "run_id": workflow["run_id"], "domain": workflow["domain"], "pattern": workflow["pattern"],
                "topology": topology, "policy": policy,
                "mapping": ";".join(f"{n['step_id']}={SITES[mapping[i]]}" for i, n in enumerate(workflow["nodes"])),
                "api_cost_usd": workflow["api_cost_usd"], "compute_cost_usd": actual["compute_cost"],
                "network_cost_usd": actual["network_cost"], "inspection_cost_usd": inspection_spend,
                "failure_cost_usd": FAILURE_PENALTY_USD if failed else 0.0,
                "total_cost_usd": realized_cost, "latency_ms": actual["latency_ms"],
                "deadline_ms": solver.deadline, "slo_violation": int(failed),
                "predicted_violation_probability": expected_violation,
                "predicted_mean_cost_usd": expected_mean, "predicted_cvar90_usd": expected_cvar,
                "risk_adjusted_objective_usd": expected_score,
                "inspection_count": count,
                "inspected_links": "|".join(f"{SITES[a]}-{SITES[b]}" for a, b in measured_edges),
                "node_count": len(workflow["nodes"]), "workflow_edge_count": len(workflow["edges"]),
                "critical_path_input_ms": workflow["observed_service_latency_ms"],
            })
    return all_results


def aggregate(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[(row["pattern"], row["topology"], row["policy"])].append(row)
    results = []
    for (pattern, topology, policy), group in sorted(groups.items()):
        costs = [r["total_cost_usd"] for r in group]
        latencies = [r["latency_ms"] for r in group]
        failures = [r["slo_violation"] for r in group]
        rate = statistics.mean(failures)
        z = 1.96
        denom = 1 + z * z / len(failures)
        center = (rate + z * z / (2 * len(failures))) / denom
        margin = z * math.sqrt(rate * (1 - rate) / len(failures) + z * z / (4 * len(failures) ** 2)) / denom
        ordered = sorted(costs, reverse=True)
        tail_n = max(1, math.ceil(.10 * len(ordered)))
        cost_sd = statistics.stdev(costs) if len(costs) > 1 else 0.0
        latency_sd = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
        results.append({
            "pattern": pattern, "topology": topology, "policy": policy, "workflows": len(group),
            "mean_total_cost_usd": statistics.mean(costs),
            "mean_cost_ci95_low": statistics.mean(costs) - 1.96 * cost_sd / math.sqrt(len(costs)),
            "mean_cost_ci95_high": statistics.mean(costs) + 1.96 * cost_sd / math.sqrt(len(costs)),
            "median_total_cost_usd": statistics.median(costs),
            "empirical_cvar90_usd": statistics.mean(ordered[:tail_n]),
            "mean_latency_ms": statistics.mean(latencies),
            "mean_latency_ci95_low": statistics.mean(latencies) - 1.96 * latency_sd / math.sqrt(len(latencies)),
            "mean_latency_ci95_high": statistics.mean(latencies) + 1.96 * latency_sd / math.sqrt(len(latencies)),
            "p95_latency_ms": sorted(latencies)[min(len(latencies)-1, math.ceil(.95*len(latencies))-1)],
            "slo_violation_rate": rate,
            "slo_rate_wilson95_low": max(0.0, center - margin),
            "slo_rate_wilson95_high": min(1.0, center + margin),
            "mean_inspections": statistics.mean(r["inspection_count"] for r in group),
            "mean_compute_cost_usd": statistics.mean(r["compute_cost_usd"] for r in group),
            "mean_network_cost_usd": statistics.mean(r["network_cost_usd"] for r in group),
            "mean_api_cost_usd": statistics.mean(r["api_cost_usd"] for r in group),
        })
    return results


def paired_topology_comparisons(rows: list[dict], bootstrap_samples: int = 1000) -> list[dict]:
    by_key = {(r["pattern"], r["policy"], r["domain"], r["run_id"], r["topology"]): r for r in rows}
    result = []
    for pattern in ("sequential", "supervisor", "parallel"):
        policies = (
            "no_inspection", "cheapest_feasible", "greedy_taskwise", "mean_variance_cost", "latency_first", "deterministic_slo",
            "single_site", "random_matched", "adaptive_voi", "inspect_all",
            "perfect_information_bound",
        )
        for policy in policies:
            runs = [(r["domain"], r["run_id"]) for r in rows if r["pattern"] == pattern and r["policy"] == policy
                    and r["topology"] == "full_mesh"]
            for comparison in ("hub_and_spoke", "selective_peering"):
                deltas = [float(by_key[(pattern, policy, domain, run, comparison)]["total_cost_usd"])
                          - float(by_key[(pattern, policy, domain, run, "full_mesh")]["total_cost_usd"])
                          for domain, run in runs]
                latency_deltas = [float(by_key[(pattern, policy, domain, run, comparison)]["latency_ms"])
                                  - float(by_key[(pattern, policy, domain, run, "full_mesh")]["latency_ms"])
                                  for domain, run in runs]
                rng = random.Random(941 + len(runs) + sum(map(ord, pattern + policy + comparison)))
                boot = [statistics.mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
                        for _ in range(bootstrap_samples)]
                boot.sort()
                result.append({
                    "pattern": pattern, "policy": policy,
                    "comparison_minus_full_mesh": comparison, "workflows": len(deltas),
                    "mean_cost_delta_usd": statistics.mean(deltas),
                    "paired_bootstrap_ci95_low": boot[int(.025 * bootstrap_samples)],
                    "paired_bootstrap_ci95_high": boot[min(bootstrap_samples - 1, int(.975 * bootstrap_samples))],
                    "mean_latency_delta_ms": statistics.mean(latency_deltas),
                    "cost_wins_vs_full_mesh": sum(d < 0 for d in deltas),
                    "ties_vs_full_mesh": sum(d == 0 for d in deltas),
                })
    return result


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/open-agent-traces"))
    parser.add_argument("--cloudsim-profile", type=Path,
                        default=Path("cloudsim-fullmesh/compute_profile.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/integrated_oat_baselines"))
    parser.add_argument("--seed", type=int, default=6111)
    parser.add_argument("--limit", type=int, default=None, help="Limit workflow count for a quick pilot run.")
    parser.add_argument("--risk-weight", type=float, default=.5)
    parser.add_argument("--inspection-cost", type=float, default=.0005)
    parser.add_argument("--alpha", type=float, default=.90)
    parser.add_argument("--max-violation", type=float, default=.10)
    parser.add_argument("--deadline-factor", type=float, default=1.15)
    parser.add_argument("--payload-scale", type=float, default=1.0,
                        help="Scale the observed/imputed handoff byte proxy for sensitivity runs.")
    args = parser.parse_args()

    workflows, audit = load_workflows(args.data_dir, args.limit)
    site_speed = load_cloudsim_profile(args.cloudsim_profile)
    rows = []
    for i, workflow in enumerate(workflows):
        rows.extend(evaluate_workflow(workflow, args.seed + i, args.risk_weight,
                                      args.inspection_cost, args.alpha, args.max_violation,
                                      args.deadline_factor, args.payload_scale, site_speed))
        if (i + 1) % 25 == 0:
            print(f"simulated {i + 1}/{len(workflows)} trace workflows")
    summaries = aggregate(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "episodes.csv", rows)
    write_csv(args.output_dir / "summary.csv", summaries)
    write_csv(args.output_dir / "topology_comparisons.csv", paired_topology_comparisons(rows))
    (args.output_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "dataset": audit["source"], "seed": args.seed, "workflows": len(workflows),
        "cloudsim_profile": str(args.cloudsim_profile),
        "assumptions": {"cloudsim_relative_speed_factor": site_speed, "site_hourly_usd": SITE_HOURLY_USD,
                        "site_availability": SITE_AVAIL, "egress_usd_per_gb": EGRESS_USD_PER_GB,
                        "link_profiles": {f"{SITES[a]}-{SITES[b]}": profile for (a,b), profile in LINKS.items()},
                        "state_availability": STATE_AVAIL,
                        "failure_penalty_usd": FAILURE_PENALTY_USD,
                        "risk_weight": args.risk_weight, "cvar_alpha": args.alpha,
                        "chance_limit": args.max_violation, "deadline_factor": args.deadline_factor,
                        "inspection_cost_usd_per_link": args.inspection_cost,
                        "payload_scale": args.payload_scale,
                        "topologies": {k: [[SITES[a], SITES[b]] for a,b in v] for k,v in TOPOLOGIES.items()}},
        "limitations": ["Open Agent Traces is generated/synthetic, not a production workload trace.",
                        "Cloud prices, link profiles, link-state priors, site speeds, and failure penalty are assumptions.",
                        "Link inspection reveals the current categorical link state perfectly.",
                        "Risk criterion is nested posterior CVaR with a chance constraint; it is not global CVaR over the adaptive policy."],
        "placement_baselines": {
            "no_inspection": "Risk-adjusted prior placement with the posterior chance constraint.",
            "cheapest_feasible": "Minimum expected monetary cost under the same chance constraint.",
            "greedy_taskwise": "Topological-order, task-by-task lowest-expected-cost assignment with a provisional CloudB completion and posterior feasibility checks.",
            "mean_variance_cost": "Mean cost plus risk_weight times standard deviation; a risk-model comparator, not an S-CEDA reproduction.",
            "latency_first": "Minimum expected latency among chance-feasible placements.",
            "deterministic_slo": "Point-profile comparator using expected latency and expected violation probability; not a COLAP, Murakkab, or SageServe reproduction.",
            "single_site": "Best risk-adjusted placement constrained to one site for all tasks.",
            "perfect_information_bound": "All current link states revealed at zero cost; non-deployable counterfactual, not a realized-cost guarantee.",
            "adaptive_voi": "Greedy, placement-coupled paid link inspection.",
            "random_matched": "Random links inspected with the adaptive policy's measurement count.",
            "inspect_all": "All configured links inspected at the stated per-link cost."
        },
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} workload/topology/policy rows to {args.output_dir}")


if __name__ == "__main__":
    main()
