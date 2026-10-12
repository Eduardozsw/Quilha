import { useCallback, useEffect, useState } from "react";
import { Gauge, Plus } from "lucide-react";
import { api } from "../api";
import { useCarregar } from "../comum";
import type { Categoria, Competencia, DetalheCompetencia, LeituraGit, Semana, Sinais } from "../tipos";
import Botao from "../ui/Botao";
import Cabecalho from "../ui/Cabecalho";
import { avisar } from "../ui/Aviso";
import Folha from "../ui/Folha";
import Vazio from "../ui/Vazio";
import { mensagem } from "./candidaturas/comum";
import Documento from "./competencias/Documento";
import FecharLacuna from "./competencias/FecharLacuna";
import FolhaPlano from "./competencias/FolhaPlano";
import FolhaLigar from "./competencias/FolhaLigar";
import FolhaNivel, { type Rascunho } from "./competencias/FolhaNivel";
import FolhaNova from "./competencias/FolhaNova";
import Lista, { ordenadas } from "./competencias/Lista";
import { plural } from "./competencias/comum";

type Props = {
  /** slug da competência que abre selecionada, ou "plano" para abrir a folha do plano da semana */
  inicial?: string;
  /** o estudo da semana mudou (a Início mostra) */
  aoMudar?: () => void;
};

const UMA_HORA = 3600;

export type IdFolha = "nivel" | "ligar" | "nova" | "plano" | "remover" | null;

/** Competências (spec §5.6): lista agrupada com o medidor; documento com nível, evidências do vault e fechar a lacuna. */
export default function Competencias({ inicial, aoMudar }: Props) {
  const lista = useCarregar(() => api.get<Competencia[]>("/api/competencias"));
  const semana = useCarregar(() => api.get<Semana>("/api/estudos/semana"));
  const [escolhida, setEscolhida] = useState<string | null>(inicial === "plano" ? null : inicial ?? null);
  const [folha, setFolha] = useState<IdFolha>(inicial === "plano" ? "plano" : null);
  const [sinais, setSinais] = useState<Sinais | null>(null);
  const [lendo, setLendo] = useState(false);

  // commits sem resposta: a tela lê o git sozinha no máximo uma vez por hora; "Ler de novo" ignora o limite.
  // Falha na leitura não vira erro na tela: a lista só some.
  const lerCommits = useCallback(async (limite: number | null) => {
    setLendo(true);
    try {
      await api.post<LeituraGit>("/api/estudos/git", { dias: 7, se_mais_velho_que: limite }).catch(() => null);
      setSinais(await api.get<Sinais>("/api/estudos/sinais"));
    } catch {
      setSinais(null);
    } finally {
      setLendo(false);
    }
  }, []);
  useEffect(() => { lerCommits(UMA_HORA); }, [lerCommits]);
  // ida e volta "Mudar nível" → "Ligar um fato" → "Mudar nível", com o nível e a justificativa guardados
  const [rascunho, setRascunho] = useState<Rascunho | null>(null);
  const niveis = useCarregar(() => api.get<Record<string, string>>("/api/competencias/niveis"));
  const categorias = useCarregar(() => api.get<Categoria[]>("/api/competencias/categorias"));

  const todas = lista.dados ?? [];
  const selecionada = todas.find((c) => c.slug === escolhida) ?? ordenadas(todas)[0] ?? null;
  const slug = selecionada?.slug ?? null;
  const detalhe = useCarregar(
    () => (slug === null ? Promise.resolve(null) : api.get<DetalheCompetencia>(`/api/competencias/${slug}`)), [slug]);
  const d = detalhe.dados && detalhe.dados.competencia.slug === slug ? detalhe.dados : null;

  function recarregar() {
    lista.recarregar();
    detalhe.recarregar();
  }

  /** estudo gravado ou commit respondido */
  function estudou() {
    detalhe.recarregar();
    semana.recarregar();
    api.get<Sinais>("/api/estudos/sinais").then(setSinais, () => setSinais(null));
    aoMudar?.();
  }

  const prontas = todas.filter((c) => c.pronta_para_cv).length;
  const s = semana.dados;
  const minutos = s && (
    <button className="link-cab" onClick={() => setFolha("plano")}>
      {s.plano ? `${s.minutos} de ${s.minutos_alvo} min` : `${s.minutos} min`} de estudo nesta semana
    </button>
  );
  const status = lista.dados && todas.length > 0 ? [`${prontas} de ${todas.length} sustentam o currículo`, minutos] : [];
  const cabecalho = <Cabecalho titulo="Competências" status={status} />;

  function fecharLigar() {
    detalhe.recarregar();
    if (rascunho) setFolha("nivel");
    else setFolha(null);
  }

  const folhas = (
    <>
      {d && (
        <>
          <FolhaNivel aberta={folha === "nivel"} detalhe={d} niveis={niveis.dados ?? {}} rascunho={rascunho}
            aoFechar={() => { setFolha(null); setRascunho(null); }}
            aoRecarregar={detalhe.recarregar}
            aoLigarFato={(r) => { setRascunho(r); setFolha("ligar"); }}
            aoGravar={(n) => { setFolha(null); setRascunho(null); recarregar(); avisar(`Nível ${n} gravado`); }} />
          <FolhaLigar aberta={folha === "ligar"} detalhe={d} aoFechar={fecharLigar} aoLigar={recarregar} />
          <FolhaRemover aberta={folha === "remover"} detalhe={d} aoFechar={() => setFolha(null)}
            aoRemover={() => { setFolha(null); setEscolhida(null); lista.recarregar(); }} />
        </>
      )}
      <FolhaPlano aberta={folha === "plano"} semana={semana.dados} competencias={todas} aoFechar={() => setFolha(null)}
        aoMudar={() => { semana.recarregar(); aoMudar?.(); }} />
      <FolhaNova aberta={folha === "nova"} categorias={categorias.dados ?? []} aoFechar={() => setFolha(null)}
        aoCriar={(c) => { setFolha(null); setEscolhida(c.slug); lista.recarregar(); avisar(`Competência adicionada: ${c.nome}`); }} />
    </>
  );

  if (lista.erro) return <>{cabecalho}<p className="erro-tela">{lista.erro}</p></>;

  // vazio (decisão 11): sem subtítulo no cabeçalho e sem mestre-detalhe
  if (lista.dados && todas.length === 0)
    return (
      <>
        {cabecalho}
        <div className="vazio-tela">
          <Vazio icone={<Gauge size={20} strokeWidth={1.5} />} titulo="Nenhuma competência ainda"
            texto="Competências são o que as vagas pedem e o seu currículo prova. Comece pelas que mais aparecem nas vagas."
            acoes={<Botao tipo="prim" icone={<Plus size={16} strokeWidth={1.5} aria-hidden />} onClick={() => setFolha("nova")}>Nova competência</Botao>} />
        </div>
        {folhas}
      </>
    );

  return (
    <>
      {cabecalho}
      <div className="mestre mestre-comp">
        {!lista.dados ? (
          <div className="esqueleto-lista" aria-hidden>{Array.from({ length: 8 }, (_, i) => <span key={i} />)}</div>
        ) : (
          <Lista competencias={todas} selecionada={slug} aoSelecionar={setEscolhida} aoNova={() => setFolha("nova")} />
        )}
        <Documento
          key={slug ?? "nada"}
          detalhe={d}
          erro={detalhe.erro}
          carregando={detalhe.carregando}
          aoMudar={recarregar}
          aoMudarNivel={() => setFolha("nivel")}
          aoLigar={() => setFolha("ligar")}
          aoRemover={() => setFolha("remover")}
          depois={d && (
            <FecharLacuna key={d.competencia.slug} detalhe={d} sinais={sinais?.sinais ?? null} lidosEm={sinais?.lidos_em ?? null}
              lendo={lendo} aoLerDeNovo={() => lerCommits(null)} aoMudar={estudou} />
          )}
        />
      </div>
      {folhas}
    </>
  );
}

