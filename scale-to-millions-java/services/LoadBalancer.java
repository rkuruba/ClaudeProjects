package services;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Load balancer (Chapter 1: "Load balancer").
 * Distributes incoming traffic round-robin across N stateless web servers,
 * and stops routing to any server that fails its health check.
 */
public class LoadBalancer {
    static final int PORT = Integer.parseInt(System.getenv().getOrDefault("PORT", "3000"));
    static final String[] BACKEND_URLS = System.getenv()
            .getOrDefault("BACKENDS", "http://127.0.0.1:3001,http://127.0.0.1:3002").split(",");

    static final Set<String> HOP_BY_HOP_HEADERS =
            Set.of("connection", "transfer-encoding", "keep-alive", "proxy-authenticate", "content-length");

    private static final class Backend {
        final String url;
        volatile boolean healthy = true;

        Backend(String url) {
            this.url = url;
        }
    }

    static final List<Backend> backends = new ArrayList<>();

    static {
        for (String url : BACKEND_URLS) backends.add(new Backend(url));
    }

    static final ReentrantLock lock = new ReentrantLock();
    static int nextIndex = 0;
    static final HttpClient client = HttpClient.newHttpClient();

    public static void main(String[] args) throws IOException {
        Thread healthChecker = new Thread(LoadBalancer::checkHealth, "health-check");
        healthChecker.setDaemon(true);
        healthChecker.start();

        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", PORT), 0);
        server.createContext("/", LoadBalancer::proxy);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("[load-balancer] listening on :" + PORT + ", backends: " + String.join(", ", BACKEND_URLS));
    }

    private static Backend pickBackend() {
        lock.lock();
        try {
            List<Backend> healthy = backends.stream().filter(b -> b.healthy).toList();
            if (healthy.isEmpty()) return null;
            Backend backend = healthy.get(nextIndex % healthy.size());
            nextIndex++;
            return backend;
        } finally {
            lock.unlock();
        }
    }

    private static void checkHealth() {
        while (true) {
            for (Backend backend : backends) {
                try {
                    HttpUtil.HttpResult result = HttpUtil.httpJson("GET", backend.url + "/health", null, 1500);
                    backend.healthy = result.status() == 200;
                } catch (Exception e) {
                    backend.healthy = false;
                }
            }
            try {
                Thread.sleep(5000);
            } catch (InterruptedException ignored) {
            }
        }
    }

    private static void proxy(HttpExchange exchange) throws IOException {
        Backend backend = pickBackend();
        if (backend == null) {
            HttpUtil.sendJson(exchange, 503, Map.of("error", "No healthy backends available"));
            return;
        }

        byte[] requestBody = exchange.getRequestBody().readAllBytes();
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(backend.url + exchange.getRequestURI()))
                .timeout(Duration.ofSeconds(5));
        for (Map.Entry<String, List<String>> header : exchange.getRequestHeaders().entrySet()) {
            String key = header.getKey().toLowerCase();
            if (key.equals("host") || HOP_BY_HOP_HEADERS.contains(key)) continue;
            for (String value : header.getValue()) {
                try {
                    builder.header(header.getKey(), value);
                } catch (IllegalArgumentException ignored) {
                    // HttpClient forbids setting a handful of restricted headers; skip those
                }
            }
        }
        builder.method(exchange.getRequestMethod(), requestBody.length > 0
                ? HttpRequest.BodyPublishers.ofByteArray(requestBody)
                : HttpRequest.BodyPublishers.noBody());

        try {
            HttpResponse<byte[]> response = client.send(builder.build(), HttpResponse.BodyHandlers.ofByteArray());
            for (Map.Entry<String, List<String>> header : response.headers().map().entrySet()) {
                if (HOP_BY_HOP_HEADERS.contains(header.getKey().toLowerCase())) continue;
                for (String value : header.getValue()) {
                    exchange.getResponseHeaders().add(header.getKey(), value);
                }
            }
            exchange.getResponseHeaders().add("x-load-balancer", "round-robin");
            byte[] payload = response.body();
            exchange.sendResponseHeaders(response.statusCode(), payload.length == 0 ? -1 : payload.length);
            try (var os = exchange.getResponseBody()) {
                os.write(payload);
            }
        } catch (Exception e) {
            backend.healthy = false;
            HttpUtil.sendJson(exchange, 502, Map.of("error", "Backend " + backend.url + " unreachable"));
        }
    }
}
