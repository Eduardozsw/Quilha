import { useLayoutEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
  tipo?: "prim" | "sec" | "fant";
  icone?: ReactNode;
  /** ação demorada: o botão vira indicador de progresso no lugar, mantendo a largura */
  ocupado?: boolean;
  textoOcupado?: string;
  submit?: boolean;
};

export default function Botao({ tipo = "sec", icone, ocupado = false, textoOcupado, submit, className, children, disabled, style, ...resto }: Props) {
  const ref = useRef<HTMLButtonElement>(null);
  const largura = useRef<number | null>(null);

  // guarda a largura parada; ocupado, o botão não encolhe (cresce se o texto de progresso for maior que o rótulo)
  useLayoutEffect(() => {
    if (!ocupado && ref.current) largura.current = ref.current.offsetWidth;
  });

  const classe = ["btn", tipo === "sec" ? "" : tipo, ocupado ? "ocupado" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <button
      ref={ref}
      type={submit ? "submit" : "button"}
      className={classe}
      disabled={disabled || ocupado}
      aria-busy={ocupado || undefined}
      style={ocupado && largura.current ? { ...style, minWidth: largura.current } : style}
      {...resto}
    >
      {ocupado ? <><span className="giro" aria-hidden />{textoOcupado ?? children}</> : <>{icone}{children}</>}
    </button>
  );
}
