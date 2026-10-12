import { Check } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api } from "../../api";
import type { EstadoConfig } from "../../tipos";

/** O repositório público do Quilha (ainda privado em 10/2026; os links abrem quando ele for aberto). */
export const REPO = "https://github.com/Eduardozsw/quilha";

export type IdSecao = "vault" | "llm" | "email" | "coleta" | "aparencia" | "diagnostico" | "sobre";

export const SECOES: IdSecao[] = ["vault", "llm", "email", "coleta", "aparencia", "diagnostico", "sobre"];

export type Problema = { tipo: string; texto: string; secao: IdSecao; grave: boolean };
export type Saude = { problemas: Problema[]; indexado_em: string | null };

/** Mensagem do backend começa em minúscula ("o provedor do LLM recusou…"); na tela, frase com maiúscula. */
export const frase = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

/** O que toda seção recebe da casca. */
export type PropsSecao = {
  config: EstadoConfig;
  saude: Saude | null;
  recarregarConfig: () => void;
  recarregarSaude: () => void;
  abrirSecao: (s: IdSecao) => void;
};

/** Documento da seção: título Newsreader 26 e uma linha de descrição. */
export function Painel({ titulo, descricao, children }: { titulo: string; descricao?: ReactNode; children: ReactNode }) {
  return (
    <>
      <div className="config-topo">
        <h2>{titulo}</h2>
        {descricao && <p>{descricao}</p>}
      </div>
      {children}
    </>
  );
}

/** Linha de ajuste: título e descrição à esquerda, ação à direita. */
export function Linha({ titulo, descricao, children }: { titulo: ReactNode; descricao?: ReactNode; children?: ReactNode }) {
  return (
    <div className="config-linha">
      <div className="texto">
        <strong>{titulo}</strong>
        {descricao && <span>{descricao}</span>}
      </div>
      {children && <div className="direita">{children}</div>}
    </div>
  );
}

export function Divisor() {
  return <hr className="config-divisor" />;
}

/** "✓ Salvo" discreto ao lado do rótulo; entra com fade e some sozinho. */
export function Salvo({ visivel }: { visivel: boolean }) {
  if (!visivel) return null;
  return (
    <span className="config-salvo troca" role="status">
      <Check size={13} strokeWidth={2} aria-hidden />
      Salvo
    </span>
  );
}

/** Rótulo + campo + ajuda (em tijolo quando é erro). */
export function Campo({ rotulo, salvo = false, erro, ajuda, id, children }: {
  rotulo: string; salvo?: boolean; erro?: string | null; ajuda?: ReactNode; id: string; children: ReactNode;
}) {
  return (
    <div className="config-campo">
      <div className="rotulo">
        <label htmlFor={id}>{rotulo}</label>
        <Salvo visivel={salvo} />
      </div>
      {children}
      {(erro || ajuda) && <p className={erro ? "ajuda erro" : "ajuda"}>{erro ? frase(erro) : ajuda}</p>}
    </div>
  );
}

/** Grava pelo `PUT /api/config`. `salvo` diz o último campo gravado e volta a null em 2 s. */
export function useGravar(aoGravar?: (e: EstadoConfig) => void) {
  const [salvo, setSalvo] = useState<string | null>(null);
  const [erro, setErro] = useState<{ campo: string; texto: string } | null>(null);
  const relogio = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(relogio.current), []);

  async function gravar(campo: string, mudancas: Record<string, string>): Promise<EstadoConfig | null> {
    try {
      const e = await api.put<EstadoConfig>("/api/config", mudancas);
      setErro(null);
      setSalvo(campo);
      window.clearTimeout(relogio.current);
      relogio.current = window.setTimeout(() => setSalvo(null), 2000);
      aoGravar?.(e);
      return e;
    } catch (e) {
      setErro({ campo, texto: e instanceof Error ? e.message : String(e) });
      return null;
    }
  }

  return { gravar, salvo, erro, erroDe: (campo: string) => (erro?.campo === campo ? erro.texto : null) };
}

/** Campo de texto que grava ao sair (blur) ou no Enter, só se mudou. Se a gravação falhar, volta ao valor salvo. */
export function CampoTexto({ rotulo, valor, aoSalvar, ajuda, largura, lista, mostrar, tipo = "text", salvo, erro }: {
  rotulo: string;
  valor: string;
  aoSalvar: (novo: string) => Promise<boolean>;
  ajuda?: ReactNode;
  largura?: number;
  lista?: string[];
  /** como o valor salvo aparece parado (ex.: "US$ 0,50"); editando, aparece o valor cru */
  mostrar?: (v: string) => string;
  tipo?: "text" | "email";
  salvo?: boolean;
  erro?: string | null;
}) {
  const id = useId();
  const [texto, setTexto] = useState(mostrar ? mostrar(valor) : valor);
  const editando = useRef(false);
  useEffect(() => {
    if (!editando.current) setTexto(mostrar ? mostrar(valor) : valor);
  }, [valor]); // eslint-disable-line react-hooks/exhaustive-deps

  async function sair() {
    editando.current = false;
    const novo = texto.trim();
    if (novo === valor || (mostrar && novo === mostrar(valor))) {
      setTexto(mostrar ? mostrar(valor) : valor);
      return;
    }
    const ok = await aoSalvar(novo);
    if (!ok) setTexto(mostrar ? mostrar(valor) : valor);
  }

  return (
    <Campo rotulo={rotulo} salvo={salvo} erro={erro} ajuda={ajuda} id={id}>
      <input
        id={id}
        className={`campo${erro ? " com-erro" : ""}`}
        type={tipo}
        style={largura ? { width: largura } : undefined}
        list={lista ? `${id}-lista` : undefined}
        value={texto}
        spellCheck={false}
        autoComplete="off"
        aria-invalid={erro ? true : undefined}
        onFocus={() => {
          editando.current = true;
          if (mostrar) setTexto(valor);
        }}
        onChange={(e) => setTexto(e.target.value)}
        onBlur={sair}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
      />
      {lista && (
        <datalist id={`${id}-lista`}>
          {lista.map((m) => <option key={m} value={m} />)}
        </datalist>
      )}
    </Campo>
  );
}

/** Interruptor: `button role="switch"`. */
export function Interruptor({ ligado, aoMudar, rotulo, desabilitado }: {
  ligado: boolean; aoMudar: (v: boolean) => void; rotulo: string; desabilitado?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={ligado}
      aria-label={rotulo}
      className="interruptor"
      disabled={desabilitado}
      onClick={() => aoMudar(!ligado)}
    >
      <span />
    </button>
  );
}
