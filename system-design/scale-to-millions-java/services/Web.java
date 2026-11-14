package services;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;

/**
 * Stateless web tier (Chapter 1: "Stateless web tier").
 * Holds NO local state - every request can be handled by any instance, which
 * is exactly what makes horizontal scaling behind the load balancer
 * possible. All state lives in the cache and database services.
 */
public class Web {
    static final int PORT = Integer.parseInt(System.getenv().getOrDefault("PORT", "3001"));
    static final String NODE_ID = System.getenv().getOrDefault("NODE_ID", "web-" + PORT);
    static final String CACHE_URL = System.getenv().getOrDefault("CACHE_URL", "http://127.0.0.1:4000");
    static final String PRIMARY_URL = System.getenv().getOrDefault("PRIMARY_URL", "http://127.0.0.1:5000");
    static final String REPLICA_URL = System.getenv().getOrDefault("REPLICA_URL", "http://127.0.0.1:5001");
    static final String QUEUE_URL = System.getenv().getOrDefault("QUEUE_URL", "http://127.0.0.1:6060");
    static final String CDN_URL = System.getenv().getOrDefault("CDN_URL", "http://127.0.0.1:7000");

    // Orchestrator.java launches every service with its working directory set
    // to services/ - one level up lands on this project's root, where its
    // own copy of frontend/ lives (this project is self-contained, same as
    // the Node and Python versions each keep their own).
    static final Path FRONTEND_HTML = Paths.get("").toAbsolutePath()
            .getParent().resolve("frontend").resolve("index.html");

    public static void main(String[] args) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", PORT), 0);
        server.createContext("/", Web::handle);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("[web:" + NODE_ID + "] listening on :" + PORT);
    }

    private static void send(HttpExchange exchange, int status, Object payload) throws IOException {
        HttpUtil.sendJson(exchange, status, payload, Map.of("x-served-by", NODE_ID));
    }

    private static void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();

        if (method.equals("GET")) {
            if (path.equals("/health")) {
                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("ok", true);
                resp.put("node", NODE_ID);
                send(exchange, 200, resp);
                return;
            }
            if (path.equals("/config.json")) {
                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("cdnUrl", CDN_URL);
                resp.put("servedBy", NODE_ID);
                send(exchange, 200, resp);
                return;
            }
            if (path.equals("/")) {
                byte[] body = Files.readAllBytes(FRONTEND_HTML);
                exchange.getResponseHeaders().add("Content-Type", "text/html");
                exchange.getResponseHeaders().add("x-served-by", NODE_ID);
                exchange.sendResponseHeaders(200, body.length);
                try (var os = exchange.getResponseBody()) {
                    os.write(body);
                }
                return;
            }
            if (path.equals("/api/users")) {
                getUsers(exchange);
                return;
            }
            send(exchange, 404, Map.of("error", "not found"));
            return;
        }

        if (method.equals("POST") && path.equals("/api/users")) {
            createUser(exchange);
            return;
        }

        send(exchange, 404, Map.of("error", "not found"));
    }

    // Read path: cache-aside. Check cache first; on miss, read from the
    // REPLICA (never the primary) and repopulate the cache.
    @SuppressWarnings("unchecked")
    private static void getUsers(HttpExchange exchange) throws IOException {
        try {
            HttpUtil.HttpResult cacheResult = HttpUtil.httpJson("GET", CACHE_URL + "/cache/users:all");
            if (cacheResult.status() == 200) {
                Map<String, Object> cached = (Map<String, Object>) cacheResult.body();
                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("source", "cache");
                resp.put("node", NODE_ID);
                resp.put("users", cached.get("value"));
                send(exchange, 200, resp);
                return;
            }

            HttpUtil.HttpResult replicaResult = HttpUtil.httpJson("GET", REPLICA_URL + "/users");
            Object users = replicaResult.body();
            Map<String, Object> cachePayload = new LinkedHashMap<>();
            cachePayload.put("value", users);
            cachePayload.put("ttlMs", 8000);
            HttpUtil.httpJson("PUT", CACHE_URL + "/cache/users:all", cachePayload);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("source", "replica-db");
            resp.put("node", NODE_ID);
            resp.put("users", users);
            send(exchange, 200, resp);
        } catch (Exception err) {
            System.out.println("[web:" + NODE_ID + "] downstream failure on GET /api/users: " + err);
            send(exchange, 502, Map.of("error", "A downstream service is unavailable"));
        }
    }

    // Write path: always goes to the PRIMARY. Invalidates the cache so the
    // next read isn't stale, and publishes an event so slow follow-up work
    // (sending a welcome email) happens asynchronously instead of blocking
    // this response.
    @SuppressWarnings("unchecked")
    private static void createUser(HttpExchange exchange) throws IOException {
        try {
            Map<String, Object> body = HttpUtil.readJsonBody(exchange);
            HttpUtil.HttpResult primaryResult = HttpUtil.httpJson("POST", PRIMARY_URL + "/users", body);
            if (primaryResult.status() >= 400) {
                send(exchange, primaryResult.status(), primaryResult.body());
                return;
            }
            Map<String, Object> user = (Map<String, Object>) primaryResult.body();

            HttpUtil.httpJson("DELETE", CACHE_URL + "/cache/users:all");

            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("id", user.get("id"));
            payload.put("name", user.get("name"));
            Map<String, Object> job = new LinkedHashMap<>();
            job.put("topic", "user.created");
            job.put("payload", payload);
            HttpUtil.httpJson("POST", QUEUE_URL + "/publish", job);

            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("node", NODE_ID);
            resp.put("user", user);
            send(exchange, 201, resp);
        } catch (Exception err) {
            System.out.println("[web:" + NODE_ID + "] downstream failure on POST /api/users: " + err);
            send(exchange, 502, Map.of("error", "A downstream service is unavailable"));
        }
    }
}
