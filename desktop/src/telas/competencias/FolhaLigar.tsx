import { useEffect, useState } from "react";
import { ErroApi, api } from "../../api";
import type { Candidato, DetalheCompetencia } from "../../tipos";
import Botao from "../../ui/Botao";
import { avisar } from "../../ui/Aviso";
import Folha from "../../ui/Folha";
import { mensagem } from "../candidaturas/comum";
import { LinhaCandidato } from "./Documento";

type Props = {
  aberta: boolean;
  detalhe: DetalheCompetencia;
  aoFechar: () => void;
  /** um fato foi ligado: o que está atrás da folha recarrega */
  aoLigar: () => void;
};

type Item = Candidato & { ligado: boolean };
type Ligado = { nota: string; block_id: string; texto: string; tem_metrica: boolean };

/** "Ligar um fato" (decisão 2): candidatos do vault no topo; ligado vira "✓ Ligado" e desce; ou cola a referência.
 *  A força padrão é média (2); muda no "⋯" da evidência. */
export default function FolhaLigar({ aberta, detalhe, aoFechar, aoLigar }: Props) {
  const c = detalhe.competencia;
  const [itens, setItens] = useState<Item[]>([]);
  const [ref, setRef] = useState("");
  const [erroRef, setErroRef] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  // a lista é uma foto de quando a folha abriu: o recarregar atrás tira o ligado dos candidatos, e aqui ele fica no fim
  useEffect(() => {
    if (!aberta) return;
    setItens(detalhe.candidatos.map((x) => ({ ...x, ligado: false })));
    setRef("");
    setErroRef(null);
  }, [aberta]); // eslint-disable-line react-hooks/exhaustive-deps

  async function ligar(referencia: string): Promise<Ligado> {
    const r = await api.post<Ligado>(
      `/api/competencias/${c.slug}/evidencias`, { referencia, forca: 2 });
    aoLigar();
    return r;
  }

  async function ligarCandidato(item: Item) {
    try {
      await ligar(item.referencia);
      setItens((xs) => [...xs.filter((x) => x.referencia !== item.referencia), { ...item, ligado: true }]);
    } catch (e) {
      avisar(mensagem(e));
    }
  }

  async function colar() {
    setOcupado(true);
    setErroRef(null);
    try {
      const r = await ligar(ref.trim());
      const referencia = `${r.nota}#${r.block_id}`;
      setItens((xs) => [...xs.filter((x) => x.referencia !== referencia),
        { referencia, block_id: r.block_id, texto: r.texto, tem_metrica: !!r.tem_metrica, ligado: true }]);
      setRef("");
    } catch (e) {
      setErroRef(e instanceof ErroApi && e.status === 422 && /não está no índice/.test(e.message)
        ? "Não achei esse bloco no vault" : mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Folha aberta={aberta} titulo="Ligar um fato" largura={640} aoFechar={aoFechar}
      rodape={
        <>
          <span className="meta dica-folha">sem custo: não chama o modelo</span>
          <Botao tipo="fant" onClick={aoFechar}>Fechar</Botao>
        </>
      }>
      <p className="sub-folha">{c.nome} · fatos do vault que provam esta competência</p>
      {itens.length > 0 ? (
        <div className="bloco-folha">
          <span className="rotulo-campo">O vault parece ter isto</span>
          <ul className="evids">
            {itens.map((x) => <LinhaCandidato key={x.referencia} c={x} ligado={x.ligado} aoLigar={() => ligarCandidato(x)} />)}
          </ul>
        </div>
      ) : (
        <p>O vault não sugeriu nada para esta competência. Cole a referência de uma nota.</p>
      )}
      <form className="rotulo-campo" onSubmit={(e) => { e.preventDefault(); if (ref.trim() && !ocupado) colar(); }}>
        <label htmlFor="ligar-ref">Colar referência</label>
        <div className="linha-colar">
          <input id="ligar-ref" className="campo" value={ref} placeholder="nota.md#^bloco" autoComplete="off"
            aria-invalid={!!erroRef} aria-describedby={erroRef ? "ligar-ref-erro" : undefined}
            onChange={(e) => { setRef(e.target.value); setErroRef(null); }} />
          <Botao submit ocupado={ocupado} disabled={!ref.trim()}>Ligar</Botao>
        </div>
        {erroRef && <small id="ligar-ref-erro" className="erro-campo">{erroRef}</small>}
      </form>
    </Folha>
  );
}
