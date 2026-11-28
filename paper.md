# Cost-Aware Placement of Trace-Reconstructed Agent Workflows in Dynamic Hybrid Clouds

**Boyang Yan and Yusen Wu**  
CS 6111 — Cloud Computing  
Simulation study; infrastructure parameters are explicit scenario assumptions

## Abstract

Agent workflows combine model calls and tools through sequential, supervisory, and parallel dependencies. Placing their tasks across on-premises and public-cloud resources creates a joint compute, communication, latency, and reliability problem. Because network conditions are uncertain, an operator may also pay to measure current link state before committing to a placement. This paper presents a trace-driven simulation that connects these decisions. We reconstruct workflow directed acyclic graphs (DAGs) from the pinned Open Agent Traces (OAT) release, then enumerate task-to-site assignments under full-mesh, hub-and-spoke, and selective-peering network graphs. For each workflow, an uncertainty-aware objective combines API and infrastructure costs, a service-level-objective (SLO) chance constraint, and a conditional value-at-risk (CVaR) premium. A greedy, Pandora’s Box-inspired policy buys link-state inspections when their estimated reduction in the optimized posterior objective exceeds their price. The dataset contains 17,019 generated events in 500 runs; 403 conformant runs are included after excluding 97 traces marked deviant. The reconstruction audit finds complete direct template-edge coverage for sequential traces and partial coverage for the supervisor and parallel templates, where event-level handoffs omit some fan-out/fan-in arcs. In the simulation, topology effects are concentrated in parallel workloads: without inspection, hub-and-spoke and selective peering cost an estimated $0.000839 more per workflow than full mesh (paired bootstrap 95% interval [$0.000502, $0.001220], 120 workflows), while modeled latency was about 2.05 seconds lower. These small differences depend on assumed prices, link profiles, and routing rules. Adaptive inspection is not uniformly beneficial in realized episodes, and inspecting every link generally costs more than inspecting none. Results establish a reproducible modeling pipeline and conditional comparisons, not production-cloud performance claims.

In the full-mesh baseline suite, expected-cost placement averaged $0.018782 per workflow with eight observed SLO failures, while the risk-adjusted placement averaged $0.019550 with two; latency-first averaged $0.022505 and reduced mean latency from 51.34 to 37.20 seconds. These trade-offs are conditional on the modeled scenario. **Keywords:** agent workflows; hybrid cloud; workflow placement; network dynamics; value of information; Pandora’s Box; CVaR

## 1. Introduction

Agentic applications increasingly execute as workflows: a supervisor may delegate to several workers, independent agents may run in parallel before an aggregation step, or stages may execute sequentially. A placement policy maps each task to an execution site. In a hybrid cloud, each site can have a different execution rate, price, availability, and network relationship to the other sites. Assigning tasks independently can therefore be inefficient. A faster or cheaper site may increase handoff delay, transfer charges, or exposure to link failure, and a parallel workflow’s completion time depends on the slowest branch and its synchronization barrier.

The problem becomes harder when network state is not known at placement time. A link can be healthy, degraded, or unavailable. The operator can act on a prior belief, or spend time and money to inspect a link before selecting the workflow mapping. The value of that inspection is not intrinsic to a link: it depends on the workflow’s dependencies, which links the candidate placement uses, the alternate routes offered by the topology, and the cost of an SLO violation. Cost and risk must therefore be modeled together with information acquisition.

This project addresses the following question: **for trace-reconstructed agent DAGs, how do network topology and paid link-state information affect risk-aware placement cost and latency in a hybrid-cloud scenario?** We treat full mesh, hub-and-spoke, and selective peering as controlled infrastructure scenarios. The primary emphasis is the placement and information decision; the three topologies are a comparison axis rather than a claim that one general topology is universally best.

