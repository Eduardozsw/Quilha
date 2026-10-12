/** Logo do Quilha (versão C, escura): linha d'água e quilha. Cores fixas da marca, iguais nos dois temas. */
export function Logo({ tamanho = 24 }: { tamanho?: number }) {
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 30 30" aria-hidden style={{ flex: "none" }}>
      <rect width="30" height="30" rx="6" fill="#2A3440" />
      <path d="M5.5 12q2.375-2 4.75 0t4.75 0t4.75 0t4.75 0" fill="none" stroke="#4FB39F" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M13.6 13.3H16.4L15.8 20.3H14.2Z" fill="#4FB39F" />
      <ellipse cx="15" cy="21" rx="3.8" ry="1.8" fill="#4FB39F" />
    </svg>
  );
}
