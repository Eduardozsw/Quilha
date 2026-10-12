import { useEffect, useRef, useState } from "react";
import { ErroApi, api } from "../../api";
import type { DetalheCompetencia, Recusa } from "../../tipos";
import Botao from "../../ui/Botao";
import Folha from "../../ui/Folha";
import { mensagem } from "../candidaturas/comum";
import Medidor from "./Medidor";
import { plural } from "./comum";

export type Rascunho = { nivel: number; justificativa: string };

type Props = {
  aberta: boolean;
  detalhe: DetalheCompetencia;
  niveis: Record<string, string>;
  /** nível e justificativa guardados na ida para "Ligar um fato" */
  rascunho: Rascunho | null;
  aoFechar: () => void;
  aoGravar: (nivel: number) => void;
  aoLigarFato: (r: Rascunho) => void;
  /** a gravação recusou (o vault mudou): o detalhe recarrega para a recusa sair da regra atual */
  aoRecarregar: () => void;
};

/** "Mudar nível" (decisão 1): os 5 níveis, a justificativa e a recusa antes de gravar, com a mesma regra da gravação. */
export default function FolhaNivel({ aberta, detalhe, niveis, rascunho, aoFechar, aoGravar, aoLigarFato, aoRecarregar }: Props) {
  const c = detalhe.competencia;
  const [nivel, setNivel] = useState(1);
  const [justificativa, setJustificativa] = useState("");
  const [recusaGravar, setRecusaGravar] = useState<Recusa>(null);
  const [ocupado, setOcupado] = useState(false);
  const opcoes = useRef<HTMLDivElement>(null);
  const campo = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!aberta) return;
    setNivel(rascunho?.nivel ?? c.nivel ?? 1);
    setJustificativa(rascunho?.justificativa ?? c.justificativa ?? "");
    setRecusaGravar(null);
  }, [aberta]); // eslint-disable-line react-hooks/exhaustive-deps

  const recusa = recusaGravar ?? detalhe.recusas[String(nivel)] ?? null;
  const n = detalhe.evidencias.length;

  function escolher(novo: number) {
    setNivel(novo);
    setRecusaGravar(null);
  }

  function teclado(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const novo = Math.min(4, Math.max(0, nivel + (e.key === "ArrowDown" ? 1 : -1)));
      escolher(novo);
      opcoes.current?.querySelectorAll<HTMLElement>("[role=radio]")[novo]?.focus();
    } else if (e.key === "Enter") {
      e.preventDefault();
      campo.current?.focus();
    }
  }

  async function gravar() {
    setOcupado(true);
    try {
      await api.post(`/api/competencias/${c.slug}/nivel`, { nivel, justificativa: justificativa.trim() });
      aoGravar(nivel);
    } catch (e) {
      // corrida: a evidência mudou depois que a folha abriu; o texto fica e a recusa aparece na mesma caixa
      if (e instanceof ErroApi && e.status === 422) {
        setRecusaGravar({ titulo: `Nível ${nivel} não foi gravado`, texto: mensagem(e) });
        aoRecarregar();
      } else setRecusaGravar({ titulo: "Não deu para gravar", texto: mensagem(e) });
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Folha aberta={aberta} titulo={c.nivel === null ? "Declarar nível" : "Mudar nível"} largura={640}
      aoFechar={() => { if (!ocupado) aoFechar(); }}
      rodape={
        <>
          <span className="meta dica-folha">sem custo: não chama o modelo</span>
          <Botao tipo="fant" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
          <Botao tipo="prim" onClick={gravar} ocupado={ocupado} disabled={!!recusa || !justificativa.trim()}>Gravar nível</Botao>
        </>
      }>
      <p className="sub-folha">{c.nome} · peso {c.peso} · {n === 0 ? "nenhuma evidência" : plural(n, "evidência", "evidências")}</p>
      <div className="niveis" role="radiogroup" aria-label="Nível" ref={opcoes} onKeyDown={teclado}>
        {[0, 1, 2, 3, 4].map((k) => (
          <button key={k} role="radio" aria-checked={k === nivel} tabIndex={k === nivel ? 0 : -1}
            className="opcao-nivel" onClick={() => escolher(k)}>
            <Medidor nivel={k} grupo="sustenta" />
            <b>Nível {k}</b>
            <span>{niveis[String(k)] ?? ""}</span>
          </button>
        ))}
      </div>
      <label className="rotulo-campo" htmlFor="nivel-just">
        <span>Justificativa <small className="meta">· é o que você vai repetir na entrevista</small></span>
        <textarea id="nivel-just" ref={campo} className="campo" rows={2} value={justificativa}
          onChange={(e) => setJustificativa(e.target.value)} />
      </label>
      {recusa && (
        <div className="caixa-recusa" role="alert">
          <b>{recusa.titulo}</b>
          <p>{recusa.texto}</p>
          <Botao onClick={() => aoLigarFato({ nivel, justificativa })}>Ligar um fato</Botao>
        </div>
      )}
    </Folha>
  );
}
