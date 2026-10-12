import { Check } from "lucide-react";
import Botao from "../../ui/Botao";
import type { Item } from "./comum";
import { LinhaConfirmacao } from "./Fio";

/** "Gravar este estudo?": pares rótulo/valor só de leitura, "Gravar" e "Agora não". Respondido, encolhe para
 *  uma linha ("✓ Estudo gravado · 30 min em …", "Não gravado · …", "Expirou · … não gravada"). */
export default function Confirmacao({ item, responder }: {
  item: Item & { tipo: "confirmar" }; responder: (id: string, aprovar: boolean) => void;
}) {
  if (item.resultado && item.linha) return <LinhaConfirmacao gravado={item.resultado === "gravado"} linha={item.linha} />;
  return (
    <section className="confirmacao cresce" aria-label={item.titulo}>
      <h3><Check size={15} strokeWidth={2} aria-hidden />{item.titulo}</h3>
      <dl>
        {item.campos.map((c) => (
          <div key={c.rotulo}><dt>{c.rotulo}</dt><dd>{c.valor}</dd></div>
        ))}
      </dl>
      <div className="acoes">
        <Botao tipo="prim" onClick={() => responder(item.id, true)} ocupado={item.enviando === true} textoOcupado="Gravando…">Gravar</Botao>
        <Botao onClick={() => responder(item.id, false)} disabled={item.enviando}>Agora não</Botao>
      </div>
    </section>
  );
}
