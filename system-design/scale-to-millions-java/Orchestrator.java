import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * Boots every service that makes up the system, each as its own OS process
 * communicating over localhost HTTP - the same shape as separate machines
 * talking over a network, just without needing Docker or multiple hosts.
 *
 * Unlike the Python version, Java needs a compile step first: this class
 * shells out to `javac` to build every service into an out/ directory before
 * spawning any of them, so `java Orchestrator.java` is still a single
 * command to get the whole system running - run it from inside the java/
 * directory.
 */
public class Orchestrator {
    static final Path BASE_DIR = Paths.get("").toAbsolutePath();
    static final Path SERVICES_DIR = BASE_DIR.resolve("services");
    static final Path OUT_DIR = BASE_DIR.resolve("out");

    static final String[] COLORS = {
            "\033[36m", "\033[35m", "\033[33m", "\033[32m", "\033[34m", "\033[91m", "\033[92m", "\033[94m", "\033[95m"
    };
    static final String RESET = "\033[0m";

    record ServiceSpec(String name, String className, Map<String, String> env) {
    }

    static final List<ServiceSpec> SERVICES = List.of(
            new ServiceSpec("cache", "services.CacheService", Map.of("PORT", "4000")),
            new ServiceSpec("db-primary", "services.DbPrimary", Map.of("PORT", "5000")),
            new ServiceSpec("db-replica", "services.DbReplica",
                    Map.of("PORT", "5001", "PRIMARY_URL", "http://127.0.0.1:5000")),
            new ServiceSpec("queue", "services.QueueService", Map.of("PORT", "6060")),
            new ServiceSpec("cdn", "services.Cdn", Map.of("PORT", "7000")),
            new ServiceSpec("worker", "services.Worker", Map.of("QUEUE_URL", "http://127.0.0.1:6060")),
            new ServiceSpec("web-1", "services.Web", Map.of(
                    "PORT", "3001", "NODE_ID", "web-1",
                    "CACHE_URL", "http://127.0.0.1:4000", "PRIMARY_URL", "http://127.0.0.1:5000",
                    "REPLICA_URL", "http://127.0.0.1:5001", "QUEUE_URL", "http://127.0.0.1:6060",
                    "CDN_URL", "http://127.0.0.1:7000"
            )),
            new ServiceSpec("web-2", "services.Web", Map.of(
                    "PORT", "3002", "NODE_ID", "web-2",
                    "CACHE_URL", "http://127.0.0.1:4000", "PRIMARY_URL", "http://127.0.0.1:5000",
                    "REPLICA_URL", "http://127.0.0.1:5001", "QUEUE_URL", "http://127.0.0.1:6060",
                    "CDN_URL", "http://127.0.0.1:7000"
            )),
            new ServiceSpec("load-balancer", "services.LoadBalancer", Map.of(
                    "PORT", "3000", "BACKENDS", "http://127.0.0.1:3001,http://127.0.0.1:3002"
            ))
    );

    static final List<Process> processes = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        compile();

        Runtime.getRuntime().addShutdownHook(new Thread(Orchestrator::shutdown));

        for (int i = 0; i < SERVICES.size(); i++) {
            ServiceSpec spec = SERVICES.get(i);
            String color = COLORS[i % COLORS.length];

            ProcessBuilder pb = new ProcessBuilder("java", "-cp", OUT_DIR.toString(), spec.className())
                    .directory(SERVICES_DIR.toFile())
                    .redirectErrorStream(true);
            pb.environment().putAll(spec.env());

            Process proc = pb.start();
            processes.add(proc);
            streamOutput(spec.name(), color, proc);
        }

        System.out.println("\nAll services starting. Once ready, open http://127.0.0.1:3000\n");

        for (Process proc : processes) {
            proc.waitFor();
        }
    }

    private static void compile() throws IOException, InterruptedException {
        List<String> sources;
        try (Stream<Path> walk = Files.walk(BASE_DIR)) {
            sources = walk.filter(p -> p.toString().endsWith(".java"))
                    .map(Path::toString)
                    .collect(Collectors.toList());
        }

        Files.createDirectories(OUT_DIR);

        List<String> command = new ArrayList<>(List.of("javac", "-d", OUT_DIR.toString()));
        command.addAll(sources);

        Process javac = new ProcessBuilder(command).inheritIO().start();
        if (javac.waitFor() != 0) {
            throw new IllegalStateException("javac failed - see compiler output above");
        }
    }

    private static void streamOutput(String name, String color, Process proc) {
        Thread thread = new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(proc.getInputStream()))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!line.isBlank()) {
                        System.out.println(color + "[" + name + "]" + RESET + " " + line);
                    }
                }
            } catch (IOException ignored) {
                // process ended; stream closed
            }
        });
        thread.setDaemon(true);
        thread.start();
    }

    private static void shutdown() {
        System.out.println("\nShutting down all services...");
        for (Process proc : processes) {
            proc.destroy();
        }
        for (Process proc : processes) {
            try {
                proc.waitFor();
            } catch (InterruptedException ignored) {
            }
        }
    }
}
