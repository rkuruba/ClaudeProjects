package services;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;
import java.util.concurrent.Executors;

/**
 * CDN (Chapter 1: "Content delivery network").
 * Serves static assets (CSS/JS) from a server dedicated to that job, with
 * long-lived cache headers, so the web tier never has to handle requests for
 * files that never change per-request. In production this would be a real
 * CDN edge node; here it's simulated as its own local process on its own port.
 */
public class Cdn {
    static final int PORT = Integer.parseInt(System.getenv().getOrDefault("PORT", "7000"));

    // Orchestrator.java launches every service with its working directory set
    // to services/ - one level up lands on this project's root, where its
    // own copy of public-cdn/ lives (this project is self-contained, same as
    // the Node and Python versions each keep their own).
    static final Path PUBLIC_DIR = Paths.get("").toAbsolutePath()
            .getParent().resolve("public-cdn").normalize();

    public static void main(String[] args) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", PORT), 0);
        server.createContext("/", Cdn::handle);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("[cdn] listening on :" + PORT);
    }

    private static void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();

        if (path.equals("/health")) {
            HttpUtil.sendJson(exchange, 200, Map.of("ok", true));
            return;
        }

        if (path.startsWith("/static/")) {
            path = path.substring("/static".length());
        }

        String relative = URLDecoder.decode(path, StandardCharsets.UTF_8);
        Path file = PUBLIC_DIR.resolve(relative.replaceFirst("^/", "")).normalize();

        exchange.getResponseHeaders().add("Cache-Control", "public, max-age=31536000, immutable");
        exchange.getResponseHeaders().add("x-served-by", "cdn");

        if (!file.startsWith(PUBLIC_DIR) || !Files.isRegularFile(file)) {
            exchange.sendResponseHeaders(404, -1);
            exchange.close();
            return;
        }

        byte[] body = Files.readAllBytes(file);
        String contentType = Files.probeContentType(file);
        exchange.getResponseHeaders().add("Content-Type", contentType != null ? contentType : "application/octet-stream");
        exchange.sendResponseHeaders(200, body.length);
        try (var os = exchange.getResponseBody()) {
            os.write(body);
        }
    }
}
