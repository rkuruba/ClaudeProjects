package services;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Primary database (Chapter 1: "Database replication" - master node).
 * Accepts ALL writes. Every write is appended to a write-ahead log (WAL) that
 * the replica polls, exactly like Postgres/MySQL streaming replication - just
 * implemented over plain HTTP instead of a binary replication protocol.
 */
public class DbPrimary {
    static final int PORT = Integer.parseInt(System.getenv().getOrDefault("PORT", "5000"));

    static final ReentrantLock lock = new ReentrantLock();
    static final List<Map<String, Object>> users = new ArrayList<>();
    static int nextId = 1;
    static final List<Map<String, Object>> wal = new ArrayList<>(); // {seq, type, row, ts}
    static int seq = 0;

    public static void main(String[] args) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", PORT), 0);
        server.createContext("/", DbPrimary::handle);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("[db-primary] listening on :" + PORT);
    }

    private static void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();

        if (method.equals("GET") && path.equals("/health")) {
            HttpUtil.sendJson(exchange, 200, Map.of("ok", true));
            return;
        }

        if (method.equals("GET") && path.equals("/users")) {
            lock.lock();
            try {
                HttpUtil.sendJson(exchange, 200, new ArrayList<>(users));
            } finally {
                lock.unlock();
            }
            return;
        }

        if (method.equals("GET") && path.equals("/wal")) {
            int since = Integer.parseInt(HttpUtil.queryParam(exchange.getRequestURI(), "since", "0"));
            lock.lock();
            try {
                List<Map<String, Object>> result = new ArrayList<>();
                for (Map<String, Object> entry : wal) {
                    if (((Number) entry.get("seq")).intValue() > since) result.add(entry);
                }
                HttpUtil.sendJson(exchange, 200, result);
            } finally {
                lock.unlock();
            }
            return;
        }

        if (method.equals("POST") && path.equals("/users")) {
            Map<String, Object> body = HttpUtil.readJsonBody(exchange);
            Object name = body.get("name");
            if (name == null || name.toString().isBlank()) {
                HttpUtil.sendJson(exchange, 400, Map.of("error", "name is required"));
                return;
            }

            Map<String, Object> row;
            int currentSeq;
            lock.lock();
            try {
                row = new LinkedHashMap<>();
                row.put("id", nextId);
                row.put("name", name);
                row.put("createdAt", Instant.now().toString());
                nextId++;
                users.add(row);
                seq++;
                Map<String, Object> walEntry = new LinkedHashMap<>();
                walEntry.put("seq", seq);
                walEntry.put("type", "insert");
                walEntry.put("row", row);
                walEntry.put("ts", System.currentTimeMillis() / 1000.0);
                wal.add(walEntry);
                currentSeq = seq;
            } finally {
                lock.unlock();
            }

            System.out.println("[db-primary] WRITE user#" + row.get("id") + " \"" + row.get("name")
                    + "\" (wal seq=" + currentSeq + ")");
            HttpUtil.sendJson(exchange, 201, row);
            return;
        }

        HttpUtil.sendJson(exchange, 404, Map.of("error", "not found"));
    }
}
