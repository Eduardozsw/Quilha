import { ArrowUpRight, FolderOpen, Play } from "lucide-react";
import { abrirExterno, mostrarNaPasta, useCarregar } from "../../comum";
import { pastaDeLogs } from "../../api";
import Botao from "../../ui/Botao";
import { reabrirTour } from "../../ui/Tour";
import { Divisor, Linha, Painel, REPO, type PropsSecao } from "./pecas";

/** Configurações → Sobre: versão, licença, pastas, tour de novo e "Relatar um problema". */
export default function Sobre({ config }: PropsSecao) {
  const { versao, sistema } = config.app;
  const logs = useCarregar(() => pastaDeLogs());
  const relato = `${REPO}/issues/new?body=${encodeURIComponent(`Versão: ${versao}\nSistema: ${sistema}\n\nO que aconteceu:\n`)}`;
  const pasta = <FolderOpen size={15} strokeWidth={1.75} aria-hidden />;
  const fora = <ArrowUpRight size={15} strokeWidth={1.75} aria-hidden />;

  return (
    <Painel titulo="Sobre" descricao={`Quilha ${versao} · código aberto, licença MIT.`}>
      <Linha titulo="Versão" descricao={`${versao} · ${sistema}`}>
        <button className="config-link" onClick={() => abrirExterno(REPO)}>
          Ver o código no GitHub <ArrowUpRight size={14} strokeWidth={1.75} aria-hidden />
        </button>
      </Linha>
      <Linha titulo="Licença" descricao="MIT: use, mude e distribua à vontade." />
      <Divisor />
      <Linha titulo="Pasta de dados" descricao={`${config.pastas.base} · banco, configuração e currículos`}>
        <Botao icone={pasta} onClick={() => mostrarNaPasta(config.pastas.base)}>Mostrar na pasta</Botao>
      </Linha>
      {logs.dados && (
        <Linha titulo="Pasta de logs" descricao={logs.dados}>
          <Botao icone={pasta} onClick={() => mostrarNaPasta(logs.dados!)}>Mostrar na pasta</Botao>
        </Linha>
      )}
      <Divisor />
      <Linha titulo="Tour" descricao="Os 4 passos da primeira abertura, de novo.">
        <Botao icone={<Play size={15} strokeWidth={1.75} aria-hidden />} onClick={reabrirTour}>Ver tour de novo</Botao>
      </Linha>
      <Linha titulo="Relatar um problema" descricao="Abre uma issue no GitHub com a versão e o sistema já preenchidos. Nada do seu vault vai junto.">
        <Botao icone={fora} onClick={() => abrirExterno(relato)}>Relatar um problema</Botao>
      </Linha>
    </Painel>
  );
}
