import { useLayoutEffect, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, ArrowUpRight, Link2 } from "lucide-react";
import { abrirExterno } from "../comum";
import type { FonteLinha } from "../tipos";

type Props = { id: string; fonte: FonteLinha | undefined; ancora: HTMLElement; folha: HTMLElement | null; aoEntrar?: () => void; aoSair?: () => void };

/** Balão "Vem do seu vault": ao lado da folha, alinhado com a linha em foco. Fixo na janela (portal),
 *  porque a mesa rola e recortaria o que flutua dentro dela. */
export default function Procedencia({ id, fonte, ancora, folha, aoEntrar, aoSair }: Props) {
  const [pos, setPos] = useState<CSSProperties>({ visibility: "hidden" });

  useLayoutEffect(() => {
    function medir() {
      const r = ancora.getBoundingClientRect();
      const f = (folha ?? ancora).getBoundingClientRect();
      const largura = 280;
      // ao lado da folha, sem cobrir o fato que a pessoa está conferindo: à direita se couber; senão à esquerda
      // (por cima da lista); só sem espaço dos dois lados encosta na direita da janela por cima da folha
      const esquerda = f.right + 12 + largura <= window.innerWidth - 8 ? f.right + 12
        : f.left - 12 - largura >= 8 ? f.left - 12 - largura
        : window.innerWidth - largura - 16;
      const topo = Math.min(Math.max(8, r.top - 8), window.innerHeight - 180);
      setPos({ position: "fixed", top: topo, left: esquerda, width: largura });
    }
    medir();
    window.addEventListener("resize", medir);
    window.addEventListener("scroll", medir, true);
    return () => {
      window.removeEventListener("resize", medir);
      window.removeEventListener("scroll", medir, true);
    };
  }, [ancora, folha]);

  // o balão mora no fim do documento (portal): o Tab dentro dele volta para perto da linha de onde veio,
  // não para o fim da página
  function teclado(e: React.KeyboardEvent) {
    if (e.key !== "Tab") return;
    e.preventDefault();
    if (e.shiftKey) return ancora.focus();
    const areas = [...(folha ?? document).querySelectorAll<HTMLElement>(".area-linha")];
    (areas[areas.indexOf(ancora) + 1] ?? ancora).focus();
  }

  const fora = !fonte || !fonte.no_vault;
  return createPortal(
    <div id={id} role="dialog" aria-label={fora ? "Saiu do seu vault" : "Vem do seu vault"} className={`procedencia${fora ? " fora" : ""}`}
      style={pos} onMouseEnter={aoEntrar} onMouseLeave={aoSair} onKeyDown={teclado}>
      {fora ? (
        <>
          <p className="topo-proc"><AlertCircle size={15} strokeWidth={1.8} aria-hidden /> Saiu do seu vault</p>
          <p>Este fato não está mais no vault. A linha mostra o que foi enviado.</p>
          {fonte && <p className="ref-proc">{fonte.nota} · ^{fonte.block_id}</p>}
        </>
      ) : (
        <>
          <p className="topo-proc"><Link2 size={15} strokeWidth={1.8} aria-hidden /> Vem do seu vault</p>
          <p className="citacao-proc">“{fonte.texto}”</p>
          <p className="ref-proc">{fonte.nota} · ^{fonte.block_id}</p>
          {fonte.obsidian && (
            <button className="link-proc" onClick={() => abrirExterno(fonte.obsidian!)}>
              Abrir no Obsidian <ArrowUpRight size={14} strokeWidth={1.8} aria-hidden />
            </button>
          )}
        </>
      )}
    </div>,
    document.body,
  );
}
