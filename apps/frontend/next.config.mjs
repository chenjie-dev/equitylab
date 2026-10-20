/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  transpilePackages: ["@equitylab/qdb"],
};

export default nextConfig;