type PropsRemover = { aberta: boolean; detalhe: DetalheCompetencia; aoFechar: () => void; aoRemover: () => void };

/** Confirmação de "Remover competência" (decisão 9): diz o que se perde; as notas do vault não são tocadas. */
function FolhaRemover({ aberta, detalhe, aoFechar, aoRemover }: PropsRemover) {
  const c = detalhe.competencia;
  const [ocupado, setOcupado] = useState(false);
  // estudos e requisitos de vaga não somem, mas perdem a ligação: a confirmação conta antes
  const [lig, setLig] = useState<{ estudos: number; requisitos: number } | null>(null);
  useEffect(() => {
    if (!aberta) return;
    setLig(null);
    api.get<{ estudos: number; requisitos: number }>(`/api/competencias/${c.slug}/ligacoes`).then(setLig, () => setLig(null));
  }, [aberta, c.slug]);
  const n = detalhe.evidencias.length;
  const perde = [
    n > 0 && plural(n, "ligação de evidência", "ligações de evidência"),
    c.nivel !== null && "os níveis declarados",
  ].filter(Boolean).join(" e ");
  const desligam = [
    lig?.estudos && plural(lig.estudos, "estudo registrado", "estudos registrados"),
    lig?.requisitos && plural(lig.requisitos, "requisito de vaga", "requisitos de vaga"),
  ].filter(Boolean).join(" e ");

  async function remover() {
    setOcupado(true);
    try {
      await api.del(`/api/competencias/${c.slug}?com_historico=true`);
      avisar(`${c.nome} removida`);
      aoRemover();
    } catch (e) {
      avisar(mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Folha aberta={aberta} titulo="Remover competência" largura={480} aoFechar={() => { if (!ocupado) aoFechar(); }}
      rodape={
        <>
          <Botao tipo="fant" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
          <Botao tipo="prim" className="perigo" onClick={remover} ocupado={ocupado}>Remover</Botao>
        </>
      }>
      <p>
        {c.nome} sai da sua lista e do competencias.yaml.
        {perde ? ` Saem junto ${perde}.` : ""}
        {desligam ? ` ${desligam} ${(lig!.estudos + lig!.requisitos) === 1 ? "fica" : "ficam"} sem competência ligada.` : ""}
        {" "}As notas do vault não são tocadas.
      </p>
    </Folha>
  );
}
