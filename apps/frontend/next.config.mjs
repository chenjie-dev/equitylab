/** @type {import('next').NextConfig} */
const gateway =
  process.env.GATEWAY_URL?.replace(/\/$/, "") ||
  process.env.NEXT_PUBLIC_GATEWAY_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:3000";

const nextConfig = {
  output: "standalone",
  transpilePackages: ["@equitylab/qdb"],
  // 直连 :3001 排障时，把 /api/* 转到 gateway（鉴权挂点仍在网关）。
  // 正式入口请用 :3000，浏览器不经过本 rewrite。
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${gateway}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
