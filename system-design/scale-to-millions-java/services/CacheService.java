package services;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Cache tier (Chapter 1: "Cache").
 * Stands in for Redis/Memcached: a fast in-memory key-value store, separate
 * from the web tier, so multiple stateless web servers share one cache
 * instead of each holding its own.
 */
public class CacheService {
    static final int PORT = Integer.parseInt(System.getenv().getOrDefault("PORT", "4000"));

    private record Entry(Object value, double expiresAt) {
    }

    static final Map<String, Entry> store = new HashMap<>();
    static int hits = 0;
    static int misses = 0;
    static final ReentrantLock lock = new ReentrantLock();

    public static void main(String[] args) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", PORT), 0);
        server.createContext("/", CacheService::handle);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("[cache] listening on :" + PORT);
    }

    private static void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();

        if (method.equals("GET") && path.equals("/health")) {
            HttpUtil.sendJson(exchange, 200, Map.of("ok", true));
            return;
        }

        if (method.equals("GET") && path.equals("/stats")) {
            lock.lock();
            try {
                Map<String, Object> stats = new LinkedHashMap<>();
                stats.put("hits", hits);
                stats.put("misses", misses);
                stats.put("keys", store.size());
                HttpUtil.sendJson(exchange, 200, stats);
            } finally {
                lock.unlock();
            }
            return;
        }

        if (method.equals("GET") && path.startsWith("/cache/")) {
            String key = path.substring("/cache/".length());
            lock.lock();
            try {
                Entry entry = store.get(key);
                if (entry == null || entry.expiresAt() < System.currentTimeMillis() / 1000.0) {
                    store.remove(key);
                    misses++;
                    HttpUtil.sendJson(exchange, 404, Map.of("hit", false));
                    return;
                }
                hits++;
                Map<String, Object> resp = new LinkedHashMap<>();
                resp.put("hit", true);
                resp.put("value", entry.value());
                HttpUtil.sendJson(exchange, 200, resp);
            } finally {
                lock.unlock();
            }
            return;
        }

        if (method.equals("PUT") && path.startsWith("/cache/")) {
            String key = path.substring("/cache/".length());
            Map<String, Object> body = HttpUtil.readJsonBody(exchange);
            double ttlMs = body.containsKey("ttlMs") ? ((Number) body.get("ttlMs")).doubleValue() : 10000;
            lock.lock();
            try {
                store.put(key, new Entry(body.get("value"), System.currentTimeMillis() / 1000.0 + ttlMs / 1000));
            } finally {
                lock.unlock();
            }
            HttpUtil.sendJson(exchange, 200, Map.of("ok", true));
            return;
        }

        if (method.equals("DELETE") && path.startsWith("/cache/")) {
            String key = path.substring("/cache/".length());
            lock.lock();
            try {
                store.remove(key);
            } finally {
                lock.unlock();
            }
            HttpUtil.sendJson(exchange, 200, Map.of("ok", true));
            return;
        }

        HttpUtil.sendJson(exchange, 404, Map.of("error", "not found"));
    }
}
