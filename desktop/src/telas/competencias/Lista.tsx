import { Plus } from "lucide-react";
import type { Competencia } from "../../tipos";
import ListaSelecao from "../../ui/ListaSelecao";
import Medidor from "./Medidor";
import { GRUPOS, grupo } from "./comum";

type Props = {
  competencias: Competencia[];
  selecionada: string | null;
  aoSelecionar: (slug: string) => void;
  aoNova: () => void;
};

const NOME = new Map(GRUPOS.map((g) => [g.id as string, g.nome]));

/** A ordem da tela: os três grupos e, dentro de cada um, a ordem da API (peso primeiro). */
export function ordenadas(lista: Competencia[]): Competencia[] {
  return GRUPOS.flatMap((g) => lista.filter((c) => grupo(c) === g.id));
}

/** Lista agrupada (Sustentam o currículo, Falta evidência, Sem nível) com o medidor; ↑/↓ andam na lista. */
export default function Lista({ competencias, selecionada, aoSelecionar, aoNova }: Props) {
  const itens = ordenadas(competencias);

  function teclado(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const i = itens.findIndex((c) => c.slug === selecionada);
    const proxima = itens[Math.min(itens.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
    if (!proxima) return;
    aoSelecionar(proxima.slug);
    e.currentTarget.querySelector<HTMLElement>(`[data-chave="${CSS.escape(proxima.slug)}"]`)?.focus();
  }

  return (
    <div className="coluna-lista lista-comp" onKeyDown={teclado}>
      <ListaSelecao
        rotulo="Competências"
        itens={itens}
        chave={(c) => c.slug}
        selecionado={selecionada}
        aoSelecionar={aoSelecionar}
        grupo={(c) => NOME.get(grupo(c)) ?? ""}
        render={(c) => (
          <>
            <span className="tx"><b>{c.nome}</b></span>
            <Medidor nivel={c.nivel} grupo={grupo(c)} />
          </>
        )}
      />
      <button className="nova-comp" onClick={aoNova}>
        <Plus size={14} strokeWidth={1.75} aria-hidden /> Nova competência
      </button>
    </div>
  );
}
