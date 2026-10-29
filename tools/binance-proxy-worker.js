// Cloudflare Worker: a minimal read-only reverse proxy for Binance PUBLIC market data.
// Deploy it like your Telegram worker, then in .env set
//   BINANCE_BASES=https://<your-worker>.workers.dev
//   BINANCE_FAPI_BASES=https://<your-worker>.workers.dev
// Only a few GET endpoints are allowed, so it cannot be abused as an open proxy.
// NOTE: Binance may still refuse some provider IP ranges; if `python cli.py check` still shows
// HTTP 451, use BINANCE_PROXY with a proxy/VPN running on your computer instead.
const ALLOWED = {
  "/api/v3/klines": "https://data-api.binance.vision",
  "/api/v3/ping": "https://data-api.binance.vision",
  "/api/v3/time": "https://data-api.binance.vision",
  "/fapi/v1/fundingRate": "https://fapi.binance.com",
  "/fapi/v1/premiumIndex": "https://fapi.binance.com",
};

export default {
  async fetch(request) {
    if (request.method !== "GET") return new Response("method not allowed", { status: 405 });
    const url = new URL(request.url);
    const origin = ALLOWED[url.pathname];
    if (!origin) return new Response("not found", { status: 404 });
    const upstream = await fetch(origin + url.pathname + url.search, {
      headers: { "User-Agent": "Mozilla/5.0", Accept: "application/json" },
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") || "application/json" },
    });
  },
};
