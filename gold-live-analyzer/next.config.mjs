/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `ws` is used only inside Node runtime route handlers (the cTrader bridge).
  serverExternalPackages: ['ws'],
};

export default nextConfig;