The study makes four contributions. First, it provides a reproducible reconstruction pipeline from OAT execution events, retaining task duration, input/output token counts, API-cost fields, timestamps, and dependency evidence while excluding prompt and completion text. Second, it makes the inference process auditable by comparing reconstructed edges with the dataset’s normative templates. Third, it integrates a cost-aware DAG placement model, dynamic link states, a chance constraint, CVaR, and paid link inspection. Fourth, it reports topology, policy, pattern, and payload-sensitivity comparisons, with uncertainty intervals and explicit assumptions.

The contribution is not a new general-purpose scheduler, an optimal Pandora’s Box policy, or a calibrated digital twin of a cloud provider. The original proposal described a broader forecast-driven, receding-horizon controller with Spot interruption risk; this evaluated implementation narrows the scope to one workflow placement episode with paid current-link inspections. It does not implement temporal forecasting, MPC, or a Spot market model, so none of the results should be attributed to those proposed features. OAT is generated synthetic data, and the cloud prices, link priors, site availability, and failure penalty in this experiment are scenario assumptions. CloudSim Plus calibrates relative execution speeds for the modeled site classes; it does not supply measured prices or model the network portion of the experiment. The results should be read as conditional simulation evidence and as a basis for a more calibrated study.

## 2. Related work

### 2.1 Workflow scheduling across clouds

Cloud workflow research has long considered the interaction between task precedence, deadlines, heterogeneous compute prices, and communication costs. Guo et al. study deadline-driven workflow scheduling across multiple clouds [1], while Arabnejad et al. consider dynamic multi-workflow scheduling under deadline and cost objectives [2]. Stochastic approaches incorporate uncertain task and communication times, as in S-CEDA [3], and reliability-aware methods adapt workflow execution under uncertain runtimes [4]. These studies establish that compute and communication should be considered jointly. Our work is smaller in scale and adds an explicit decision about whether to purchase current network information before placement.

### 2.2 Network-aware service and agent placement

COLAP predicts latency for service-function-chain placement across multiple clouds and uses those predictions in cost-oriented placement [5]. Murakkab studies resource-efficient agentic workflow orchestration, including model/hardware mapping and SLO-aware runtime behavior [6]. Both motivate modeling workflow structure and performance jointly. The present simulator differs in scope: it isolates a finite, pre-execution placement episode with discrete link states and priced inspections. It does not implement a production serving stack or compete with these systems’ scale and runtime functions.

### 2.3 Information acquisition and risk

Weitzman’s Pandora’s Box model formalizes search when alternatives have unknown values and inspection costs [7]. Later work studies combinatorial and correlated variants [8]. Here, an inspected link can alter several task assignments through shared workflow edges or alternate routes. The independent-alternative reservation-index result does not directly apply. We therefore use a greedy value-of-information (VOI) calculation that re-optimizes the complete placement after each possible observation; no optimality guarantee is claimed.

Expected cost, chance constraints, and CVaR represent different risk preferences. Expected cost minimizes average expenditure but can conceal rare severe outcomes. A chance constraint limits the probability of an SLO violation but treats failures of different severity alike. CVaR summarizes the upper tail of monetary loss, but depends on a meaningful failure-cost model and selected confidence level [9]. We use a chance constraint as a service-acceptability threshold and a CVaR premium to rank placements. This is a modeling choice, not a claim that CVaR is universally the right operational risk measure.

### 2.4 Workload data and infrastructure calibration

Open Agent Traces is an MIT-licensed, generated dataset containing 17,019 events across 500 workflow runs, 10 domains, and three patterns [10]. It supplies execution-event structure, token counts, latency and cost fields, and normative models. It is not production telemetry and does not report the network or cloud infrastructure measurements required to parameterize this study. CloudLab measurements show that datacenter performance can vary over time [11], but are not measurements of our three hypothetical sites. FOCUS defines interoperable cost and usage semantics [12]; it is not a source of provider price values. We accordingly distinguish OAT-derived workload fields from infrastructure assumptions throughout.

## 3. Proposed method

### 3.1 Trace reconstruction

