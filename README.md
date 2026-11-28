# Cost-Aware Agent Placement in Dynamic Hybrid Clouds

The primary experiment now reconstructs agent workflow DAGs from Open Agent Traces, evaluates full-mesh, hub-and-spoke, and selective-peering networks, and integrates cost, service risk, dynamic link states, and paid link inspection. CloudSim Plus calibrates relative site execution speed. A smaller nine-uncertainty synthetic Pandora’s Box study remains available as a separate baseline in `experiment.py`.

## Legacy synthetic inspection baseline

The workflow is a three-stage chain (`Planner -> Researcher -> Writer`) placed on three illustrative resources: on-premises, Cloud-A, and Cloud-B. Each agent-resource pair has a binary latent performance state (good/bad). The prior probability is resource-specific. An inspection costs $0.65 and reveals that pair's state exactly. This is the report's initial perfect-measurement abstraction; inspection noise is not modeled yet.

For placement `x` and latent state `omega`, the simulator computes:

`C(x, omega) = compute + cross-resource transfer + $20 * 1{SLO failure}`.

The workflow fails if chain latency exceeds 115 ms or end-to-end reliability falls below 0.80. The risk-neutral criterion is expected total cost. The primary risk-aware criterion is

`J(x) = E[C(x, omega)] + lambda * (CVaR_0.90(C(x, omega)) - E[C(x, omega)])`,

with `lambda=0.50`, subject to `P(SLO failure) <= 0.10`. Thus cost is always paid in the objective, while risk enters both as a hard service-reliability requirement and as a tail-cost premium. The penalty amount translates SLO failures into economic loss; report it as a simulation assumption and vary it in sensitivity analysis.

If no placement satisfies the chance constraint under the current posterior, the solver explicitly falls back to the placement with the lowest predicted violation probability (breaking ties by expected cost). This can produce a policy-level violation rate above 10%; it signals that the posterior admits no feasible assignment, rather than silently claiming the constraint was met.

The adaptive policy estimates the reduction in the best posterior objective from inspecting each unobserved pair, subtracts the inspection cost, and inspects the pair with the highest positive net value. It stops when no inspection has positive net value. This is a greedy, placement-coupled VOI heuristic inspired by Pandora's Box, not an exact Weitzman index. With `--include-exact-adaptive`, the simulator also runs a dynamic program that is optimal for the finite model's nested objective: expected inspection cost plus expected terminal posterior risk-adjusted placement score. It is a small-instance benchmark, not a scalable policy or a global-CVaR objective over the whole adaptive policy.

## Risk-model trade-offs

- **Expected cost only** is simple and cost-efficient on average, but can hide rare expensive failures.
- **Chance constraint** directly controls the probability of missing the latency/reliability SLO. It is easy to explain operationally, but says little about how severe failures are and can be brittle near the threshold.
- **CVaR** measures the average cost in the worst 10% of outcomes, distinguishing mild from severe downside. It needs a defensible failure-cost model and a risk-weight choice; it can also pay extra to avoid tail outcomes even when the chance constraint already passes.

The experiment uses the chance constraint for minimum acceptability and CVaR as a preference among acceptable placements. `--risk-weight 0` isolates expected-cost placement with the same chance constraint and fallback; positive values expose the cost-versus-tail-risk trade-off. Compare both settings in the discussion rather than presenting CVaR as universally best.

## Policies and outputs

The simulator compares no inspection, adaptive VOI, inspect-all, and random inspection with a matched test count. With `--include-exact-adaptive`, it also reports exact dynamic programming and random inspection matched to the exact policy's test count. Output includes aggregate, episode-level, and per-seed CSV files, supporting confidence intervals across independent seeds.

Run with Python 3 and no third-party packages:

```bash
python3 experiment.py --episodes 100 --replicates 30 --seed 6111 --risk-weight 0.5 --inspection-cost 0.65 --include-exact-adaptive --output-dir results/reproduce_primary
python3 experiment.py --episodes 100 --replicates 30 --seed 6111 --risk-weight 0 --inspection-cost 0.65 --output-dir results/reproduce_risk_neutral
```

