import createNextIntlPlugin from "next-intl/plugin";

/** @type {import('next').NextConfig} */
const apiOrigin = process.env.MEMORY_SPARK_API_ORIGIN || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // Browser discovery can spend 45s per provider, then widen an exact year
  // to its decade. Next's 30s default disconnects these valid searches.
  experimental: { proxyTimeout: 240_000 },
  async rewrites() {
    return [
      {
        source: "/api/v1/memoir/:path*",
        destination: `${apiOrigin}/api/v1/memoir/:path*`,
      },
      {
        source: "/api/v1/memoir",
        destination: `${apiOrigin}/api/v1/memoir`,
      },
      // The existing browser client uses /static/* URLs. Keep that public
      // contract while Next serves the same files from its public directory.
      {
        source: "/static/:path*",
        destination: "/:path*",
      },
    ];
  },
};

const withNextIntl = createNextIntlPlugin("./i18n/request.js");

export default withNextIntl(nextConfig);
