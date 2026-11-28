# Results and reproducibility notes

## Primary experiment: OAT trace-driven hybrid-cloud placement

The current primary results are produced by `oat_reconstruct.py` and `integrated_experiment.py`, not by the earlier toy experiment. The input is Open Agent Traces revision `dff8ed6331f5abf9ec8ad825088eeb4caa6715a`. It contains 17,019 generated events across 500 workflows. The pipeline excludes 97 runs marked as deviant and retains 403 conformant workflows: 170 sequential, 113 supervisor, and 120 parallel. All 403 are evaluated under three topologies and eleven placement/information policies, giving 13,299 episode rows.

Run from the repository root:

```bash
python3 oat_reconstruct.py
python3 integrated_experiment.py --seed 6111
python3 integrated_experiment.py --seed 6111 --payload-scale 1000 \
  --output-dir results/integrated_oat_payload1000
```

The normal outputs are `results/open_agent_traces/workflows.jsonl`, `results/open_agent_traces/audit.json`, and `results/integrated_oat_baselines/`. The latter contains episode-level results, pattern/topology/policy summaries, paired topology comparisons, assumptions, and limitations. The dataset download is pinned; reconstructed workflow files are generated locally.

### Placement baselines

The proposal names static placement, greedy cheapest-feasible placement, DWS, ADPSOGA, S-CEDA, COLAP, Murakkab, and SageServe. We do not claim to reproduce those full systems. Instead, we implement common-model comparisons: exact expected-cost placement under the same chance constraint; a taskwise greedy cheapest-feasible heuristic; mean–variance cost; latency-first placement under the chance constraint; a deterministic point-profile SLO comparator; a single-site co-location restriction; and a free perfect-information counterfactual. These are compared with risk-adjusted no-inspection, adaptive VOI, matched-random inspection, and inspect-all. Exhaustive enumeration gives the risk-adjusted no-inspection policy the exact best mapping under its stated criterion for this small workload model. The taskwise greedy policy assigns in topological order with unassigned tasks provisionally placed on CloudB. The free-information result is non-deployable and included as an informational reference; it is not a guaranteed lower bound on realized episode cost.

| Full-mesh policy | Mean cost (USD) | 95% CI | Mean latency | CVaR90 | Violations / 403 |
|---|---:|---:|---:|---:|---:|
| Cheapest feasible (expected cost) | 0.018782 | [0.017584, 0.019979] | 58.61 s | 0.046708 | 8 |
| Taskwise greedy cheapest-feasible | 0.018753 | [0.017591, 0.019915] | 57.86 s | 0.045510 | 6 |
| Deterministic point-profile SLO | 0.018872 | [0.017672, 0.020073] | 58.11 s | 0.046884 | 8 |
| Mean–variance cost | 0.019495 | [0.018355, 0.020635] | 53.27 s | 0.045358 | 6 |
| Risk-adjusted, no inspection | 0.019550 | [0.018521, 0.020578] | 51.34 s | 0.042584 | 2 |
| Latency-first | 0.022505 | [0.021277, 0.023733] | 37.20 s | 0.050701 | 2 |
| Single-site | 0.019799 | [0.018714, 0.020885] | 50.72 s | 0.044542 | 2 |
| Perfect-information counterfactual | 0.019268 | [0.018158, 0.020378] | 54.27 s | 0.044300 | 5 |

Cost-first policies lower mean expenditure but have more realized SLO failures in this sample. Latency-first lowers average latency at a higher mean cost and has a larger empirical cost tail. The risk-adjusted baseline has the lowest CVaR90 among these full-mesh rows. These are not universal rankings: they depend on assumed input values and one sampled network seed.

### Main findings

At baseline payload size, the no-inspection outcomes by pattern are:

| Pattern | Topology | n | Mean total cost (USD) | Mean latency | P95 latency | SLO violations |
|---|---|---:|---:|---:|---:|---:|
| Sequential | All three | 170 | 0.011859 | 38.24 s | 59.13 s | 0 |
| Supervisor | All three | 113 | 0.019965 | 55.78 s | 85.87 s | 2 |
| Parallel | Full mesh | 120 | 0.030054 | 65.70 s | 123.03 s | 0 |
| Parallel | Hub-and-spoke | 120 | 0.030893 | 63.65 s | 111.54 s | 0 |
| Parallel | Selective peering | 120 | 0.030893 | 63.65 s | 111.54 s | 0 |

For parallel workflows with no inspection, hub-and-spoke and selective peering each cost $0.000839 more per workflow than full mesh. Paired 95% bootstrap intervals are [$0.000502, $0.001220] and [$0.000498, $0.001225], respectively. Mean modeled latency is about 2.05 seconds lower in the sparse topologies in this comparison. Sequential and supervisor no-inspection outcomes are ties across topology in this run.

Across all 403 workflows, no-inspection recorded two violations per topology. Adaptive VOI recorded four violations and averaged roughly 0.14–0.17 link inspections per workflow. Inspect-all recorded five violations and cost more on average than no-inspection for each topology. These are realized outcomes from one sampled network seed; they do not establish that inspection worsens expected risk. The implementation’s greedy objective is posterior expected risk-adjusted value, and ex-post realized performance can differ.

The payload sensitivity multiplies handoff sizes by 1,000. It increases full-mesh no-inspection network cost from approximately $0.00000005 to $0.0000127 per workflow. This is a modeled stress test, not a measured payload distribution.

### Reconstruction audit

The audit is in `results/open_agent_traces/audit.json`. Sequential workflow arcs have complete direct message-edge coverage. Supervisor and parallel event traces directly represent two-thirds of their normative template arcs; some dependencies are inferred from execution order/barrier evidence. Overall direct message-to-template-arc coverage is 73.2%. Deviation runs are excluded. This is why the paper distinguishes observed messages from inferred dependencies instead of claiming every reconstructed DAG is a literal normative graph.

### Model and limitations

OAT supplies workflow/task fields. Site prices, site availability, link bandwidth and latency, link-state priors, egress price, link-inspection price, failure penalty, and deadline multiplier are assumptions. The run’s assumptions and baseline definitions are recorded in `results/integrated_oat_baselines/metadata.json`. CloudSim Plus 8.0.0 generates relative compute-speed factors from three Cloudlet/VM classes; it is not used to calibrate prices or network behavior. The Python experiment models handoff delay with a state-aware shortest-path graph. It does not include packet queues, congestion coupling, or link changes during a workflow. Inspections perfectly reveal the current link state. Confidence intervals capture workflow/sample variation under the selected scenario, not parameter uncertainty or real-world cloud variation.

The confidence intervals for mean cost are normal intervals across workflows; violation-rate intervals use Wilson intervals; topology differences use 1,000-resample paired bootstrap intervals. Because OAT itself is generated and infrastructure inputs are assumed, the intervals should not be interpreted as population-level or provider-level guarantees.

## Separate legacy experiment: nine-state Pandora’s Box baseline

`experiment.py` retains the earlier synthetic three-stage chain with nine independent agent-resource good/bad states. Its result files and claims are not pooled with the OAT experiment above. In its 30-seed, 3,000-episode setting, the exact adaptive dynamic program outperformed greedy inspection for that finite nested-risk objective. That result motivates the importance of inspection complementarity but does not describe the trace-driven hybrid-cloud result, which currently has no exact adaptive DP benchmark.

## Separate Java prototype

`cloudsim-fullmesh/WorkflowPlacementSimulation` remains a standalone full-mesh prototype. It is separate from the main Python experiment. `CloudSimComputeProfile` is the Java utility used to generate the relative compute calibration profile consumed by `integrated_experiment.py`.