The implementation downloads the ten domain-specific OCEL logs and normative models from a pinned OAT revision. It reconstructs one DAG per run using agent invocation/completion events and message-sent events. Node service time is derived from event timestamps; input/output token counts and invocation API cost come from the invocation records. Observed sender-to-receiver messages provide dependency evidence and message length when available. Where a parallel aggregate begins after all worker completion times but explicit join messages are absent, the pipeline adds inferred worker-to-aggregate barrier edges and marks their payload as estimated. No prompt, completion, or reasoning text is exported.

Runs labeled as nonconformant deviations are excluded from the main experiment. The remaining 403 traces comprise 170 sequential, 113 supervisor, and 120 parallel workflows. Each sequential DAG has three tasks and two edges; supervisor and parallel DAGs have five tasks, with reconstructed edge sets based on their events. The audit compares direct observed handoffs against normative template arcs: sequential arcs are all represented; supervisor and parallel event logs each represent two-thirds of their template arcs. Overall, 73.2% of normative arcs are directly represented by observed message handoffs. Missing template arcs are not silently treated as observed; inferred barriers are separately identifiable. This distinction matters because the supervisor traces can serialize work that the normative template depicts as fan-out/fan-in.

### 3.2 Hybrid-cloud graph and dynamics

The infrastructure graph has sites (S=\{O,A,B\}): OnPrem, CloudA, and CloudB. The experiment compares three undirected link graphs:

| Topology | Available physical links | Interpretation |
|---|---|---|
| Full mesh | O–A, O–B, A–B | Every pair has a direct link |
| Hub-and-spoke | O–A, O–B | OnPrem is the hub |
| Selective peering | O–A, A–B | CloudA is the bridge |

Each configured link independently occupies one state during a workflow: good, degraded, or failed. The state priors and base network profiles are assumptions: O–A uses 200 Mbps/25 ms with probabilities (0.90, 0.08, 0.02); O–B uses 120 Mbps/48 ms with (0.84, 0.12, 0.04); and A–B uses 300 Mbps/18 ms with (0.92, 0.07, 0.01). Degraded links have one-quarter bandwidth and 2.5 times the base latency; a failed link is removed. A Dijkstra-style shortest-delay path is selected for each handoff. Serialization delay depends on handoff bytes and link bandwidth. This is a small analytical graph model, not packet-level simulation: it does not model queues, congestion coupling, or link changes within a workflow.

Site execution rates use relative speed factors (OnPrem 0.773, CloudA 1.0, CloudB 1.364) obtained from a CloudSim Plus 8.0.0 Cloudlet calibration with three VM classes [13]. Those rates are simulator outputs for the calibration setup, not cloud benchmark measurements. Site hourly prices ($0.20, $0.42, $0.78), site availabilities (0.997, 0.999, 0.9995), egress prices ($0.02, $0.09, $0.08 per GB), and a $0.05 workflow failure penalty are scenario assumptions. OAT API-cost fields are included as workload costs.

### 3.3 Placement and risk model

Let a workload be a DAG `G=(V,E)`, with each task `i ∈ V` assigned to site `x_i ∈ S`. The implementation enumerates all `|S|^{|V|}` mappings (at most `3^5 = 243` in this dataset). For a link-state scenario `ω`, DAG execution times are computed in topological order. A task starts after both its parents complete and the corresponding handoffs arrive. Parallel branches therefore overlap; the workflow latency is the maximum task completion time.

For placement (x) and state (\omega), monetary deployment cost is

\[
C(x,\omega)=C_{API}+C_{compute}(x)+C_{egress}(x,\omega)+P_f\,\mathbf{1}\{L(x,\omega)>D\},
\]

where `L` is modeled makespan, `D = 1.15 × L_trace` is the deadline, and `P_f = $0.05`. The conditional failure probability also includes site and link availability when the deadline is met. The placement score under observations `O` is

\[
J(x\mid O)=\mathbb{E}[C(x,\omega)\mid O]+
\lambda\big(\operatorname{CVaR}_{0.90}(C\mid O)-\mathbb{E}[C\mid O]\big),
\]

subject to

\[
\Pr\{\text{SLO violation}\mid x,O\}\leq \epsilon,\qquad \epsilon=0.10.
\]

