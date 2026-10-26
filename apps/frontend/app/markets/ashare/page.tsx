"use client";

/**
 * 旧路径兼容：`/markets/ashare` → `/markets/cn`。
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AshareRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/markets/cn");
  }, [router]);
  return (
    <main style={{ padding: 24, color: "var(--muted, #888)" }}>
      已迁移至 <a href="/markets/cn">/markets/cn</a>…
    </main>
  );
}
