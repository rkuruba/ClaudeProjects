package services;

import com.sun.net.httpserver.HttpExchange;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Small shared helpers so every service doesn't reimplement JSON
 * request/response plumbing on top of com.sun.net.httpserver. Standard-library
 * only - no Spring/OkHttp/Gson - so the project runs with zero Maven/Gradle
 * dependencies, the same spirit as the Python version's "zero pip install."
 */
public final class HttpUtil {
    private HttpUtil() {
    }

    private static final HttpClient CLIENT = HttpClient.newHttpClient();

    public static void sendJson(HttpExchange exchange, int status, Object payload) throws IOException {
        sendJson(exchange, status, payload, Map.of());
    }

    public static void sendJson(HttpExchange exchange, int status, Object payload, Map<String, String> extraHeaders)
            throws IOException {
        byte[] body = Json.encode(payload).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        for (Map.Entry<String, String> header : extraHeaders.entrySet()) {
            exchange.getResponseHeaders().add(header.getKey(), header.getValue());
        }
        exchange.sendResponseHeaders(status, body.length);
        try (var os = exchange.getResponseBody()) {
            os.write(body);
        }
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> readJsonBody(HttpExchange exchange) throws IOException {
        byte[] raw = exchange.getRequestBody().readAllBytes();
        if (raw.length == 0) return new LinkedHashMap<>();
        Object parsed = Json.parse(new String(raw, StandardCharsets.UTF_8));
        return parsed instanceof Map ? (Map<String, Object>) parsed : new LinkedHashMap<>();
    }

    public static String queryParam(URI uri, String key, String defaultValue) {
        String query = uri.getRawQuery();
        if (query == null) return defaultValue;
        for (String pair : query.split("&")) {
            String[] kv = pair.split("=", 2);
            if (kv[0].equals(key)) return kv.length > 1 ? kv[1] : "";
        }
        return defaultValue;
    }

    /** Mirrors Python's `http_json`: returns (status, body) for ANY status, including 4xx/5xx. */
    public record HttpResult(int status, Object body) {
    }

    public static HttpResult httpJson(String method, String url) throws IOException, InterruptedException {
        return httpJson(method, url, null, 2000);
    }

    public static HttpResult httpJson(String method, String url, Object payload) throws IOException, InterruptedException {
        return httpJson(method, url, payload, 2000);
    }

    public static HttpResult httpJson(String method, String url, Object payload, int timeoutMs)
            throws IOException, InterruptedException {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofMillis(timeoutMs));
        if (payload != null) {
            builder.header("Content-Type", "application/json")
                    .method(method, HttpRequest.BodyPublishers.ofString(Json.encode(payload)));
        } else {
            builder.method(method, HttpRequest.BodyPublishers.noBody());
        }
        HttpResponse<String> response = CLIENT.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        String body = response.body();
        Object parsed = (body == null || body.isEmpty()) ? null : Json.parse(body);
        return new HttpResult(response.statusCode(), parsed);
    }
}