The primary risk weight is `λ = 0.5`. If no assignment meets the chance constraint, the simulator uses a least-violation fallback, minimizing predicted violation probability before expected loss. Such a fallback is reported as infeasible with respect to the constraint; it is not presented as satisfying the 10% requirement. The objective is a nested posterior-risk score used at each decision point, not a single unconditional CVaR over all adaptive policy outcomes.

### 3.4 Paid inspection policy

For a topology with `q` configured links, an inspection reveals the current state of one link perfectly and costs $0.0005. For uninspected link `e`, the greedy Pandora’s Box-inspired rule computes

\[
\operatorname{VOI}(e\mid O)=F(O)-\mathbb{E}_{z_e\mid O}[F(O\cup\{(e,z_e)\})],
\]

where `F(O) = min_x J(x | O)` subject to the chance constraint (with the documented fallback). It inspects the link with greatest positive net value `VOI − κ` and repeats until no positive net value remains. Because each branch re-optimizes the complete workflow mapping and routing, the rule accounts for interactions among tasks and routes. It is greedy and can miss complementary inspection value.

The comparison policies are: (1) risk-adjusted placement with no inspection; (2) exact expected-cost cheapest-feasible placement under the same chance constraint; (3) a taskwise greedy cheapest-feasible heuristic that assigns tasks in topological order; (4) mean–variance cost, using mean plus `λ` times cost standard deviation; (5) latency-first among chance-feasible mappings; (6) deterministic point-profile placement using mean latency and expected violation probability; (7) best co-located single-site placement; (8) adaptive VOI; (9) random inspection with the same realized count as the adaptive policy; (10) inspect all configured links; and (11) a free perfect-link-information counterfactual. The last condition is non-deployable and is included as an informational reference, not a guaranteed bound on realized cost. Inspection policy outcomes are evaluated against the sampled current state. Consequently, the expected-objective greedy policy is not guaranteed to have lower realized cost in each episode; ex-post comparisons are descriptive of this sampled simulation.

These are common-model placement criteria, not full reproductions of every named scheduler in the original proposal. The expected-cost baseline corresponds to cheapest-feasible placement, while the taskwise heuristic adds a genuinely greedy comparator; the point-profile condition captures deterministic prediction-guided placement; the mean–variance condition tests an alternative risk criterion; and the single-site condition measures the value of allowing cross-site placement. The placement space is exhaustively enumerated, so the risk-adjusted no-inspection policy is an exact prior-optimal mapping for the stated finite objective, stronger than using a metaheuristic such as ADPSOGA on this small instance. DWS’s ready-task heuristic, ADPSOGA’s evolutionary search, S-CEDA’s NSGA-II, COLAP’s SVR/random search, Murakkab’s MILP/autoscaling, and SageServe’s ARIMA/ILP are not claimed as algorithmic reproductions.

## 4. Theoretical analysis

The finite placement problem is exactly enumerable for this study: at most 243 mappings and three link states per configured edge (at most `3^3 = 27` scenarios). For `n` tasks and `m` sites, placement enumeration grows as `m^n`; for `q` uncertain links, full state enumeration grows as `3^q`. Exact adaptive inspection would additionally require a belief-state decision tree and is not implemented in the trace-driven experiment. The results therefore evaluate a tractable greedy heuristic, not an optimal inspection policy.

The standard Pandora’s Box index is not asserted to apply because link states affect shared routes and multiple workflow edges, and the placement utility is combinatorial. The VOI calculation is a one-step re-optimization heuristic. A future small-instance dynamic program could provide an oracle for the same nested objective and quantify the greedy gap. No approximation ratio is claimed here.

## 5. Performance evaluation

### 5.1 Experimental protocol

