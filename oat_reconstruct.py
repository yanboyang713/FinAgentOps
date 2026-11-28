"""Download and reconstruct workload DAGs from Open Agent Traces OCEL 2.0 logs.

The source is a generated, MIT-licensed dataset. This tool retains only trace
metadata needed for simulation; it never exports prompts, completions, or
reasoning text.
"""
from __future__ import annotations

import argparse
import json
import statistics
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = "juliensimon/open-agent-traces"
REVISION = "dff8ed6331f5abf9ec8ad825088eeb4caa6715a4"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}"
DOMAINS = {
    "customer-support-triage": "sequential",
    "legal-document-analysis": "sequential",
    "financial-analysis": "sequential",
    "ecommerce-product-enrichment": "sequential",
    "code-review-pipeline": "supervisor",
    "data-pipeline-debugging": "supervisor",
    "incident-response": "supervisor",
    "market-research": "parallel",
    "content-generation": "parallel",
    "academic-paper-review": "parallel",
}


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "workflow-placement-project/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response, path.open("wb") as output:
        output.write(response.read())


def ensure_dataset(data_dir: Path) -> None:
    for domain in DOMAINS:
        for relative in (f"ocel/{domain}/output.jsonocel", f"ocel/{domain}/normative_model.json"):
            path = data_dir / relative
            if not path.exists():
                print(f"Downloading {relative}")
                _download(f"{BASE}/{relative}", path)
    metadata = data_dir / "source.json"
    if not metadata.exists():
        metadata.write_text(json.dumps({
            "repo": REPO, "revision": REVISION, "license": "MIT",
            "description": "Generated OCEL 2.0 agent workflow traces; not production observations.",
        }, indent=2) + "\n", encoding="utf-8")


def _attrs(items: list[dict]) -> dict[str, str]:
    return {str(item.get("name")): str(item.get("value", "")) for item in items}


