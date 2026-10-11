package services;

import java.util.Map;

/**
 * Async worker (Chapter 1: "Message queue" - the consumer side).
 * Polls the queue and processes jobs off the request path. Simulates sending
 * a "welcome email" whenever a new user signs up - the canonical
 * message-queue example from the book.
 */
public class Worker {
    static final String QUEUE_URL = System.getenv().getOrDefault("QUEUE_URL", "http://127.0.0.1:6060");
    static final String TOPIC = "user.created";

    public static void main(String[] args) throws InterruptedException {
        System.out.println("[worker] polling " + QUEUE_URL + " for topic \"" + TOPIC + "\"");
        while (true) {
            poll();
            Thread.sleep(500);
        }
    }

    @SuppressWarnings("unchecked")
    private static void poll() {
        try {
            HttpUtil.HttpResult result = HttpUtil.httpJson("GET", QUEUE_URL + "/consume?topic=" + TOPIC, null, 2000);
            if (result.status() != 200 || result.body() == null) return;

            Map<String, Object> job = (Map<String, Object>) result.body();
            Map<String, Object> payload = (Map<String, Object>) job.get("payload");
            System.out.println("[worker] processing job: " + payload);
            Thread.sleep(800); // simulate slow work, e.g. calling a third-party email API
            System.out.println("[worker] sent welcome email to \"" + payload.get("name") + "\"");
        } catch (Exception e) {
            // queue unreachable this cycle; retry next tick
        }
    }
}
