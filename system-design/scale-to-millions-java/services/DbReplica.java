package services;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Timer;
import java.util.TimerTask;
import java.util.concurrent.Executors;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Read replica (Chapter 1: "Database replication" - slave node).
 * Serves ALL reads so the primary is freed up to handle writes. Polls the
 * primary's WAL and applies entries with a deliberate delay to make
 * replication lag visible - a write to the primary is not guaranteed to be
 * immediately visible on a replica, exactly as the book calls out.
 */
public class DbReplica {
    static final int PORT = Integer.parseInt(System.getenv().getOrDefault("PORT", "5001"));
    static final String PRIMARY_URL = System.getenv().getOrDefault("PRIMARY_URL", "http://127.0.0.1:5000");
    static final int REPLICATION_LAG_MS = Integer.parseInt(System.getenv().getOrDefault("REPLICATION_LAG_MS", "1200"));

    static final ReentrantLock lock = new ReentrantLock();
    static final List<Map<String, Object>> users = new ArrayList<>();
    static volatile int lastAppliedSeq = 0;
    static final Timer timer = new Timer(true); // daemon: shouldn't keep the JVM alive on its own

    public static void main(String[] args) throws IOException {
        Thread poller = new Thread(DbReplica::pollPrimary, "wal-poller");
        poller.setDaemon(true);
        poller.start();

        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", PORT), 0);
        server.createContext("/", DbReplica::handle);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("[db-replica] listening on :" + PORT + ", tailing " + PRIMARY_URL);
    }

    @SuppressWarnings("unchecked")
    private static void applyEntry(Map<String, Object> entry) {
        if ("insert".equals(entry.get("type"))) {
            Map<String, Object> row = (Map<String, Object>) entry.get("row");
            lock.lock();
            try {
                users.add(row);
            } finally {
                lock.unlock();
            }
            System.out.println("[db-replica] applied WAL seq=" + entry.get("seq") + " -> user#" + row.get("id")
                    + " (lag=" + REPLICATION_LAG_MS + "ms)");
        }
    }

    @SuppressWarnings("unchecked")
    private static void pollPrimary() {
        while (true) {
            try {
                HttpUtil.HttpResult result = HttpUtil.httpJson(
                        "GET", PRIMARY_URL + "/wal?since=" + lastAppliedSeq, null, 2000);
                if (result.status() == 200 && result.body() != null) {
                    for (Object o : (List<Object>) result.body()) {
                        Map<String, Object> entry = (Map<String, Object>) o;
                        int entrySeq = ((Number) entry.get("seq")).intValue();
                        timer.schedule(new TimerTask() {
                            @Override
                            public void run() {
                                applyEntry(entry);
                            }
                        }, REPLICATION_LAG_MS);
                        lastAppliedSeq = Math.max(lastAppliedSeq, entrySeq);
                    }
                }
            } catch (Exception e) {
                // primary unreachable this cycle; retry next tick
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException ignored) {
            }
        }
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

        if (method.equals("GET") && path.equals("/status")) {
            Map<String, Object> status = new LinkedHashMap<>();
            status.put("lastAppliedSeq", lastAppliedSeq);
            status.put("replicationLagMs", REPLICATION_LAG_MS);
            HttpUtil.sendJson(exchange, 200, status);
            return;
        }

        HttpUtil.sendJson(exchange, 404, Map.of("error", "not found"));
    }
}