We evaluate all 403 conformant OAT workflows under each of the three topologies and eleven placement/information conditions, producing 12,897 workflow-policy-topology rows. The random seed is 6111. Costs and latencies are summarized by workflow pattern and condition. Mean-cost intervals use a normal 95% interval across workflows; violation-rate intervals use Wilson intervals. Paired topology differences use 1,000-resample bootstrap intervals over matching workflow identifiers. Because the dataset is synthetic and infrastructure parameters are assumed, these intervals describe variability in the experiment and do not quantify uncertainty in real cloud behavior or the input assumptions.

The baseline handoff size uses observed message length where available and a token-based proxy for inferred barriers. The sensitivity run scales every handoff by 1,000 to expose whether larger payloads change routing, egress charges, and policy choices. This is a stress test, not an estimate of actual payload size. Reproduce the primary run with `python3 oat_reconstruct.py` followed by `python3 integrated_experiment.py --seed 6111`; use `--payload-scale 1000` for the stress condition.

### 5.2 Main policy and risk results

At baseline payload size, no-inspection has two observed SLO violations among 403 workflows for each topology. Adaptive VOI uses a mean of approximately 0.14–0.17 inspections per workflow, depending on topology, but records four violations in this realized sample. Inspect-all measures every configured link (two or three) and records five violations; its mean total cost is higher than no-inspection under all three assumptions. Random matched-count is close to no-inspection because the adaptive policy commonly buys few measurements.

The broader placement comparison is shown for full mesh in Table 2. Cost-only placement has the lowest deployable mean cost among these listed criteria, but records eight realized violations and has the highest mean latency among the cost/risk baselines. Latency-first reduces mean latency substantially but raises cost and empirical CVaR. The mean–variance and risk-adjusted criteria occupy intermediate points; neither dominates on every metric. The single-site baseline matches the risk-aware objective under hub-and-spoke and selective peering in this run, indicating that the optimizer often chooses a co-located assignment. The perfect-information counterfactual is cheaper than inspect-all because it incurs no measurement charge, but it still has five realized violations and is not actionable; its realized cost is not guaranteed to be a lower bound.

| Full-mesh policy | Mean cost (USD) | 95% CI | Mean latency | CVaR90 | Violations / 403 | Mean inspections |
|---|---:|---:|---:|---:|---:|---:|
| Cheapest feasible (expected cost) | 0.018782 | [0.017584, 0.019979] | 58.61 s | 0.046708 | 8 | 0 |
| Taskwise greedy cheapest-feasible | 0.018753 | [0.017591, 0.019915] | 57.86 s | 0.045510 | 6 | 0 |
| Deterministic point-profile SLO | 0.018872 | [0.017672, 0.020073] | 58.11 s | 0.046884 | 8 | 0 |
| Mean–variance cost | 0.019495 | [0.018355, 0.020635] | 53.27 s | 0.045358 | 6 | 0 |
| Risk-adjusted, no inspection | 0.019550 | [0.018521, 0.020578] | 51.34 s | 0.042584 | 2 | 0 |
| Latency-first | 0.022505 | [0.021277, 0.023733] | 37.20 s | 0.050701 | 2 | 0 |
| Single-site | 0.019799 | [0.018714, 0.020885] | 50.72 s | 0.044542 | 2 | 0 |
| Perfect-information counterfactual | 0.019268 | [0.018158, 0.020378] | 54.27 s | 0.044300 | 5 | 0 |

These values show distinct cost/latency/tail-risk trade-offs; they do not establish one baseline as universally superior. The perfect-information condition is evaluated after revealing all current link states but excludes inspection expense by construction.

These realized values do not show that inspection is harmful in expectation. The policy selects tests using posterior expected risk-adjusted value, while the reported row is one sampled current state. Nor do they establish that the chosen inspection price is realistic. They do show that perfect information is not automatically worth buying, and that the policy should be evaluated across repeated network-state samples and inspection-cost sensitivities before a deployment claim.

### 5.3 Topology effects

Under no inspection, sequential and supervisor workflows have identical cost and latency between topologies in this run, because their selected placements do not use links whose alternative paths change the outcome. For parallel workflows, hub-and-spoke and selective peering each increase mean total cost relative to full mesh by $0.000839 per workflow (paired 95% bootstrap intervals [$0.000502, $0.001220] and [$0.000498, $0.001225], respectively; `n = 120`). Their modeled mean latency is about 2,052 ms lower than full mesh in the same paired comparison. The joint result is possible because placement, route, and cost are optimized together under a particular sampled/assumed setting; it is not a general monotonic property of denser graphs.

