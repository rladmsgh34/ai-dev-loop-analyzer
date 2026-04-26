import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // 부모 디렉토리(gwangcheon-shop)에도 pnpm-lock.yaml이 있어 Turbopack의 workspace 추론이
  // 잘못 잡힘 → '@/' alias가 엉뚱한 src/lib을 가리키게 됨. web/ 자체를 root로 명시.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
