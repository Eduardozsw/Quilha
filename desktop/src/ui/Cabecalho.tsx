import type { ReactNode } from "react";

type Props = {
  contexto?: ReactNode;
  titulo: ReactNode;
  /** até 3 itens; vazios somem e os demais ganham " · " entre si */
  status?: (ReactNode | null | false | undefined)[];
  acoes?: ReactNode;
};

/** Cabeçalho de tela: linha de contexto opcional, título Newsreader 34, linha de status, ações à direita. */
export default function Cabecalho({ contexto, titulo, status, acoes }: Props) {
  const itens = (status ?? []).filter((s) => s !== null && s !== false && s !== undefined && s !== "");
  return (
    <header className="cab">
      <div>
        {contexto && <div className="ctx">{contexto}</div>}
        <h1>{titulo}</h1>
        {itens.length > 0 && (
          <div className="status">
            {itens.map((s, i) => (
              <span key={i}>{i > 0 && " · "}{s}</span>
            ))}
          </div>
        )}
      </div>
      {acoes && <div className="acoes">{acoes}</div>}
    </header>
  );
}