| Pattern, no inspection | Topology | Mean cost (USD) | Mean latency (ms) | P95 latency (ms) | SLO violations |
|---|---|---:|---:|---:|---:|
| Sequential | All three | 0.011859 | 38,240 | 59,131 | 0/170 |
| Supervisor | All three | 0.019965 | 55,776 | 85,872 | 2/113 |
| Parallel | Full mesh | 0.030054 | 65,704 | 123,031 | 0/120 |
| Parallel | Hub-and-spoke | 0.030893 | 63,653 | 111,544 | 0/120 |
| Parallel | Selective peering | 0.030893 | 63,653 | 111,544 | 0/120 |

Topology comparisons are conditional on the locations, costs, link priors, routing model, and workload payloads selected here. In particular, the small modeled egress charge means that latency and availability can matter more than network price at baseline. The paired differences should not be described as a universal ranking of topologies.

### 5.4 Payload stress test

Scaling handoff payloads by 1,000 raises the full-mesh no-inspection average network charge to approximately $0.0000127 per workflow, compared with approximately $0.00000005 at baseline, and increases mean latency modestly. The topology choice can therefore become more consequential as payloads grow. However, the stress run’s payloads are mechanically scaled OAT message-length fields and token-derived proxies. It tests model sensitivity; it does not provide empirical evidence that real agent messages are 1,000 times larger.

### 5.5 Interpretation and limitations

The experiment supports three limited conclusions. First, DAG dependencies and topology jointly affect placement most visibly when branches execute in parallel. Second, the value of inspection is conditional on the inspection price, risk preference, and what the placement optimizer can do after observing the state; inspecting every link is not justified by the current assumptions. Third, model transparency is essential: OAT fields drive task workload, but not cloud network dynamics or provider pricing.

Several limitations constrain interpretation. OAT is generated, not production-derived. Conformance to normative graphs is incomplete for supervisor and parallel runs, so reconstructed dependencies retain observed/inferred provenance. Infrastructure price, availability, link states, and physical rates are assumptions; CloudSim Plus provides relative CPU calibration only. Link states are independent and fixed for one workflow, inspections are perfect, and the routing model excludes queueing and congestion. The $0.05 failure penalty and 1.15 deadline factor are also assumptions. The confidence intervals reflect workflow-level variation under this one seed and scenario, not uncertainty in those choices. Broader sensitivity analysis, repeated state seeds, noisy measurements, correlated link failures, and calibrated provider/testbed data are needed before stronger conclusions.

## 6. Conclusion

We presented a trace-driven model for placing sequential, supervisor, and parallel agent workflows across dynamic hybrid-cloud network graphs. The model combines OAT-derived workload fields, finite placement enumeration, link-state uncertainty, paid inspections, SLO chance constraints, and a CVaR tail-cost premium. Full mesh, hub-and-spoke, and selective peering were evaluated as controlled scenarios. In this experiment, topology differences were concentrated in parallel workflows, while indiscriminate inspection increased cost under the assumed parameters. These outcomes are conditional rather than provider-level findings.

The next scientific step is not simply to add more topologies. It is to improve the model’s empirical grounding and validate the decision rule: repeat state sampling across seeds, sweep deadline and failure-cost assumptions, introduce noisy inspections and correlated link states, and compare greedy VOI with an exact oracle on reduced instances. A future study should also use measured network profiles and explicit cloud billing data. This provides a path from a reproducible course-project simulation toward a defensible systems evaluation.

## References

