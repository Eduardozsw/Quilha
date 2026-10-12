import type { ReactNode } from "react";

/** Selo de estado: ok (acento), at (pede decisão), er (recusa/falha), ne (neutro). */
export default function Selo({ tom, children }: { tom: "ok" | "at" | "er" | "ne"; children: ReactNode }) {
  return <span className={`selo ${tom}`}>{children}</span>;
}
