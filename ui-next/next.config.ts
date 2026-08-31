import type { NextConfig } from "next";

const API_INTERNAL = process.env.API_URL_INTERNAL ?? "http://localhost:8001";

const nextConfig: NextConfig = {
  // Proxy /api/* to FastAPI so the browser only ever talks to its own origin.
  //
  // This matters for auth: the session cookie is httpOnly and SameSite=Lax, so
  // a cross-origin XHR would neither send nor accept it. In production nginx
  // already routes /api/* to the api container and Next never sees these
  // requests, so this rewrite only takes effect in local development — where
  // it makes dev behave exactly like prod instead of needing CORS credentials.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_INTERNAL}/api/:path*` },
    ];
  },
};

export default nextConfig;
