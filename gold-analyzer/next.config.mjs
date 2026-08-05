/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Ce dossier est volontairement hors des workspaces yarn du monorepo Expo :
  // il s'installe et se déploie seul.
  outputFileTracingRoot: import.meta.dirname,
};

export default nextConfig;
