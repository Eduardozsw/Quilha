import { useLayoutEffect, useRef, useState } from "react";
import { MoreHorizontal, PanelLeft, Pencil, Settings, SquarePen, Trash2 } from "lucide-react";
import { Logo } from "../marca";
import Menu from "./Menu";
import { NAVEGACAO, type IdTela } from "./telas";

type Props = {
  tela: IdTela;
  abrir: (id: IdTela) => void;
  novaConversa: () => void;
  recentes: { id: number; titulo: string }[];
  recenteAtiva?: number | null;
  abrirRecente: (id: number) => void;
  renomearRecente?: (id: number, titulo: string) => void;
  apagarRecente?: (id: number) => void;
  usuario: { nome: string; detalhe?: string };
  recolhida: boolean;
  alternar: () => void;
};

const ICONE = { size: 17, strokeWidth: 1.5, "aria-hidden": true } as const;

/** Lateral da V3: logo, nova conversa, as 6 telas com a pílula que desliza, recentes e usuário + engrenagem. */
export default function Lateral({ tela, abrir, novaConversa, recentes, recenteAtiva, abrirRecente, renomearRecente, apagarRecente,
  usuario, recolhida, alternar }: Props) {
  const nav = useRef<HTMLElement>(null);
  const [pilula, setPilula] = useState<{ y: number; visivel: boolean }>({ y: 0, visivel: false });

  // a pílula vai até o item ativo; em Configurações (fora da navegação) ela some no lugar
  useLayoutEffect(() => {
    function medir() {
      const item = nav.current?.querySelector<HTMLElement>(`[data-tela="${tela}"]`);
      setPilula((p) => (item ? { y: item.offsetTop, visivel: true } : { ...p, visivel: false }));
    }
    medir();
    window.addEventListener("resize", medir);
    return () => window.removeEventListener("resize", medir);
  }, [tela]);

  return (
    <aside className="lateral" aria-label="Navegação">
      <div className="topo-lat">
        <Logo />
        <span className="nome">Quilha</span>
        <button className="btn-icone recolher" onClick={alternar} aria-label={recolhida ? "Abrir a lateral" : "Recolher a lateral"} aria-expanded={!recolhida}>
          <PanelLeft {...ICONE} />
        </button>
      </div>
      <button className="item" onClick={novaConversa} title={recolhida ? "Nova conversa" : undefined}>
        <SquarePen {...ICONE} /><span className="rotulo">Nova conversa</span>
      </button>
      <div className="sep" />
      <nav className="nav" ref={nav}>
        <div className="pilula-nav" style={{ transform: `translateY(${pilula.y}px)`, opacity: pilula.visivel ? 1 : 0 }} />
        {NAVEGACAO.map(({ id, nome, icone: Icone }) => (
          <button
            key={id}
            data-tela={id}
            className={`item${tela === id ? " ativo" : ""}`}
            aria-current={tela === id ? "page" : undefined}
            title={recolhida ? nome : undefined}
            onClick={() => abrir(id)}
          >
            <Icone {...ICONE} /><span className="rotulo">{nome}</span>
          </button>
        ))}
      </nav>
      {recentes.length > 0 && (
        <div className="recentes" aria-hidden={recolhida || undefined}>
          <h3>Recentes</h3>
          {recentes.map((r) => (
            <Recente key={r.id} recente={r} ativa={tela === "conversa" && recenteAtiva === r.id} recolhida={recolhida}
              aoAbrir={() => abrirRecente(r.id)} aoRenomear={renomearRecente && ((t) => renomearRecente(r.id, t))}
              aoApagar={apagarRecente && (() => apagarRecente(r.id))} />
          ))}
        </div>
      )}
      <div className="usuario">
        <span className="avatar" aria-hidden>{(usuario.nome.trim()[0] ?? "?").toUpperCase()}</span>
        <span className="rotulo">
          {usuario.nome}
          {usuario.detalhe && <small>{usuario.detalhe}</small>}
        </span>
        <button
          className={`btn-icone${tela === "configuracoes" ? " ativo" : ""}`}
          onClick={() => abrir("configuracoes")}
          aria-label="Configurações"
          aria-current={tela === "configuracoes" ? "page" : undefined}
          title="Configurações"
        >
          <Settings {...ICONE} />
        </button>
      </div>
    </aside>
  );
}

/** Uma conversa recente: abre no clique; o "⋯" renomeia (na própria linha: Enter grava, Esc desiste) ou apaga
 *  (com confirmação na linha, porque não tem volta). */
function Recente({ recente, ativa, recolhida, aoAbrir, aoRenomear, aoApagar }: {
  recente: { id: number; titulo: string }; ativa: boolean; recolhida: boolean; aoAbrir: () => void;
  aoRenomear?: (titulo: string) => void; aoApagar?: () => void;
}) {
  const [modo, setModo] = useState<"ver" | "renomear" | "apagar">("ver");
  const [rascunho, setRascunho] = useState(recente.titulo);
  const tab = recolhida ? -1 : undefined;

  if (modo === "renomear")
    return (
      <div className="linha-recente">
        <input className="campo campo-recente" autoFocus value={rascunho} aria-label="Novo nome da conversa"
          onChange={(e) => setRascunho(e.target.value)} onBlur={() => setModo("ver")}
          onKeyDown={(e) => {
            if (e.key === "Escape") { e.stopPropagation(); setModo("ver"); }
            if (e.key === "Enter") { aoRenomear?.(rascunho); setModo("ver"); }
          }} />
      </div>
    );
  if (modo === "apagar")
    return (
      <div className="linha-recente confirmar-apagar" role="group" aria-label={`Apagar ${recente.titulo}?`}>
        <span>Apagar?</span>
        <button className="perigo" autoFocus onClick={() => { setModo("ver"); aoApagar?.(); }}>Apagar</button>
        <button onClick={() => setModo("ver")}>Cancelar</button>
      </div>
    );
  return (
    <div className={`linha-recente${ativa ? " ativo" : ""}`}>
      <button className={ativa ? "ativo" : undefined} tabIndex={tab} onClick={aoAbrir}>{recente.titulo}</button>
      {(aoRenomear || aoApagar) && !recolhida && (
        <Menu rotulo={`Mais ações de ${recente.titulo}`} alinhamento="esquerda" classeGatilho="btn-icone mais-recente"
          gatilho={<MoreHorizontal size={15} strokeWidth={1.75} aria-hidden />}
          itens={[
            ...(aoRenomear ? [{ rotulo: "Renomear", icone: <Pencil size={16} strokeWidth={1.5} />,
              aoEscolher: () => { setRascunho(recente.titulo); setModo("renomear"); } }] : []),
            ...(aoApagar ? [{ rotulo: "Apagar conversa", icone: <Trash2 size={16} strokeWidth={1.5} />, perigo: true, separado: !!aoRenomear,
              aoEscolher: () => setModo("apagar") }] : []),
          ]} />
      )}
    </div>
  );
}
