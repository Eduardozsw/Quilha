import type { ReactNode } from "react";
import type { DetalheCandidatura } from "../../tipos";
import { DocCorpo } from "../../ui/ListaSelecao";
import Selo from "../../ui/Selo";
import LinhaDoTempo from "./LinhaDoTempo";
import { SELO, diaMes, ePingada, nomeDa, quandoMarco } from "./comum";

type Props = {
  detalhe: DetalheCandidatura | null;
  erro: string | null;
  carregando: boolean;
  nomePerfil: (slug: string | null) => string | null;
  aoMudar: () => void;
  /** menu "⋯" ao lado do selo */
  menu?: ReactNode;
  /** cartões e avisos entre o título e a linha do tempo */
  antes?: ReactNode;
  /** o que vem depois da linha do tempo (cartão de preparo ou roteiro salvo) */
  depois?: ReactNode;
};

/** "Orla Tech · enviada em 27 de set. · currículo front-end"; a enviar e pingada dizem de onde vieram. */
function contexto(d: DetalheCandidatura, perfil: string | null): string {
  const c = d.candidatura;
  const empresa = c.empresa ?? "Sem empresa";
  if (c.status === "a_enviar") {
    const gerado = d.cv?.criado_em ?? c.enviada_em;
    return `${empresa} · currículo${perfil ? ` ${perfil}` : ""} gerado ${quandoMarco(gerado)}`;
  }
  if (ePingada(c)) return `${empresa} · nasceu de um e-mail em ${diaMes(c.enviada_em)}`;
  return [empresa, `enviada em ${diaMes(c.enviada_em)}`, perfil && `currículo ${perfil}`].filter(Boolean).join(" · ");
}

/** Documento da candidatura: contexto, título Newsreader 28 e selo da etapa; a linha do tempo embaixo. */
export default function Documento({ detalhe: d, erro, carregando, nomePerfil, aoMudar, menu, antes, depois }: Props) {
  if (!d) return <article className="doc" aria-busy={carregando || undefined}>{erro && <p className="erro-tela">{erro}</p>}</article>;
  const c = d.candidatura;
  const selo = SELO[c.status];
  return (
    <article className="doc doc-cand" aria-busy={carregando || undefined}>
      <DocCorpo chave={c.id}>
        <header className="topo-cand">
          <div>
            <div className="meta">{contexto(d, nomePerfil(c.perfil))}</div>
            <h3>{ePingada(c) ? "Candidatura sem título" : nomeDa(c)}</h3>
          </div>
          <div className="selo-menu">
            <Selo tom={selo.tom}>{selo.nome}</Selo>
            {menu}
          </div>
        </header>
        {erro && <p className="erro-tela">{erro}</p>}
        {antes}
        <LinhaDoTempo detalhe={d} nomePerfil={nomePerfil} aoMudar={aoMudar} />
        {depois}
      </DocCorpo>
    </article>
  );
}
