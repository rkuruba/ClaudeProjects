package services;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Message queue (Chapter 1: "Message queue").
 * Decouples slow/non-critical work (e.g. sending a welcome email) from the
 * request path. The web tier publishes a job and responds to the user
 * immediately; a separate worker process consumes and processes it later.
 */
public class QueueService {
    static final int PORT = Integer.parseInt(System.getenv().getOrDefault("PORT", "6060"));

    static final ReentrantLock lock = new ReentrantLock();
    static final Map<String, Deque<Map<String, Object>>> queues = new HashMap<>(); // topic -> jobs

    public static void main(String[] args) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", PORT), 0);
        server.createContext("/", QueueService::handle);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("[queue] listening on :" + PORT);
    }

    private static void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();

        if (method.equals("GET") && path.equals("/health")) {
            HttpUtil.sendJson(exchange, 200, Map.of("ok", true));
            return;
        }

        if (method.equals("GET") && path.equals("/consume")) {
            String topic = HttpUtil.queryParam(exchange.getRequestURI(), "topic", null);
            Map<String, Object> job;
            lock.lock();
            try {
                Deque<Map<String, Object>> jobs = queues.get(topic);
                if (jobs == null || jobs.isEmpty()) {
                    exchange.sendResponseHeaders(204, -1);
                    exchange.close();
                    return;
                }
                job = jobs.pollFirst();
            } finally {
                lock.unlock();
            }
            HttpUtil.sendJson(exchange, 200, job);
            return;
        }

        if (method.equals("POST") && path.equals("/publish")) {
            Map<String, Object> body = HttpUtil.readJsonBody(exchange);
            Object topic = body.get("topic");
            Object payload = body.get("payload");
            if (topic == null) {
                HttpUtil.sendJson(exchange, 400, Map.of("error", "topic is required"));
                return;
            }

            int depth;
            lock.lock();
            try {
                Deque<Map<String, Object>> jobs = queues.computeIfAbsent(topic.toString(), k -> new ArrayDeque<>());
                Map<String, Object> job = new LinkedHashMap<>();
                job.put("payload", payload);
                jobs.addLast(job);
                depth = jobs.size();
            } finally {
                lock.unlock();
            }

            System.out.println("[queue] published to \"" + topic + "\": " + payload);
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("ok", true);
            resp.put("queueDepth", depth);
            HttpUtil.sendJson(exchange, 202, resp);
            return;
        }

        HttpUtil.sendJson(exchange, 404, Map.of("error", "not found"));
    }
}
