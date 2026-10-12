import type { ReactNode } from "react";

type Props = { icone: ReactNode; rotulo?: string; titulo: string; texto: string; acoes?: ReactNode };

/** Estado vazio: é o tutorial de verdade da tela. Diz o que ela faz e oferece uma ação (quadro "Estados vazios"). */
export default function Vazio({ icone, rotulo, titulo, texto, acoes }: Props) {
  return (
    <div className="vazio-v3">
      {rotulo && <div className="rotulo-vazio">{rotulo}</div>}
      <span className="ic-vazio" aria-hidden>{icone}</span>
      <h2 className="titulo-vazio">{titulo}</h2>
      <p>{texto}</p>
      {acoes && <div className="acoes-vazio">{acoes}</div>}
    </div>
  );
}