All resource prices, latency profiles, state probabilities, transfer charges, and failure penalties in this **legacy toy baseline** are hand-set simulation assumptions, not measured AWS/Azure/GCP/on-prem prices or CloudLab measurements. This baseline does not ingest Open Agent Traces and uses one fixed cross-resource transfer charge. Its results are separate from the integrated OAT experiment below and should not be interpreted as empirical claims about real providers.

## Integrated trace-driven experiment

`oat_reconstruct.py` downloads the ten OCEL 2.0 logs and their workflow templates from a pinned Open Agent Traces revision, excludes non-conformant deviation runs by default, and writes node/edge JSONL plus a reconstruction audit. It exports only roles, timestamps, token counts, estimated invocation costs, and handoff lengths; it does not export prompts, completions, or reasoning.

`integrated_experiment.py` reads those DAGs and compares eleven placement/information policies over three graph layouts: risk-aware no-inspection, exact expected-cost cheapest-feasible, taskwise greedy cheapest-feasible, mean–variance cost, latency-first, deterministic point-profile SLO, single-site, adaptive VOI inspection, random matched inspection, inspect-all, and a free perfect-information counterfactual. Full mesh contains all three site pairs; hub-and-spoke uses OnPrem as its hub; selective peering connects OnPrem–CloudA and CloudA–CloudB. Each link epoch has good, degraded, or failed states. The risk-aware policies use the shared cost model, CVaR90 premium, and 10% chance constraint; the deterministic and latency-first baselines intentionally change the decision criterion. The perfect-information result is non-deployable and is included as an informational reference, not a guarantee of lower realized cost.

These are common-model comparator implementations, not full reproductions of DWS, ADPSOGA, S-CEDA, COLAP, Murakkab, or SageServe. The finite placement space is exhaustively enumerated, providing an exact prior-placement solution for the selected objective on this small instance. The taskwise greedy baseline commits to a site for each task in topological order, evaluating provisional completions with unassigned tasks on CloudB. The mean–variance policy captures a risk-criterion contrast, and the deterministic point-profile baseline captures the point-estimate decision style. Algorithm-specific features such as MPC, ARIMA forecasting, MILP, or NSGA-II are not implemented. The perfect-information policy is a non-deployable counterfactual; it is not guaranteed to beat other policies in each realized episode.

Open Agent Traces is an MIT-licensed **generated synthetic dataset**, not production telemetry. It supplies workflow structure and workload measurements, but it contains no hybrid-cloud link measurements or cloud VM prices. Site prices, link bandwidth/latency/state priors, reliability, and failure penalty are therefore explicit assumptions in `integrated_experiment.py` and `results/integrated_oat_baselines/metadata.json`. The handoff `content_length` is treated as a byte proxy, with `--payload-scale` available for sensitivity analysis. The supervisor traces can be serialized even where the normative template specifies fan-out/fan-in; the reconstruction audit exposes this mismatch.

Run from the repository root (requires Python 3.10+, Maven, and a JDK):

```bash
mvn -f cloudsim-fullmesh/pom.xml package
mvn -f cloudsim-fullmesh/pom.xml exec:java \
  -Dexec.mainClass=edu.project.hybrid.CloudSimComputeProfile \
  -Dexec.args=compute_profile.csv
python3 oat_reconstruct.py
python3 integrated_experiment.py --seed 6111
```

The CloudSim Plus calibration produces the per-site relative execution profile used by the placement solver. The Python model applies this profile to measured trace service time, while it handles DAG scheduling and dynamic shortest-path routing; it does not model packet queues or within-run link transitions. Default outputs are `results/open_agent_traces/` (reconstructed DAGs and audit) and `results/integrated_oat_baselines/` (episode rows, topology-by-pattern summary, paired topology comparisons, and assumptions). The earlier standalone Java full-mesh model remains available for comparison but is not the integrated experiment.
