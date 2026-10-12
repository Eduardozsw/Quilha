import { useState } from "react";
import { Briefcase, Clock, Mail, MoreHorizontal, Plus, Sparkles, Trash2 } from "lucide-react";
import Aviso, { avisar } from "./Aviso";
import Botao from "./Botao";
import Cabecalho from "./Cabecalho";
import CartaoAcao from "./CartaoAcao";
import { Contexto } from "./contexto";
import Folha from "./Folha";
import ListaSelecao, { DocCorpo } from "./ListaSelecao";
import Menu from "./Menu";
import Pergunta from "./Pergunta";
import Segmentado from "./Segmentado";
import Selo from "./Selo";
import { aplicarTema, lerTema, type Tema } from "./tema";
import UsaLLM from "./UsaLLM";
import Vazio from "./Vazio";

/** Vitrine de desenvolvimento (abre com `?vitrine`): todas as peças da V3 para conferir contra V3 · Componentes.
 *  Dados fictícios. */
const VAGAS = [
  { id: "1", titulo: "Desenvolvedor Front-end", meta: "Vértice Pay · remoto", score: 82, grupo: "Novas" },
  { id: "2", titulo: "Desenvolvedor React", meta: "Orla Tech · remoto", score: 79, grupo: "Novas" },
  { id: "3", titulo: "Engenheiro de Software", meta: "Lumina Saúde · híbrido", score: 77, grupo: "Abertas" },
  { id: "4", titulo: "Estágio Corporativo", meta: "Grupo Tavares · São Paulo", score: 54, grupo: "Abertas" },
];

