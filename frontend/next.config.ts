import type { NextConfig } from "next";

// Static export: the app is fully client-side, so the backend container serves the built files from "/" and the
// browser calls the API on the same origin (one service to deploy, no CORS).
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
