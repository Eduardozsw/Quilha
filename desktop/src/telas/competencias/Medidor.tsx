import { corMedidor, type Grupo } from "./comum";

/** Medidor de nível: 4 barras de 4 px (6/9/12/15 de altura); cheias até o nível, na cor do grupo. */
export default function Medidor({ nivel, grupo }: { nivel: number | null; grupo: Grupo }) {
  const rotulo = nivel === null ? "sem nível" : `nível ${nivel}${grupo === "falta" ? ", falta evidência" : ""}`;
  return (
    <span className="medidor" role="img" aria-label={rotulo} title={rotulo}>
      {[1, 2, 3, 4].map((n) => (
        <i key={n} style={nivel !== null && n <= nivel ? { background: corMedidor(grupo) } : undefined} />
      ))}
    </span>
  );
}
