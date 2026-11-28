package edu.project.hybrid;

import org.cloudsimplus.brokers.DatacenterBrokerSimple;
import org.cloudsimplus.cloudlets.CloudletSimple;
import org.cloudsimplus.core.CloudSimPlus;
import org.cloudsimplus.datacenters.DatacenterSimple;
import org.cloudsimplus.hosts.Host;
import org.cloudsimplus.hosts.HostSimple;
import org.cloudsimplus.network.topologies.BriteNetworkTopology;
import org.cloudsimplus.resources.Pe;
import org.cloudsimplus.resources.PeSimple;
import org.cloudsimplus.vms.Vm;
import org.cloudsimplus.vms.VmSimple;

import java.io.BufferedWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Random;

/**
 * First CloudSim Plus experiment for a three-stage AI workflow on a full-mesh
 * hybrid cloud. Each episode samples a new link state (a piecewise-constant
 * network epoch), enumerates all 3^3 placements, and evaluates compute cost,
 * transfer charges, latency, and SLO risk together.
 *
 * CloudSim Plus runs calibration tasks on each resource class. The placement
 * objective is calculated from those measured service times plus a sampled
 * network epoch. CloudSim's Brite topology represents the baseline full-mesh
 * connectivity; sampled epoch metrics are evaluated in the placement model.
 * This first version models network dynamics between workflow episodes; it
 * does not yet simulate packet queues or within-episode link transitions.
 */
public final class WorkflowPlacementSimulation {
    private static final String[] PROVIDERS = {"OnPrem", "CloudA", "CloudB"};
    private static final String[] STAGES = {"Planner", "Researcher", "Writer"};
    private static final double[] COST_PER_STAGE = {3.2, 4.0, 5.4};
    private static final double[] VM_MIPS = {850, 1100, 1500};
    private static final long[] STAGE_MI = {48, 60, 42};
    private static final double[] DATA_MB = {2.0, 1.5};
    private static final double[] EGRESS_PER_MB = {0.08, 0.12, 0.10};
    private static final double DEADLINE_MS = 250;
    private static final double MIN_RELIABILITY = 0.80;
    private static final double FAILURE_PENALTY = 20.0;
    private static final double[] GOOD_PROB = {0.82, 0.78, 0.90};
    private static final double[] BAD_MULTIPLIER = {1.75, 1.85, 1.55};
    private static final double[] BAD_AVAILABILITY = {0.91, 0.89, 0.95};

    private record Link(double bandwidthMbps, double latencyMs, double goodProbability,
                        double egressPerMb) {}
    private record Score(int[] mapping, double cost, double latencyMs, double reliability,
                         boolean failed, double objective) {}

    private WorkflowPlacementSimulation() {}

    public static void main(String[] args) throws Exception {
        int episodes = args.length > 0 ? Integer.parseInt(args[0]) : 500;
        long seed = args.length > 1 ? Long.parseLong(args[1]) : 6111L;
        Path output = Path.of(args.length > 2 ? args[2] : "results/cloudsim_fullmesh/episodes.csv");
        Files.createDirectories(output.getParent());
        Random rng = new Random(seed);
        double[] serviceMs = calibrateCloudSim();

        try (BufferedWriter out = Files.newBufferedWriter(output)) {
            out.write("episode,placement,compute_cost,network_cost,total_cost,latency_ms,reliability,slo_violation,risk_adjusted_objective,selected_placement\n");
            double costSum = 0, latencySum = 0;
            int failCount = 0;
            for (int e = 0; e < episodes; e++) {
                Link[][] links = sampleFullMesh(rng);
                boolean[][] states = new boolean[STAGES.length][PROVIDERS.length];
                for (int s = 0; s < STAGES.length; s++) for (int p = 0; p < PROVIDERS.length; p++)
                    states[s][p] = rng.nextDouble() < GOOD_PROB[p];
                List<Score> candidates = enumerate(links, serviceMs, states);
                Score chosen = candidates.stream().min((a, b) -> Double.compare(a.objective, b.objective)).orElseThrow();
                for (Score s : candidates) {
                    // Preserve the full assignment-level data for later plots and analysis.
                    out.write(String.format(Locale.ROOT, "%d,%s,%.5f,%.5f,%.5f,%.5f,%.6f,%d,%.5f,%s%n",
                        e, mappingName(s.mapping), computeCost(s.mapping), networkCost(s.mapping, links),
                        s.cost, s.latencyMs, s.reliability, s.failed ? 1 : 0, s.objective, mappingName(chosen.mapping)));
                }
                costSum += chosen.cost;
                latencySum += chosen.latencyMs;
                if (chosen.failed) failCount++;
            }
            System.out.printf(Locale.ROOT,
                "CloudSim Plus 8.0.0 calibration (3 stages): %s%nEpisodes=%d, seed=%d, placements/episode=27%nMean selected cost=%.4f, mean latency=%.2f ms, observed SLO violations=%.3f%%%nCSV=%s%n",
                format(serviceMs), episodes, seed, costSum / episodes, latencySum / episodes,
                100.0 * failCount / episodes, output.toAbsolutePath());
        }
    }

