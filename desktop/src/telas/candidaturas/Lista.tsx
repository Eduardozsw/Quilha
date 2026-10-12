import { useState } from "react";
import { ChevronRight, Inbox } from "lucide-react";
import type { Candidatura } from "../../tipos";
import ListaSelecao from "../../ui/ListaSelecao";
import Selo from "../../ui/Selo";
import { ENCERRADAS, ETAPAS, SELO, metaDa, nomeDa, ordenar, plural } from "./comum";

type Props = {
  candidaturas: Candidatura[];
  selecionada: number | null;
  aoSelecionar: (id: number) => void;
  aTriar: number;
  aoTriar: () => void;
  /** a triagem é feita pelo Jev, não pelo LLM do usuário */
  porJev?: boolean;
};

const NOME = new Map(ETAPAS.map((e) => [e.id as string, e.nome]));

function Item({ c }: { c: Candidatura }) {
  return (
    <span className="tx">
      <b>{nomeDa(c)}</b>
      <span className="meta">{metaDa(c)}</span>
    </span>
  );
}

/** Lista por etapa: caixa "A triar" no topo, etapas na ordem de `ETAPAS` e "Encerradas" recolhido no fim. */
export default function Lista({ candidaturas, selecionada, aoSelecionar, aTriar, aoTriar, porJev = false }: Props) {
  const encerradas = candidaturas.filter((c) => ENCERRADAS.includes(c.status));
  const ativas = candidaturas.filter((c) => !ENCERRADAS.includes(c.status)).sort(ordenar);
  const [abertas, setAbertas] = useState(() => encerradas.some((c) => c.id === selecionada));
  const sel = selecionada === null ? null : String(selecionada);

  return (
    <div className="coluna-lista lista-cand">
      {aTriar > 0 && (
        <button className="caixa-triar" onClick={aoTriar}>
          <Inbox size={18} strokeWidth={1.5} aria-hidden />
          <span className="tx">
            <b>A triar</b>
            <span>{plural(aTriar, "e-mail sem candidatura", "e-mails sem candidatura")} · {porJev ? "triagem pelo Jev" : "usa seu LLM"}</span>
          </span>
          <span className="n tabular">{aTriar}</span>
        </button>
      )}
      {ativas.length > 0 && (
        <ListaSelecao
          rotulo="Candidaturas"
          itens={ativas}
          chave={(c) => String(c.id)}
          selecionado={sel}
          aoSelecionar={(k) => aoSelecionar(Number(k))}
          grupo={(c) => NOME.get(c.status) ?? ""}
          render={(c) => <Item c={c} />}
        />
      )}
      {encerradas.length > 0 && (
        <div className="encerradas">
          <button className="alternar-encerradas" aria-expanded={abertas} onClick={() => setAbertas((a) => !a)}>
            <ChevronRight size={14} strokeWidth={2} aria-hidden />
            Encerradas <span className="tabular">{encerradas.length}</span>
          </button>
          {abertas && (
            <ListaSelecao
              rotulo="Candidaturas encerradas"
              itens={encerradas}
              chave={(c) => String(c.id)}
              selecionado={sel}
              aoSelecionar={(k) => aoSelecionar(Number(k))}
              render={(c) => (
                <>
                  <Item c={c} />
                  <Selo tom={SELO[c.status].tom}>{SELO[c.status].nome}</Selo>
                </>
              )}
            />
          )}
        </div>
      )}
    </div>
  );
}
