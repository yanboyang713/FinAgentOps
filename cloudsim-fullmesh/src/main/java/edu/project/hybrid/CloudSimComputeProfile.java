package edu.project.hybrid;

import org.cloudsimplus.brokers.DatacenterBrokerSimple;
import org.cloudsimplus.cloudlets.CloudletSimple;
import org.cloudsimplus.core.CloudSimPlus;
import org.cloudsimplus.datacenters.DatacenterSimple;
import org.cloudsimplus.hosts.HostSimple;
import org.cloudsimplus.resources.PeSimple;
import org.cloudsimplus.vms.VmSimple;

import java.io.BufferedWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Locale;

/** Measures normalized execution throughput of each illustrative site with CloudSim Plus. */
public final class CloudSimComputeProfile {
    private static final String[] SITES = {"OnPrem", "CloudA", "CloudB"};
    private static final double[] MIPS = {850, 1100, 1500};
    private static final long CALIBRATION_MI = 10_000;

    private CloudSimComputeProfile() {}

    public static void main(String[] args) throws Exception {
        Path output = Path.of(args.length == 0 ? "compute_profile.csv" : args[0]);
        if (output.getParent() != null) Files.createDirectories(output.getParent());
        double[] effectiveMips = new double[SITES.length];
        double[] elapsedMs = new double[SITES.length];
        for (int i = 0; i < SITES.length; i++) {
            CloudSimPlus simulation = new CloudSimPlus();
            var host = new HostSimple(4096, 10_000, 100_000,
                List.of(new PeSimple(MIPS[i])));
            new DatacenterSimple(simulation, List.of(host));
            var broker = new DatacenterBrokerSimple(simulation);
            var vm = new VmSimple(MIPS[i], 1).setRam(1024).setBw(1000).setSize(10_000);
            var cloudlet = new CloudletSimple(CALIBRATION_MI, 1);
            broker.submitVmList(List.of(vm));
            broker.submitCloudletList(List.of(cloudlet));
            simulation.start();
            double cpuSeconds = broker.getCloudletFinishedList().get(0).getActualCpuTime();
            elapsedMs[i] = cpuSeconds * 1000.0;
            effectiveMips[i] = CALIBRATION_MI / cpuSeconds;
        }
        double reference = effectiveMips[1];
        try (BufferedWriter writer = Files.newBufferedWriter(output)) {
            writer.write("site,vm_mips,cloudsim_elapsed_ms,effective_mips,speed_factor,cloudsim_version\n");
            for (int i = 0; i < SITES.length; i++) {
                writer.write(String.format(Locale.ROOT, "%s,%.3f,%.6f,%.6f,%.8f,8.0.0%n",
                    SITES[i], MIPS[i], elapsedMs[i], effectiveMips[i], effectiveMips[i] / reference));
            }
        }
        System.out.printf(Locale.ROOT, "CloudSim Plus compute profile: %s%n", output.toAbsolutePath());
    }
}
