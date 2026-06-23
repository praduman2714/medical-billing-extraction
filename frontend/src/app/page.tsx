"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { authClient } from "@/lib/auth-client";

export default function Home() {
  const router = useRouter();
  const { data: session, isPending } = authClient.useSession();

  useEffect(() => {
    if (!isPending) {
      if (session) {
        router.push("/dashboard");
      } else {
        router.push("/auth/login");
      }
    }
  }, [session, isPending, router]);

  return (
    <div style={{ 
      display: "flex", 
      alignItems: "center", 
      justifyContent: "center", 
      minHeight: "100vh", 
      background: "var(--background)",
      fontFamily: "var(--font-sans)"
    }}>
      <p style={{ color: "var(--foreground-muted)", fontSize: "16px" }}>Loading platform...</p>
    </div>
  );
}

