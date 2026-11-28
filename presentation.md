---
marp: true
title: Cost-Aware Placement of Agent Workflows in Dynamic Hybrid Clouds
author: Boyang Yan and Yusen Wu
paginate: true
size: 16:9
---

# Cost-Aware Placement of Agent Workflows
## Dynamic hybrid-cloud networks and paid link inspection

**Boyang Yan · Yusen Wu**  
CS 6111 — Cloud Computing  
20-minute project presentation

<!-- Speaker notes (0:45): Hello. This project asks how to place agent workflows across a hybrid cloud when network conditions can change, and whether it is worth paying to inspect links before choosing a placement. I’ll explain the workload reconstruction, cost and risk model, the three network scenarios, and what our current simulation results do and do not support. The central point is that placement, network risk, and information cost belong in one decision model. -->

---

## The decision is coupled

```text
Agent workflow DAG                 Hybrid-cloud network
 task A ──► task B                  OnPrem ── CloudA
   └────► task C                       \       /
          \                            CloudB
           └──► aggregate
```

- Assign each task to OnPrem, CloudA, or CloudB
- Handoffs consume time and may incur egress cost
- Link states are uncertain; inspection costs money
- SLO failures carry economic loss

**Question:** When does information change the best risk-aware mapping enough to pay for itself?

<!-- Speaker notes (1:20): An agent workflow is a directed graph, not necessarily a chain. A supervisor can delegate, multiple workers can run concurrently, and an aggregator can wait for all branches. Each task maps to a site. If connected tasks run at different sites, messages traverse the network; a degraded or failed link can change completion time, route, and reliability. So we jointly consider the mapping, the route under a topology, and whether to measure uncertain links before placement. -->

---

## Scope follows the project feedback

- **Cost and risk** both enter the objective and SLO constraint
- **Topology is a controlled comparison:** full mesh, hub-and-spoke, selective peering
- Explain why the risk model uses both a chance constraint and CVaR
- Make the experiment’s model and assumptions explicit

**Focus:** trace-driven DAG placement + dynamic link states + paid inspections

<!-- Speaker notes (1:10): The instructor’s guidance was to keep both cost and risk in scope, focus less on topology, explain the risk-model trade-offs, and state the experiment model clearly. I interpret that as making placement and information acquisition the central question, while comparing the three requested topologies as experimental conditions. They are not the main novelty claim. -->

---

## Workload: Open Agent Traces

**Pinned release:** 17,019 events · 500 generated runs · 10 domains

```text
Sequential:   A ──► B ──► C
Supervisor:   S ──► W1, W2, W3 ──► S'
Parallel:     A1, A2, A3 ──► aggregate
```

- Reconstruct task duration, tokens, API cost, message handoffs, dependencies
- 403 conformant workflows retained: 170 sequential, 113 supervisor, 120 parallel
- 97 runs marked as deviant excluded

<!-- Speaker notes (1:10): Open Agent Traces is pinned to a specific revision and is generated, not production telemetry. We use execution structure, timestamps, tokens, API cost, and handoffs, but not prompts or completions. After excluding 97 deviant traces, 403 workflows remain. -->

---

## Reconstruction is audited, not assumed

| Pattern | Direct observed template arcs | Reconstruction note |
|---|---:|---|
| Sequential | 100% | Message order recovers the chain |
| Supervisor | 66.7% | Event handoffs can serialize template fan-out |
| Parallel | 66.7% | Missing join arcs inferred only at observed barrier |

**Overall direct arc coverage: 73.2%**  
Inferred edges and token-based payload proxies are labeled separately.

<!-- Speaker notes (1:15): We compare observed message dependencies with normative templates. Sequential dependencies are complete. Supervisor and parallel traces expose two-thirds of template arcs directly. A missing parallel join is inferred only when the aggregate begins after workers finish, and its payload is estimated. Supervisor logs can serialize a template fan-out. The audit makes these limits visible rather than silently filling the DAG from the template. -->

---

## Three infrastructure graphs

| Scenario | Direct links |
|---|---|
| Full mesh | OnPrem–CloudA · OnPrem–CloudB · CloudA–CloudB |
| Hub-and-spoke | OnPrem–CloudA · OnPrem–CloudB |
| Selective peering | OnPrem–CloudA · CloudA–CloudB |

Each configured link has a workflow-level state: **good / degraded / failed**.

- Degraded: ¼ bandwidth and 2.5× base latency
- Failed: edge removed; route search may use an alternate path
- Shortest-delay route for each workflow handoff

