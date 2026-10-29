// Cloudflare Worker: a minimal read-only reverse proxy for Toobit PUBLIC market data.
// Deploy it, then in .env set   TOOBIT_BASES=https://<your-worker>.workers.dev
// Only a few GET endpoints are allowed, so it cannot be abused as an open proxy,
// and no API key ever passes through it (no Authorization/X-BB-APIKEY header is forwarded).
const ALLOWED = new Set([
  "/quote/v1/klines",
  "/quote/v1/ticker/price",
  "/api/v1/time",
  "/api/v1/futures/fundingRate",
  "/api/v1/futures/historyFundingRate",
]);

export default {
  async fetch(request) {
    if (request.method !== "GET") return new Response("method not allowed", { status: 405 });
    const url = new URL(request.url);
    if (!ALLOWED.has(url.pathname)) return new Response("not found", { status: 404 });
    const upstream = await fetch("https://api.toobit.com" + url.pathname + url.search, {
      headers: { "User-Agent": "Mozilla/5.0", Accept: "application/json" },
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") || "application/json" },
    });
  },
};
