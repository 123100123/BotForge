import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Self-contained server (.next/standalone/server.js) for the Docker image in frontend/Dockerfile.
  output: "standalone",
};

export default nextConfig;