<!-- Speaker notes (1:35): The three graphs differ only in which physical links are present. Link state is sampled for the duration of each workflow. Good, degraded, and failed states change bandwidth, propagation latency, availability, and route feasibility. For each handoff, the simulator searches for the minimum-delay path over available links. This is a transparent analytical graph model rather than packet-level networking: there are no queues or within-workflow link transitions. -->

---

## Cost, latency, and reliability model

```text
Total cost = OAT API cost + compute + egress + SLO-failure penalty
```

- Makespan follows DAG dependencies and parallel branch barriers
- Deadline = 1.15 × trace-observed service latency
- Site speeds calibrated with CloudSim Plus 8.0.0
- Cloud prices, link profiles, availability, and failure penalty are assumptions

**CloudSim Plus calibrates relative compute speed; Python models dynamic network paths.**

<!-- Speaker notes (1:20): The task runtime observed in the trace is scaled by the relative speed of the assigned site. CloudSim Plus calibration gives factors of about .773, 1.0, and 1.364. We compute DAG makespan with handoff delays. Cost includes the trace API charge, modeled compute and egress, and an SLO failure penalty. The deadline is 1.15 times observed service time. Prices, availability, link rates, and the penalty are assumptions, not provider data. -->

---

## Why use chance constraint + CVaR?

| Measure | Strength | Limitation |
|---|---|---|
| Expected cost | Clear average-spend objective | Can hide rare severe outcomes |
| Chance constraint | Bounds SLO-violation probability | Does not distinguish failure severity |
| CVaR₉₀ | Prices average loss in worst 10% | Depends on penalty and risk preference |

**Model:** minimize expected cost + `λ × (CVaR₉₀ − expected cost)`  
subject to predicted SLO-violation probability ≤ 0.10; primary `λ = 0.5`.

<!-- Speaker notes (1:45): This is the risk-model trade-off. Expected cost alone is easy to communicate but can ignore a costly tail. A chance constraint directly controls how often the placement is expected to violate the SLO, but it treats a small miss like a large one. CVaR captures the cost severity in the worst ten percent, but depends on how we set the failure penalty and lambda. We use the chance constraint as a service requirement and CVaR as a preference over feasible placements. If no mapping is feasible, a least-violation fallback is reported as such. -->

---

## Paid link inspection: Pandora’s Box inspiration

For each unmeasured link, compute:

`VOI(link) = current best score − expected best score after inspection`

1. Consider each possible link state
2. Re-optimize the entire workflow placement and routing
3. Inspect the link with largest positive `VOI − inspection price`
4. Stop when no link is worth its price

**Greedy heuristic only:** no optimality guarantee; states are revealed perfectly.

<!-- Speaker notes (1:40): Pandora’s Box motivates treating information as something with a price. Our implementation does not claim the classic reservation index is optimal here: links affect shared routes and multiple workflow edges, so alternatives are coupled. The greedy policy measures the value of a link by evaluating the best placement before and after each possible observation. It then inspects the best positive net-value link. The current inspection is perfect and has a fixed assumed price of five ten-thousandths of a dollar. No optimality guarantee follows from this heuristic. -->

---

## Experiment and reproducibility

**403 workloads × 3 topologies × 11 policies = 12,897 outcomes**

- Placement baselines: exact cost-first, taskwise greedy, mean–variance, latency-first, deterministic point-profile, single-site
- Information policies: no inspection, adaptive VOI, matched random, inspect all
- Free perfect-information counterfactual reported separately (not deployable)
- Metrics: total cost, mean/p95 latency, SLO violations, inspections
- Paired topology comparisons: bootstrap over matching workflows
- Payload stress test: handoff sizes ×1,000 (sensitivity, not observed traffic)

<!-- Speaker notes (0:50): Each conformant workflow is evaluated with eleven placement/information criteria under all three topologies, for 12,897 outcomes. Metrics share workflow inputs, and topology differences use paired bootstrap intervals. A separate sensitivity scales handoff sizes by 1,000; it is not a claim about real message sizes. -->

---

## Result 1: topology matters most for parallel DAGs

**No inspection, parallel workflows (n = 120)**

| Topology | Mean cost | Mean latency | P95 latency |
|---|---:|---:|---:|
| Full mesh | $0.030054 | 65.70 s | 123.03 s |
| Hub-and-spoke | $0.030893 | 63.65 s | 111.54 s |
| Selective peering | $0.030893 | 63.65 s | 111.54 s |

Hub/selective cost delta vs full mesh: **+$0.000839**  
Paired 95% bootstrap CI: **[$0.000502, $0.001220]**

