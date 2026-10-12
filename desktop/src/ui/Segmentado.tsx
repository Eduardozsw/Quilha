type Props<T extends string> = {
  opcoes: { id: T; nome: string; contagem?: number }[];
  valor: T;
  aoMudar: (id: T) => void;
  rotulo: string;
};

/** Filtro segmentado: trilho `--suave`, opção ativa em `--card` com sombra mínima; contagem opcional. */
export default function Segmentado<T extends string>({ opcoes, valor, aoMudar, rotulo }: Props<T>) {
  return (
    <div className="segmentado" role="group" aria-label={rotulo}>
      {opcoes.map((o) => (
        <button key={o.id} aria-pressed={o.id === valor} onClick={() => aoMudar(o.id)}>
          {o.nome}
          {o.contagem !== undefined && <span className="contagem tabular">{o.contagem}</span>}
        </button>
      ))}
    </div>
  );
}