[1] W. Guo, B. Lin, G. Chen, Y. Chen, and F. Liang, “Cost-Driven Scheduling for Deadline-Based Workflow Across Multiple Clouds,” *IEEE Transactions on Network and Service Management*, 15(4), 1571–1585, 2018. [doi:10.1109/TNSM.2018.2872066](https://doi.org/10.1109/TNSM.2018.2872066).

[2] V. Arabnejad, K. Bubendorfer, and B. C. K. Ng, “Dynamic Multi-Workflow Scheduling: A Deadline and Cost-Aware Approach for Commercial Clouds,” *Future Generation Computer Systems*, 100, 98–108, 2019. [doi:10.1016/j.future.2019.04.029](https://doi.org/10.1016/j.future.2019.04.029).

[3] R. A. Haidri, C. P. Katti, and P. C. Saxena, “Cost-Effective Deadline-Aware Stochastic Scheduling Strategy for Workflow Applications on Virtual Machines in Cloud Computing,” *Concurrency and Computation: Practice and Experience*, 31(7), e5006, 2019. [doi:10.1002/cpe.5006](https://doi.org/10.1002/cpe.5006).

[4] W. Wang, Q. Ren, G. Yao, and S. Zhu, “Reliable Cloud Workflow Scheduling with Uncertain Task Execution Time,” *Journal of King Saud University Computer and Information Sciences*, 38, article 216, 2026. [doi:10.1007/s44443-026-00585-x](https://doi.org/10.1007/s44443-026-00585-x).

[5] L. Gupta, M. Samaka, R. Jain, A. Erbad, D. Bhamare, and C. Metz, “COLAP: A Predictive Framework for Service Function Chain Placement in a Multi-Cloud Environment,” in *2017 IEEE 7th Annual Computing and Communication Workshop and Conference*, 2017. [Paper](https://www.cse.wustl.edu/~jain/papers/ftp/clp_ccwc.pdf).

[6] G. I. Chaudhry et al., “Murakkab: Resource-Efficient Agentic Workflow Orchestration in Cloud Platforms,” in *20th USENIX Symposium on Operating Systems Design and Implementation (OSDI 26)*, 2026. [USENIX paper](https://www.usenix.org/conference/osdi26/presentation/chaudhry).

[7] M. L. Weitzman, “Optimal Search for the Best Alternative,” *Econometrica*, 47(3), 641–654, 1979. [doi:10.2307/1910412](https://doi.org/10.2307/1910412).

[8] H. Beyhaghi and L. Cai, “Recent Developments in Pandora’s Box Problem: Variants and Applications,” *ACM SIGecom Exchanges*, 21(1), 20–34, 2023. [doi:10.1145/3699814.3699817](https://doi.org/10.1145/3699814.3699817).

[9] R. T. Rockafellar and S. Uryasev, “Optimization of Conditional Value-at-Risk,” *The Journal of Risk*, 2(3), 21–41, 2000. [doi:10.21314/JOR.2000.038](https://doi.org/10.21314/JOR.2000.038).

[10] J. Simon, “Open Agent Traces: Synthetic Multi-Agent Workflow Datasets,” Hugging Face dataset card, 2026. [Dataset and documentation](https://huggingface.co/datasets/juliensimon/open-agent-traces).

[11] D. Duplyakin, A. Uta, A. Maricq, and R. Ricci, “In Datacenter Performance, The Only Constant Is Change,” in *Proceedings of the 20th IEEE/ACM International Symposium on Cluster, Cloud and Internet Computing*, 2020. [Project page](https://www.flux.utah.edu/paper/duplyakin-ccgrid20).

[12] FinOps Foundation, *FinOps Open Cost and Usage Specification (FOCUS), Version 1.4*, 2026. [Specification overview](https://focus.finops.org/what-is-focus/).

[13] CloudSim Plus, “NetworkTopology API, Version 8.0.0,” [API documentation](https://javadoc.io/static/org.cloudsimplus/cloudsim-plus/8.0.0/org/cloudsimplus/network/topologies/NetworkTopology.html); “Simulation API, Version 8.0.0,” [API documentation](https://www.javadoc.io/static/org.cloudsimplus/cloudsim-plus/8.0.0/org/cloudsimplus/core/Simulation.html).