<!-- Speaker notes (1:30): In the no-inspection parallel condition, sparse topologies cost about $0.000839 more per workflow than full mesh, with a paired interval excluding zero in this simulation. Their modeled mean latency is around 2.05 seconds lower. The mapping, route, price, sampled link state, and egress assumptions interact. Sequential and supervisor outcomes are tied here. This is not a general real-cloud topology ranking. -->

---

## Placement baselines expose the trade-off

**Full mesh, all 403 workflows**

| Placement rule | Mean cost | Mean latency | CVaR₉₀ | SLO failures |
|---|---:|---:|---:|---:|
| Cheapest feasible | $0.018782 | 58.61 s | $0.046708 | 8 |
| Taskwise greedy | $0.018753 | 57.86 s | $0.045510 | 6 |
| Deterministic point profile | $0.018872 | 58.11 s | $0.046884 | 8 |
| Mean–variance | $0.019495 | 53.27 s | $0.045358 | 6 |
| Risk-adjusted, no inspection | $0.019550 | 51.34 s | **$0.042584** | **2** |
| Latency-first | $0.022505 | **37.20 s** | $0.050701 | **2** |

Free perfect-information is a non-deployable counterfactual; named-system reproductions are out of scope.

<!-- Speaker notes (1:10): This table shows why one baseline is not enough. Cheapest feasible minimizes average cost, but it has eight SLO failures here. The risk-adjusted baseline spends more and sees two failures, with the lowest empirical CVaR in the table. Latency-first is much faster but costs more and has a larger tail cost. These are sample outcomes under assumed infrastructure. The deterministic profile and mean–variance rows are common-model comparators, not full COLAP or S-CEDA implementations. -->

---

## Result 2: inspection is not automatically beneficial

Across the 403-workflow baseline:

- No inspection: **2** observed SLO failures
- Adaptive VOI: **4** failures; about **0.14–0.17** tests/workflow
- Inspect all: **5** failures; cost higher than no inspection in all topologies

These are realized outcomes under one sampled network seed.  
Expected-value inspection need not win in each realized episode.

<!-- Speaker notes (1:35): The adaptive policy buys relatively few inspections, averaging around fifteen hundredths per workflow. In this one realized sample it records four failures, compared with two for no inspection. Inspect-all records five failures and costs more than no inspection across all topology scenarios. We should not interpret that as proof inspection raises expected failure. The policy acts on posterior expectations, and a policy evaluated on one sampled current state can lose ex post. The result does show that information is not free and perfect information is not automatically worth buying under the chosen price. -->

---

## Sensitivity and limits

- At ×1,000 payload, full-mesh no-inspection network cost rises to ≈ **$0.0000127/workflow**
- OAT is generated synthetic data; supervisor/parallel dependencies are partly inferred
- Infrastructure prices, site availability, link priors, and penalties are assumptions
- Network model has no queues or within-run transitions; inspection is perfect
- Intervals reflect this simulation sample, not real-cloud uncertainty

<!-- Speaker notes (1:10): Larger payloads make network charges more visible: full-mesh network cost rises from about $0.00000005 to $0.0000127 per workflow in the stress run. This scales trace fields and proxies, so it is only a sensitivity. Other limits include generated traces, partial dependency evidence, assumed infrastructure parameters, and no network queues. Intervals describe workflow variation, not assumption uncertainty. -->

---

## Conclusion and next scientific steps

**Takeaway:** placement, SLO risk, network state, and inspection cost can be evaluated in one trace-driven model.

1. Repeat network-state seeds and sweep deadline, penalty, and inspection price
2. Add noisy inspections and correlated link states
3. Compare greedy VOI against an exact small-instance oracle
4. Calibrate with measured links and explicit billing data

<!-- Speaker notes (1:10): We built a reproducible path from agent events to DAG placement under three hybrid-cloud graphs. Topology matters most for parallel workflows, and information does not help uniformly. Next, repeat network sampling, sweep assumptions, model noisy inspections and correlated failures, and compare with an exact small-instance oracle. Provider claims require measured network and billing data. Thank you. -->

---

## Selected references

- Weitzman, “Optimal Search for the Best Alternative,” 1979
- Rockafellar & Uryasev, “Optimization of Conditional Value-at-Risk,” 2000
- Open Agent Traces dataset card, pinned release
- Guo et al., multi-cloud workflow scheduling, 2018
- Chaudhry et al., Murakkab, OSDI 2026
- CloudSim Plus 8.0.0 API documentation

<!-- Speaker notes (0:35): These references anchor the information-acquisition, risk, workflow scheduling, workload, and simulation components. The paper includes the full reference list and the pinned OAT revision. -->
