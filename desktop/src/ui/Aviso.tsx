import { useEffect, useState } from "react";

type Estado = { texto: string; acao?: { rotulo: string; onClick: () => void }; vez: number } | null;

let ouvinte: ((e: Estado) => void) | null = null;

/** Aviso de resultado: pílula escura no rodapé que sobe 12 px com fade e some em 2,6 s. */
export function avisar(texto: string, acao?: { rotulo: string; onClick: () => void }): void {
  ouvinte?.({ texto, acao, vez: Date.now() });
}

export default function Aviso() {
  const [estado, setEstado] = useState<Estado>(null);
  const [visivel, setVisivel] = useState(false);

  useEffect(() => {
    ouvinte = (e) => {
      setEstado(e);
      setVisivel(true);
    };
    return () => {
      ouvinte = null;
    };
  }, []);

  useEffect(() => {
    if (!estado) return;
    const t = setTimeout(() => setVisivel(false), 2600);
    return () => clearTimeout(t);
  }, [estado]);

  return (
    <div className={`aviso${visivel ? " visivel" : ""}`} role="status" aria-live="polite">
      <span>{estado?.texto}</span>
      {estado?.acao && (
        <button
          onClick={() => {
            setVisivel(false);
            estado.acao!.onClick();
          }}
          tabIndex={visivel ? 0 : -1}
        >
          {estado.acao.rotulo}
        </button>
      )}
    </div>
  );
}
