// Async worker (Chapter 1: "Message queue" - the consumer side).
// Polls the queue and processes jobs off the request path. Here it simulates
// sending a "welcome email" whenever a new user signs up - the kind of slow,
// non-critical task the book uses as the canonical message-queue example.
const QUEUE_URL = process.env.QUEUE_URL || 'http://localhost:6060';
const TOPIC = 'user.created';

async function poll() {
  try {
    const res = await fetch(`${QUEUE_URL}/consume?topic=${TOPIC}`, {
      signal: AbortSignal.timeout(2000),
    });
    if (res.status === 204) return;
    const job = await res.json();

    console.log(`[worker] processing job: ${JSON.stringify(job.payload)}`);
    // Simulate slow work (e.g. calling a third-party email API).
    await new Promise((resolve) => setTimeout(resolve, 800));
    console.log(`[worker] sent welcome email to "${job.payload.name}"`);
  } catch {
    // Queue unreachable this cycle; retry on next poll.
  }
}

console.log(`[worker] polling ${QUEUE_URL} for topic "${TOPIC}"`);
setInterval(poll, 500);