def _rels(event: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for rel in event.get("relationships", []):
        result[str(rel.get("qualifier", ""))].append(str(rel.get("objectId", "")))
    return result


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _number(attrs: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(attrs.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def reconstruct_run(run_id: str, domain: str, pattern: str, conformant: bool,
                    events: list[dict], objects: dict[str, dict], template: dict) -> tuple[dict | None, dict]:
    agent_roles = {}
    for oid, obj in objects.items():
        if obj.get("type") == "agent":
            agent_roles[oid] = _attrs(obj.get("attributes", [])).get("role", oid)

    started: dict[str, dict] = {}
    completed: dict[str, datetime] = {}
    message_events = []
    for event in events:
        a = _attrs(event.get("attributes", []))
        rel = _rels(event)
        if event.get("type") == "agent_invoked":
            inv_id = next(iter(rel.get("started", [])), None)
            agent_id = next(iter(rel.get("invoked", [])), None)
            if inv_id and agent_id:
                started[inv_id] = {
                    "step_id": a.get("step_id", inv_id),
                    "agent_id": agent_id,
                    "role": agent_roles.get(agent_id, agent_id),
                    "start": _time(event["time"]),
                }
        elif event.get("type") == "agent_completed":
            inv_id = next(iter(rel.get("completed", [])), None)
            if inv_id:
                completed[inv_id] = _time(event["time"])
        elif event.get("type") == "message_sent":
            msg_id = next(iter(rel.get("sent", [])), None)
            message_events.append((event, rel, objects.get(msg_id, {})))

    node_ids = set(started)
    if not node_ids or not node_ids.issubset(completed):
        return None, {"reason": "missing_invocation_boundary"}
    by_step = defaultdict(list)
    nodes = []
    for inv_id, data in started.items():
        by_step[data["step_id"]].append(inv_id)
        span_ms = max(0.0, (completed[inv_id] - data["start"]).total_seconds() * 1000)
        oa = _attrs(objects.get(inv_id, {}).get("attributes", []))
        nodes.append({
            "id": inv_id, "step_id": data["step_id"], "role": data["role"],
            "model": _attrs(objects.get(data["agent_id"], {}).get("attributes", [])).get("model_name", "unknown"),
            "start_ms": data["start"].timestamp() * 1000,
            "finish_ms": completed[inv_id].timestamp() * 1000,
            "service_ms": span_ms,
            "input_tokens": int(_number(oa, "input_tokens")),
            "output_tokens": int(_number(oa, "output_tokens")),
            "api_cost_usd": _number(oa, "cost_usd"),
        })

    template_steps = {step["id"]: step for step in template.get("steps", [])}
    template_edges = template.get("edges", [])
    # The shipped template validates step identities and identifies parallel
    # workers; actual dependencies below come from message and timing events.
    if len(by_step) != len(template_steps) or any(len(by_step.get(sid, [])) != 1 for sid in template_steps):
        return None, {"reason": "template_step_mismatch"}
    inv_to_node = {n["id"]: n for n in nodes}
    payload_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    observed_pairs = set()
    for event, rel, msg_obj in message_events:
        sender = next(iter(rel.get("sender", [])), None)
        receiver = next(iter(rel.get("receiver", [])), None)
        if not sender or not receiver:
            continue
        t = _time(event["time"]).timestamp() * 1000
        source_candidates = [n for n in nodes if started[n["id"]]["agent_id"] == sender and n["finish_ms"] <= t + 1e-6]
        target_candidates = [n for n in nodes if started[n["id"]]["agent_id"] == receiver
                             and n["start_ms"] <= t <= n["finish_ms"]]
        if not source_candidates:
            source_candidates = [n for n in nodes if started[n["id"]]["agent_id"] == sender]
        if not target_candidates:
            target_candidates = [n for n in nodes if started[n["id"]]["agent_id"] == receiver
                                 and n["start_ms"] >= t]
        if not source_candidates or not target_candidates:
            continue
        source = max(source_candidates, key=lambda n: n["finish_ms"])
        target = min(target_candidates, key=lambda n: abs(n["start_ms"] - t))
        pair = (source["step_id"], target["step_id"])
        observed_pairs.add(pair)
        message_attrs = _attrs(msg_obj.get("attributes", []))
        length = _number(message_attrs, "content_length")
        if length > 0:
            payload_samples[pair].append(length)

    edges_by_pair = {}

    def add_edge(src_id: str, dst_id: str, reason: str) -> None:
        if src_id == dst_id or (src_id, dst_id) in edges_by_pair:
            return
        src_node, dst_node = inv_to_node[src_id], inv_to_node[dst_id]
        samples = payload_samples.get((src_node["step_id"], dst_node["step_id"]), [])
        payload_bytes = statistics.median(samples) if samples else max(1, 4 * src_node["output_tokens"])
        edges_by_pair[(src_id, dst_id)] = {
            "source": src_id, "target": dst_id,
            "source_step": src_node["step_id"], "target_step": dst_node["step_id"],
            "payload_bytes": float(payload_bytes),
            "payload_source": "message_content_length" if samples else "4_bytes_per_source_output_token_proxy",
            "has_observed_handoff": bool(samples), "dependency_source": reason,
        }

    # The execution event's sender/receiver handoff relations define observed edges.
    for src_step, dst_step in observed_pairs:
        if len(by_step.get(src_step, [])) == 1 and len(by_step.get(dst_step, [])) == 1:
            add_edge(by_step[src_step][0], by_step[dst_step][0], "observed_message_handoff")

    # For parallel traces, a join invocation that starts after every worker
    # finishes is an observed synchronization barrier. Missing branch handoffs
    # are represented as inferred precedence edges, with payload imputed below.
    if pattern == "parallel":
        groups: dict[str, list[str]] = defaultdict(list)
        for step in template.get("steps", []):
            if step.get("parallel_group"):
                groups[step["parallel_group"]].append(step["id"])
        join_steps = [edge["target"] for edge in template_edges
                      if edge["source"] in {sid for ids in groups.values() for sid in ids}]
        join_step = next((sid for sid in join_steps if sid in by_step and sid not in {s for ids in groups.values() for s in ids}), None)
        if join_step and by_step.get(join_step):
            join_node = inv_to_node[by_step[join_step][0]]
            branch_steps = next(iter(groups.values()), [])
            branch_nodes = [inv_to_node[by_step[s][0]] for s in branch_steps if by_step.get(s)]
            if branch_nodes and join_node["start_ms"] >= max(n["finish_ms"] for n in branch_nodes) - 2.0:
                for branch in branch_nodes:
                    add_edge(branch["id"], join_node["id"], "observed_parallel_join_barrier")

    # Supervisor workflows in this release often execute delegated roles
    # serially despite the template's fan-out/fan-in graph. Preserve the
    # observed serialized execution order if no handoff edge connects adjacent
    # invocations and the measured spans do not overlap.
    if pattern == "supervisor":
        serial = sorted(nodes, key=lambda n: (n["start_ms"], n["id"]))
        for left, right in zip(serial, serial[1:]):
            if right["start_ms"] >= left["finish_ms"] - 2.0:
                add_edge(left["id"], right["id"], "observed_serial_execution_order")

    edges = list(edges_by_pair.values())
    expected_pairs = {(e["source"], e["target"]) for e in template_edges}

    graph = {
        "run_id": run_id, "domain": domain, "pattern": pattern,
        "conformant": conformant,
        "nodes": sorted(nodes, key=lambda n: (n["start_ms"], n["id"])),
        "edges": edges,
        "trace_message_edge_count": len(observed_pairs),
        "template_edge_count": len(template_edges),
        "observed_message_edge_coverage": sum(e["dependency_source"] == "observed_message_handoff" for e in edges),
        "observed_template_edge_count": len(observed_pairs & expected_pairs),
        "reconstructed_edge_sources": dict(Counter(e["dependency_source"] for e in edges)),
        "observed_message_pairs": [list(p) for p in sorted(observed_pairs)],
        "api_cost_usd": sum(n["api_cost_usd"] for n in nodes),
        "observed_service_latency_ms": max(n["finish_ms"] for n in nodes) - min(n["start_ms"] for n in nodes),
    }
    return graph, {"reason": "included"}


def reconstruct_dataset(data_dir: Path, include_deviants: bool = False) -> tuple[list[dict], dict]:
    ensure_dataset(data_dir)
    all_workflows = []
    audit = {"source": {"repo": REPO, "revision": REVISION, "license": "MIT",
                         "dataset_is_synthetic": True}, "domains": {}, "exclusions": Counter()}
    for domain, expected_pattern in DOMAINS.items():
        source = data_dir / f"ocel/{domain}/output.jsonocel"
        template_path = data_dir / f"ocel/{domain}/normative_model.json"
        log = json.loads(source.read_text(encoding="utf-8"))
        template = json.loads(template_path.read_text(encoding="utf-8"))
        objects = {obj["id"]: obj for obj in log.get("objects", [])}
        by_run = defaultdict(list)
        for event in log.get("events", []):
            a = _attrs(event.get("attributes", []))
            if a.get("run_id"):
                by_run[a["run_id"]].append(event)
        run_objects = [obj for obj in log.get("objects", []) if obj.get("type") == "run"]
        domain_stats = {"pattern": expected_pattern, "runs": len(run_objects), "events": len(log.get("events", [])),
                        "conformant_runs": 0, "included_runs": 0, "observed_handoffs": 0,
                        "template_edges": 0, "covered_template_edges": 0, "node_counts": Counter(),
                        "excluded": Counter()}
        for obj in run_objects:
            run_attrs = _attrs(obj.get("attributes", []))
            run_id = obj["id"]
            pattern = run_attrs.get("pattern_type", expected_pattern)
            conformant = run_attrs.get("is_conformant", "false").lower() == "true"
            if conformant:
                domain_stats["conformant_runs"] += 1
            if pattern != expected_pattern:
                reason = "pattern_mismatch"
            elif not conformant and not include_deviants:
                reason = "deviant_trace_excluded"
            else:
                graph, status = reconstruct_run(run_id, domain, pattern, conformant,
                                                by_run.get(run_id, []), objects, template)
                reason = status["reason"]
                if graph:
                    all_workflows.append(graph)
                    domain_stats["included_runs"] += 1
                    domain_stats["observed_handoffs"] += graph["trace_message_edge_count"]
                    domain_stats["template_edges"] += graph["template_edge_count"]
                    domain_stats["covered_template_edges"] += graph["observed_template_edge_count"]
                    domain_stats["node_counts"][str(len(graph["nodes"]))] += 1
            if reason != "included":
                domain_stats["excluded"].update([reason])
                audit["exclusions"].update([reason])
        domain_stats["node_counts"] = dict(domain_stats["node_counts"])
        domain_stats["excluded"] = dict(domain_stats["excluded"])
        audit["domains"][domain] = domain_stats
    audit["exclusions"] = dict(audit["exclusions"])
    audit["included_runs"] = len(all_workflows)
    audit["included_by_pattern"] = dict(Counter(w["pattern"] for w in all_workflows))
    audit["message_edge_coverage"] = (
        sum(d["covered_template_edges"] for d in audit["domains"].values()) /
        max(1, sum(d["template_edges"] for d in audit["domains"].values()))
    )
    return all_workflows, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/open-agent-traces"))
    parser.add_argument("--output", type=Path, default=Path("results/open_agent_traces/workflows.jsonl"))
    parser.add_argument("--audit", type=Path, default=Path("results/open_agent_traces/audit.json"))
    parser.add_argument("--include-deviants", action="store_true", help="Include structurally valid runs labeled non-conformant.")
    args = parser.parse_args()
    workflows, audit = reconstruct_dataset(args.data_dir, args.include_deviants)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(w, separators=(",", ":")) + "\n" for w in workflows), encoding="utf-8")
    args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"included_runs": audit["included_runs"], "patterns": audit["included_by_pattern"],
                      "message_edge_coverage": round(audit["message_edge_coverage"], 3),
                      "audit": str(args.audit), "workflows": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
