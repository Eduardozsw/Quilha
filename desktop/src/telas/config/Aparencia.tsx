import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { aplicarMovimento, lerMovimento, type Movimento } from "../../ui/movimento";
import Segmentado from "../../ui/Segmentado";
import { aplicarTema, lerTema, type Tema } from "../../ui/tema";
import { Divisor, Linha, Painel } from "./pecas";

const TEMAS: { id: Tema; nome: string; icone: LucideIcon }[] = [
  { id: "sistema", nome: "Sistema", icone: Monitor },
  { id: "claro", nome: "Claro", icone: Sun },
  { id: "escuro", nome: "Escuro", icone: Moon },
];

/** Miniatura do tema com as cores fixas de cada um (é uma amostra, não segue o tema atual). */
function Miniatura({ tema }: { tema: Tema }) {
  const metade = (lado: "claro" | "escuro") => (
    <span className={`mini ${lado}`}><i className="lat" /><i className="jan"><b /></i></span>
  );
  return (
    <span className="miniatura" aria-hidden>
      {tema === "escuro" ? metade("escuro") : metade("claro")}
      {tema === "sistema" && metade("escuro")}
    </span>
  );
}

/** Configurações → Aparência: tema e reduzir movimento. Os dois valem neste computador (localStorage). */
export default function Aparencia() {
  const [tema, setTema] = useState<Tema>(lerTema);
  const [movimento, setMovimento] = useState<Movimento>(lerMovimento);

  return (
    <Painel titulo="Aparência" descricao="Como o Quilha aparece neste computador.">
      <div className="config-campo">
        <div className="rotulo" id="rotulo-tema">Tema</div>
        <div className="config-temas" role="radiogroup" aria-labelledby="rotulo-tema">
          {TEMAS.map(({ id, nome, icone: Icone }) => (
            <button key={id} role="radio" aria-checked={tema === id} className="config-tema"
              onClick={() => { setTema(id); aplicarTema(id); }}>
              <Miniatura tema={id} />
              <span className="nome"><Icone size={16} strokeWidth={1.75} aria-hidden />{nome}</span>
            </button>
          ))}
        </div>
        <p className="ajuda">Sistema segue o claro ou o escuro do seu computador e troca sozinho quando ele troca.</p>
      </div>
      <Divisor />
      <Linha titulo="Reduzir movimento"
        descricao="Troca as animações por mudanças instantâneas. Por padrão, segue o ajuste do seu sistema. Sempre: as telas trocam sem animação.">
        <Segmentado rotulo="Reduzir movimento" valor={movimento}
          aoMudar={(m) => { setMovimento(m); aplicarMovimento(m); }}
          opcoes={[{ id: "sistema", nome: "Seguir o sistema" }, { id: "sempre", nome: "Sempre" }, { id: "nunca", nome: "Nunca" }]} />
      </Linha>
    </Painel>
  );
}
