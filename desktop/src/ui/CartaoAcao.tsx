import type { ReactNode } from "react";
import Botao from "./Botao";

type Props = {
  icone: ReactNode;
  titulo: ReactNode;
  meta?: ReactNode;
  acao?: { rotulo: string; tipo?: "prim" | "sec"; onClick: () => void; ocupado?: boolean; desabilitada?: boolean };
};

/** Cartão de ação: quadrado de ícone 36, título 14,5/500, metadado e um botão. Um só primário por área. */
export default function CartaoAcao({ icone, titulo, meta, acao }: Props) {
  return (
    <div className="cartao-acao">
      <span className="ic" aria-hidden>{icone}</span>
      <div className="tx">
        <b>{titulo}</b>
        {meta && <span>{meta}</span>}
      </div>
      {acao && (
        <Botao tipo={acao.tipo ?? "sec"} onClick={acao.onClick} ocupado={acao.ocupado} disabled={acao.desabilitada}>
          {acao.rotulo}
        </Botao>
      )}
    </div>
  );
}
