import React from "react";
import styles from "./auth.module.css";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <main className={styles.container}>
      <div className={styles.card}>
        <div className={styles.glow} />
        <div className={styles.content}>{children}</div>
      </div>
    </main>
  );
}
