import { useEffect, useState } from "react";
import { ErroApi, api } from "../../api";
import type { Categoria, Competencia } from "../../tipos";
import Botao from "../../ui/Botao";
import Folha from "../../ui/Folha";
import { mensagem } from "../candidaturas/comum";

type Props = { aberta: boolean; categorias: Categoria[]; aoFechar: () => void; aoCriar: (c: Competencia) => void };

const PESOS = [
  { n: 1, nome: "aparece às vezes" },
  { n: 2, nome: "comum" },
  { n: 3, nome: "quase toda vaga pede" },
];

/** "Nova competência" (decisão 10): nome, categoria e peso; grava no competencias.yaml. */
export default function FolhaNova({ aberta, categorias, aoFechar, aoCriar }: Props) {
  const [nome, setNome] = useState("");
  const [categoria, setCategoria] = useState("");
  const [peso, setPeso] = useState(2);
  const [erroNome, setErroNome] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    if (!aberta) return;
    setNome(""); setCategoria(categorias[0]?.id ?? ""); setPeso(2); setErroNome(null); setErro(null);
  }, [aberta]); // eslint-disable-line react-hooks/exhaustive-deps

  async function adicionar() {
    setOcupado(true);
    setErro(null);
    try {
      aoCriar(await api.post<Competencia>("/api/competencias", { nome: nome.trim(), categoria: categoria || categorias[0]?.id, peso }));
    } catch (e) {
      if (e instanceof ErroApi && e.status === 409) setErroNome(mensagem(e));
      else setErro(mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  const pode = !!nome.trim() && !!(categoria || categorias[0]);
  return (
    <Folha aberta={aberta} titulo="Nova competência" largura={640} aoFechar={() => { if (!ocupado) aoFechar(); }}
      rodape={
        <>
          <span className="meta dica-folha">sem custo: não chama o modelo</span>
          <Botao tipo="fant" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
          <Botao tipo="prim" onClick={adicionar} ocupado={ocupado} disabled={!pode}>Adicionar</Botao>
        </>
      }>
      <p className="sub-folha">Entra no competencias.yaml. O nível você declara depois, com evidência.</p>
      <form className="form-folha" onSubmit={(e) => { e.preventDefault(); if (pode && !ocupado) adicionar(); }}>
        <div className="campos-2">
          <label className="rotulo-campo" htmlFor="nova-nome">Nome
            <input id="nova-nome" className="campo" value={nome} autoComplete="off" aria-invalid={!!erroNome}
              aria-describedby={erroNome ? "nova-nome-erro" : undefined}
              onChange={(e) => { setNome(e.target.value); setErroNome(null); }} />
            {erroNome && <small id="nova-nome-erro" className="erro-campo">{erroNome}</small>}
          </label>
          <label className="rotulo-campo" htmlFor="nova-cat">Categoria
            <select id="nova-cat" className="campo" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
              {categorias.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
            </select>
          </label>
        </div>
        <fieldset className="rotulo-campo">
          <legend>Peso nas vagas</legend>
          <div className="segmentado pesos" role="group" aria-label="Peso nas vagas">
            {PESOS.map((p) => (
              <button key={p.n} type="button" aria-pressed={p.n === peso} onClick={() => setPeso(p.n)}>
                <b>{p.n}</b> {p.nome}
              </button>
            ))}
          </div>
          <small className="meta ajuda-peso">Ordena a lista: as de peso 3 aparecem primeiro em cada grupo.</small>
        </fieldset>
        <button type="submit" hidden />
      </form>
      {erro && <div className="erro-folha" role="alert">{erro}</div>}
    </Folha>
  );
}
