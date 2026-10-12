import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Botao from "./Botao";

type Progresso = { estado: "parado" | "rodando" | "pronto" | "cancelado" | "erro"; feitas: number; total: number; erro?: string };

/** Progresso da indexação que já começou (`POST /api/operacao/index/iniciar`): barra, "N de M notas" e "Cancelar".
 *  O mesmo das boas-vindas e de Configurações → Vault. Quem usa decide o que fazer em cada fim. */
export default function ProgressoIndexacao({ aoTerminar, aoCancelar, aoErro }: {
  aoTerminar: () => void; aoCancelar: () => void; aoErro: (mensagem: string) => void;
}) {
  const [progresso, setProgresso] = useState<Progresso | null>(null);
  const fins = useRef({ aoTerminar, aoCancelar, aoErro });
  fins.current = { aoTerminar, aoCancelar, aoErro };

  // consultas encadeadas: a próxima só sai 300 ms depois da resposta da anterior (nunca duas em voo)
  useEffect(() => {
    let vivo = true;
    let relogio: number | undefined;
    async function consultar() {
      try {
        const p = await api.get<Progresso>("/api/operacao/index/progresso");
        if (!vivo) return;
        setProgresso(p);
        if (p.estado === "pronto") return fins.current.aoTerminar();
        if (p.estado === "cancelado") return fins.current.aoCancelar();
        if (p.estado === "erro") return fins.current.aoErro(p.erro ?? "não deu para ler o vault");
      } catch {
        /* a próxima volta tenta de novo */
      }
      if (vivo) relogio = window.setTimeout(consultar, 300);
    }
    relogio = window.setTimeout(consultar, 300);
    return () => {
      vivo = false;
      window.clearTimeout(relogio);
    };
  }, []);

  const total = progresso?.total ?? 0;
  const feitas = progresso?.feitas ?? 0;
  return (
    <div className="progresso-indexacao" role="status" aria-live="polite">
      <div className="trilho-bv" aria-hidden><i style={{ transform: `scaleX(${total ? feitas / total : 0.05})` }} /></div>
      <div className="linha-progresso">
        <p className="meta tabular">{total ? `${feitas} de ${total} notas` : "Contando as notas…"}</p>
        <Botao tipo="fant" onClick={() => api.post("/api/operacao/index/cancelar").catch(() => undefined)}>Cancelar</Botao>
      </div>
    </div>
  );
}
