import type { NextConfig } from "next";

// Same-origin proxy so the browser only ever talks to the Next server. Lets the
// app sit behind a single TLS front (Tailscale) with no CORS and no second port
// exposed. Unused when NEXT_PUBLIC_API_BASE_URL points at an absolute backend.
//
// BUILD TIME, not run time: Next resolves rewrites during `next build` and
// freezes them into .next/routes-manifest.json, so setting BACKEND_ORIGIN on
// `next start` does nothing. Set it before building, or rebuild after changing.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // deploy/pi/check.sh builds into .next-build so the live .next keeps
  // serving; deploy/pi/deploy.sh swaps it in. Unset = the default .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  reactStrictMode: true,
  poweredByHeader: false,
  rewrites: async () => [
    { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
  ],
};

export default nextConfig;