export default function Vitrine() {
  const [tema, setTema] = useState<Tema>(lerTema);
  const [semLLM, setSemLLM] = useState(false);
  const [sel, setSel] = useState("2");
  const [ocupado, setOcupado] = useState(false);
  const [filtro, setFiltro] = useState<"abertas" | "novas" | "minhas">("abertas");
  const [folha, setFolha] = useState(false);
  const [competencia, setCompetencia] = useState("Testes automatizados");
  const vaga = VAGAS.find((v) => v.id === sel)!;

  function gerar() {
    setOcupado(true);
    setTimeout(() => {
      setOcupado(false);
      avisar("Currículo gerado · 12 fatos do vault", { rotulo: "Abrir", onClick: () => {} });
    }, 1600);
  }

  return (
    <Contexto.Provider value={{ abrir: (t) => avisar(`Abriria ${t}`), semLLM }}>
      <div className="app">
        <main className="principal">
          <section className="tela entrando">
            <Cabecalho
              contexto="Desenvolvimento"
              titulo="Vitrine da V3"
              status={["peças da casca", "dados fictícios", `tema: ${tema}`]}
              acoes={
                <>
                  <Segmentado rotulo="Tema" valor={tema} aoMudar={(t) => { setTema(t); aplicarTema(t); }}
                    opcoes={[{ id: "sistema", nome: "Sistema" }, { id: "claro", nome: "Claro" }, { id: "escuro", nome: "Escuro" }]} />
                  <Botao onClick={() => setSemLLM((s) => !s)}>{semLLM ? "Com LLM" : "Sem LLM"}</Botao>
                </>
              }
            />
            <div style={{ display: "grid", gap: 28, maxWidth: 1000 }}>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                <Botao tipo="prim" onClick={gerar} ocupado={ocupado} textoOcupado="Gerando…" disabled={semLLM}>Gerar currículo sob medida</Botao>
                <Botao>Secundário</Botao>
                <Botao tipo="fant">Fantasma</Botao>
                <Selo tom="ok">Sustentado</Selo>
                <Selo tom="at">Pede decisão</Selo>
                <Selo tom="er">Reprovada</Selo>
                <Selo tom="ne">Enviada</Selo>
                <UsaLLM para="gerar o currículo" />
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <input className="campo" placeholder="Cole o link ou o texto da vaga" style={{ maxWidth: 360 }} />
                <Segmentado rotulo="Filtro de vagas" valor={filtro} aoMudar={setFiltro}
                  opcoes={[{ id: "abertas", nome: "Abertas", contagem: 14 }, { id: "novas", nome: "Novas", contagem: 2 }, { id: "minhas", nome: "Já me candidatei", contagem: 6 }]} />
                <Botao onClick={() => setFolha(true)} icone={<Plus size={16} strokeWidth={1.5} />}>Abrir folha</Botao>
                <Menu rotulo="Mais ações" gatilho={<MoreHorizontal size={16} strokeWidth={2} />} itens={[
                  { rotulo: "Analisar lacunas e riscos", icone: <Sparkles size={16} strokeWidth={1.5} />, dica: "usa seu LLM", desabilitado: semLLM, aoEscolher: () => avisar("Analisaria") },
                  { rotulo: "Descartar vaga", icone: <Trash2 size={16} strokeWidth={1.5} />, perigo: true, separado: true,
                    aoEscolher: () => avisar("Vaga descartada", { rotulo: "Desfazer", onClick: () => avisar("Desfeito") }) },
                ]} />
                <Menu rotulo="Trocar competência" busca alinhamento="esquerda" gatilho={<span className="meta">{competencia}</span>} classeGatilho="btn fant"
                  itens={[...["Testes automatizados", "Playwright", "Qualidade de software", "JavaScript"].map((c) => ({ rotulo: c, marcado: c === competencia, aoEscolher: () => setCompetencia(c) })),
                    { rotulo: "Sem competência", separado: true, aoEscolher: () => setCompetencia("sem competência") }]} />
              </div>
              <div style={{ display: "grid", gap: 10, maxWidth: 620 }}>
                <h2>Pede ação</h2>
                <CartaoAcao icone={<Briefcase size={17} strokeWidth={1.5} />} titulo="Vaga nova com score 82"
                  meta="Desenvolvedor Front-end · Vértice Pay · coletada hoje" acao={{ rotulo: "Gerar currículo", tipo: "prim", onClick: gerar, desabilitada: semLLM }} />
                <CartaoAcao icone={<Mail size={17} strokeWidth={1.5} />} titulo="E-mail da Nimbo Logística sem dono"
                  meta="“Teste técnico: prazo de entrega” · ontem, 17:40" acao={{ rotulo: "Triar", onClick: () => avisar("Triagem aberta") }} />
                <CartaoAcao icone={<Clock size={17} strokeWidth={1.5} />} titulo="Entrevista técnica amanhã, 14h"
                  meta="Desenvolvedor React · Orla Tech" acao={{ rotulo: "Ver candidatura", onClick: () => {} }} />
              </div>
              <Vazio icone={<Briefcase size={20} strokeWidth={1.5} />} rotulo="Vagas" titulo="Nenhuma vaga ainda"
                texto="Cole o link ou o texto de uma vaga e o Quilha compara com o seu vault."
                acoes={<Botao tipo="prim" icone={<Plus size={16} strokeWidth={1.5} />} onClick={() => setFolha(true)}>Colar uma vaga</Botao>} />
              <div className="mestre" style={{ height: 420, minHeight: 0 }}>
                <ListaSelecao rotulo="Vagas" itens={VAGAS} chave={(v) => v.id} selecionado={sel} aoSelecionar={setSel} grupo={(v) => v.grupo}
                  render={(v) => (<><span className="tx"><b>{v.titulo}</b><span className="meta">{v.meta}</span></span><span className="valor">{v.score}</span></>)} />
                <article className="doc">
                  <DocCorpo chave={sel}>
                    <div className="meta">{vaga.meta}</div>
                    <h3 style={{ marginTop: 4 }}>{vaga.titulo}</h3>
                    <p className="leitura" style={{ marginTop: 16 }}>Documento de exemplo. A pílula da lista desliza e este corpo troca com fade de 140 ms.</p>
                  </DocCorpo>
                  <div className="doc-rodape">
                    <UsaLLM />
                    <Botao tipo="fant">Abrir anúncio</Botao>
                    <Botao tipo="prim" onClick={gerar} ocupado={ocupado} textoOcupado="Gerando…" disabled={semLLM}>Gerar currículo sob medida</Botao>
                  </div>
                </article>
              </div>
            </div>
          </section>
          <Folha aberta={folha} titulo="Colar uma vaga" aoFechar={() => setFolha(false)}
            rodape={<><UsaLLM para="extrair os requisitos" /><Botao tipo="fant" onClick={() => setFolha(false)}>Cancelar</Botao><Botao tipo="prim" disabled={semLLM}>Avaliar vaga</Botao></>}>
            <p>Cole o link do anúncio ou o texto inteiro da vaga. O Quilha extrai os requisitos e compara com o seu vault.</p>
            <textarea className="campo" rows={6} placeholder="https://… ou o texto da vaga" />
          </Folha>
          <Pergunta mostrarPilula aoPerguntar={(t) => avisar(`Perguntaria: ${t}`)} />
        </main>
      </div>
      <Aviso />
    </Contexto.Provider>
  );
}