    /** Run real CloudSim Plus Cloudlets on provider-specific VM classes. */
    private static double[] calibrateCloudSim() {
        double[] timeMs = new double[PROVIDERS.length];
        for (int c = 0; c < PROVIDERS.length; c++) {
            CloudSimPlus simulation = new CloudSimPlus();
            List<Pe> pes = List.of(new PeSimple(VM_MIPS[c]));
            List<DatacenterSimple> datacenters = new ArrayList<>();
            for (int p = 0; p < PROVIDERS.length; p++) {
                Host host = new HostSimple(8192, 100_000, 1_000_000, pes);
                datacenters.add(new DatacenterSimple(simulation, List.of(host)));
            }
            BriteNetworkTopology topology = new BriteNetworkTopology();
            topology.addLink(datacenters.get(0), datacenters.get(1), 300, .024);
            topology.addLink(datacenters.get(0), datacenters.get(2), 180, .038);
            topology.addLink(datacenters.get(1), datacenters.get(2), 220, .018);
            simulation.setNetworkTopology(topology);
            DatacenterBrokerSimple broker = new DatacenterBrokerSimple(simulation);
            Vm vm = new VmSimple(VM_MIPS[c], 1).setRam(2048).setBw(10_000).setSize(20_000);
            List<CloudletSimple> cloudlets = new ArrayList<>();
            for (long length : STAGE_MI) {
                cloudlets.add(new CloudletSimple(length, 1));
            }
            broker.submitVmList(List.of(vm));
            broker.submitCloudletList(cloudlets);
            simulation.start();
            timeMs[c] = broker.getCloudletFinishedList().stream().mapToDouble(cl -> cl.getActualCpuTime() * 1000.0).sum() / STAGES.length;
        }
        return timeMs;
    }

    /** Complete undirected graph; sample each pair's condition for this epoch. */
    private static Link[][] sampleFullMesh(Random rng) {
        Link[][] links = new Link[3][3];
        double[][] bw = {{0, 300, 180}, {300, 0, 220}, {180, 220, 0}};
        double[][] lat = {{0, 24, 38}, {24, 0, 18}, {38, 18, 0}};
        double[][] pGood = {{1, .90, .83}, {.90, 1, .92}, {.83, .92, 1}};
        for (int i = 0; i < 3; i++) for (int j = i + 1; j < 3; j++) {
            boolean good = rng.nextDouble() < pGood[i][j];
            double sampledBw = bw[i][j] * (good ? 1.0 : .20);
            double sampledLat = lat[i][j] * (good ? 1.0 : 3.5);
            Link l = new Link(sampledBw, sampledLat, good ? 0.999 : .90,
                              (EGRESS_PER_MB[i] + EGRESS_PER_MB[j]) / 2.0);
            links[i][j] = l;
            links[j][i] = l;
        }
        return links;
    }

