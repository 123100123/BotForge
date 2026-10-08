import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Development only: proxy /api/* to the local backend so NEXT_PUBLIC_API_BASE_URL=/api works in
  // `npm run dev` and the session cookie stays same-origin. In production Caddy does this.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    return [{ source: "/api/:path*", destination: "http://localhost:8000/:path*" }];
  },
  // Development only: gzip on the /api proxy buffers the agent run's text/event-stream until it closes,
  // so live run events never reach the browser. Production is unaffected (Caddy routes /api directly).
  compress: process.env.NODE_ENV !== "development",
  // Self-contained server (.next/standalone/server.js) for the Docker image in frontend/Dockerfile.
  output: "standalone",
};

export default nextConfig;
