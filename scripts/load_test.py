"""Bounded read-only staging probe. Does not create users or send emails."""

import asyncio, os, time, statistics, collections
import httpx


async def main():
    base = os.environ["TARGET_URL"].rstrip("/")
    if not base.startswith(("http://localhost:", "http://127.0.0.1:", "https://")):
        raise SystemExit("Use localhost or an HTTPS staging endpoint you control.")
    concurrency = min(20, max(1, int(os.getenv("CONCURRENCY", "5"))))
    count = min(1000, max(1, int(os.getenv("REQUESTS", "100"))))
    limit = asyncio.Semaphore(concurrency)
    latencies = []
    statuses = collections.Counter()
    async with httpx.AsyncClient(timeout=10) as client:

        async def request():
            async with limit:
                start = time.monotonic()
                try:
                    r = await client.get(base + "/api/config")
                    statuses[r.status_code] += 1
                except httpx.HTTPError:
                    statuses["network_error"] += 1
                latencies.append((time.monotonic() - start) * 1000)

        await asyncio.gather(*(request() for _ in range(count)))
    ordered = sorted(latencies)
    print(
        {
            "requests": count,
            "concurrency": concurrency,
            "statuses": dict(statuses),
            "median_ms": round(statistics.median(ordered), 2),
            "p95_ms": round(
                ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2
            ),
        }
    )
    if any(isinstance(k, int) and k >= 500 or k == "network_error" for k in statuses):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