    private static List<Score> enumerate(Link[][] links, double[] serviceMs, boolean[][] states) {
        List<Score> result = new ArrayList<>(27);
        for (int a = 0; a < 3; a++) for (int b = 0; b < 3; b++) for (int c = 0; c < 3; c++) {
            int[] map = {a, b, c};
            double cost = computeCost(map) + networkCost(map, links);
            double latency = 0, reliability = 1;
            for (int s = 0; s < 3; s++) {
                int provider = map[s];
                boolean good = states[s][provider];
                // Calibrated CloudSim service time is a workload-specific baseline;
                // provider state represents runtime contention/availability variation.
                latency += serviceMs[provider] * STAGE_MI[s] / (double) sum(STAGE_MI)
                    * (good ? 1.0 : BAD_MULTIPLIER[provider]);
                reliability *= good ? .995 : BAD_AVAILABILITY[provider];
            }
            for (int edge = 0; edge < 2; edge++) if (map[edge] != map[edge + 1]) {
                Link l = links[map[edge]][map[edge + 1]];
                double serialization = DATA_MB[edge] * 8_000.0 / l.bandwidthMbps;
                latency += l.latencyMs + serialization;
                reliability *= l.goodProbability;
            }
            boolean failed = latency > DEADLINE_MS || reliability < MIN_RELIABILITY;
            double allIn = cost + (failed ? FAILURE_PENALTY : 0);
            // Select using the prior model; the sampled state above is used only
            // to record the realized outcome, avoiding clairvoyant placement.
            double objective = expectedObjective(map, links, serviceMs);
            result.add(new Score(map, allIn, latency, reliability, failed, objective));
        }
        return result;
    }

    /** Exact 2^3 state expectation for the chosen three mapped stage-resource pairs. */
    private static double expectedObjective(int[] map, Link[][] links, double[] serviceMs) {
        double base = computeCost(map) + networkCost(map, links);
        double mean = 0, failureProbability = 0;
        double[] values = new double[8], probabilities = new double[8];
        for (int mask = 0; mask < 8; mask++) {
            double p = 1, latency = 0, reliability = 1;
            for (int s = 0; s < 3; s++) {
                int provider = map[s];
                boolean good = (mask & (1 << s)) != 0;
                p *= good ? GOOD_PROB[provider] : 1 - GOOD_PROB[provider];
                latency += serviceMs[provider] * STAGE_MI[s] / (double) sum(STAGE_MI)
                    * (good ? 1 : BAD_MULTIPLIER[provider]);
                reliability *= good ? .995 : BAD_AVAILABILITY[provider];
            }
            for (int edge = 0; edge < 2; edge++) if (map[edge] != map[edge + 1]) {
                Link l = links[map[edge]][map[edge + 1]];
                latency += l.latencyMs + DATA_MB[edge] * 8_000.0 / l.bandwidthMbps;
                reliability *= l.goodProbability;
            }
            boolean failed = latency > DEADLINE_MS || reliability < MIN_RELIABILITY;
            values[mask] = base + (failed ? FAILURE_PENALTY : 0);
            probabilities[mask] = p;
            mean += p * values[mask];
            if (failed) failureProbability += p;
        }
        Integer[] order = {0,1,2,3,4,5,6,7};
        java.util.Arrays.sort(order, (i, j) -> Double.compare(values[j], values[i]));
        double left = .10, tail = 0;
        for (int i : order) {
            double take = Math.min(left, probabilities[i]);
            tail += take * values[i];
            left -= take;
            if (left <= 1e-12) break;
        }
        double cvar = tail / .10;
        return mean + .5 * (cvar - mean) + 1000 * Math.max(0, failureProbability - .10);
    }

    private static double computeCost(int[] map) {
        double cost = 0;
        for (int p : map) cost += COST_PER_STAGE[p];
        return cost;
    }

    private static double networkCost(int[] map, Link[][] links) {
        double cost = 0;
        for (int e = 0; e < 2; e++) if (map[e] != map[e + 1]) {
            cost += DATA_MB[e] * links[map[e]][map[e + 1]].egressPerMb;
        }
        return cost;
    }

    private static String mappingName(int[] map) {
        return STAGES[0] + "=" + PROVIDERS[map[0]] + ";" + STAGES[1] + "=" + PROVIDERS[map[1]] + ";" + STAGES[2] + "=" + PROVIDERS[map[2]];
    }
    private static long sum(long[] values) { long s = 0; for (long v : values) s += v; return s; }
    private static String format(double[] values) { return String.format(Locale.ROOT, "[%.2f, %.2f, %.2f] ms", values[0], values[1], values[2]); }
}
