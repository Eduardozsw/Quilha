import { ExternalLink } from "lucide-react";
import { abrirExterno } from "./comum";

const LINK = /https?:\/\/[^\s<>()"']+/g;

function dominio(url: string) {
  try {
    const partes = new URL(url).hostname.split(".");
    // domínio principal: sendgrid.net, gupy.com.br (o sufixo de país com com/org/gov fica junto)
    const pais = partes.length > 2 && partes[partes.length - 1].length === 2 && /^(com|org|net|gov|edu|co)$/.test(partes[partes.length - 2]);
    return partes.slice(pais ? -3 : -2).join(".");
  } catch {
    return "link";
  }
}

/** Texto do e-mail com os links encurtados para o domínio: o link de rastreamento ocupa
 *  linhas inteiras e esconde o que a empresa escreveu. Clicar abre no navegador. */
export function CorpoEmail({ texto, className }: { texto: string; className?: string }) {
  const partes: (string | { url: string })[] = [];
  let fim = 0;
  for (const m of texto.matchAll(LINK)) {
    const url = m[0].replace(/[.,;:!?]+$/, "");
    partes.push(texto.slice(fim, m.index), { url });
    fim = m.index! + url.length;
  }
  partes.push(texto.slice(fim));
  return (
    <p className={className}>
      {partes.map((p, i) =>
        typeof p === "string" ? (
          p
        ) : (
          <button key={i} className="link-curto" title={p.url} onClick={() => abrirExterno(p.url)}>
            {dominio(p.url)} <ExternalLink size={12} aria-hidden />
          </button>
        ),
      )}
    </p>
  );
}
