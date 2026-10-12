import { useEffect, useState } from "react";
import { api } from "../../api";
import type { DetalheCandidatura, PerfilCurriculo } from "../../tipos";
import Botao from "../../ui/Botao";
import Folha from "../../ui/Folha";
import { mensagem } from "./comum";

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function hojeIso() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Data e hora digitadas, em ISO com o fuso local: "14h" continua 14h (toISOString viraria UTC). */
export function isoLocal(data: string, hora: string): string {
  const d = new Date(`${data}T${hora}:00`);
  const off = -d.getTimezoneOffset();
  const a = Math.abs(off);
  return `${data}T${hora}:00${off >= 0 ? "+" : "-"}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

function partesLocais(iso: string | null): { data: string; hora: string } {
  if (!iso) return { data: "", hora: "" };
  const d = new Date(iso);
  return { data: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, hora: `${pad(d.getHours())}:${pad(d.getMinutes())}` };
}

function SeletorPerfil({ id, valor, perfis, aoMudar, vazio }: { id: string; valor: string; perfis: PerfilCurriculo[]; aoMudar: (v: string) => void; vazio: string }) {
  return (
    <select id={id} className="campo" value={valor} onChange={(e) => aoMudar(e.target.value)}>
      <option value="">{vazio}</option>
      {perfis.map((p) => <option key={p.slug} value={p.slug}>{p.cargo?.pt ?? p.slug}</option>)}
    </select>
  );
}

type PropsAdicionar = { aberta: boolean; perfis: PerfilCurriculo[]; aoFechar: () => void; aoCriar: (d: DetalheCandidatura) => void };

/** "Adicionar candidatura" (decisão 9): o que foi feito fora do Quilha nasce em "Aguardando resposta". Sem custo. */
export function FolhaAdicionar({ aberta, perfis, aoFechar, aoCriar }: PropsAdicionar) {
  const [empresa, setEmpresa] = useState("");
  const [cargo, setCargo] = useState("");
  const [quando, setQuando] = useState(hojeIso);
  const [perfil, setPerfil] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (!aberta) return;
    setEmpresa(""); setCargo(""); setQuando(hojeIso()); setPerfil(""); setErro(null);
  }, [aberta]);

  async function adicionar() {
    setOcupado(true);
    setErro(null);
    try {
      aoCriar(await api.post<DetalheCandidatura>("/api/candidaturas",
        { empresa: empresa.trim(), titulo: cargo.trim() || null, enviada_em: quando || null, perfil: perfil || null }));
    } catch (e) {
      setErro(mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Folha
      aberta={aberta}
      titulo="Adicionar candidatura"
      largura={560}
      aoFechar={() => { if (!ocupado) aoFechar(); }}
      rodape={
        <>
          <span className="meta dica-folha">sem custo: não chama o modelo</span>
          <Botao tipo="fant" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
          <Botao tipo="prim" onClick={adicionar} ocupado={ocupado} disabled={!empresa.trim()}>Adicionar</Botao>
        </>
      }
    >
      <p>Para uma candidatura que você fez fora do Quilha.</p>
      <form className="form-folha" onSubmit={(e) => { e.preventDefault(); if (empresa.trim() && !ocupado) adicionar(); }}>
        <div className="campos-2">
          <label className="rotulo-campo" htmlFor="ad-empresa">Empresa
            <input id="ad-empresa" className="campo" value={empresa} onChange={(e) => setEmpresa(e.target.value)} autoComplete="off" />
          </label>
          <label className="rotulo-campo" htmlFor="ad-cargo">Cargo
            <input id="ad-cargo" className="campo" value={cargo} onChange={(e) => setCargo(e.target.value)} autoComplete="off" />
          </label>
        </div>
        <div className="campos-enviada">
          <label className="rotulo-campo" htmlFor="ad-quando">Enviada em
            <input id="ad-quando" type="date" className="campo" value={quando} max={hojeIso()} onChange={(e) => setQuando(e.target.value)} />
          </label>
          <label className="rotulo-campo" htmlFor="ad-perfil">Perfil do currículo (opcional)
            <SeletorPerfil id="ad-perfil" valor={perfil} perfis={perfis} aoMudar={setPerfil} vazio="Sem recorte" />
            <small className="meta ajuda-campo">Conta na nota do recorte em Currículos.</small>
          </label>
        </div>
        <button type="submit" hidden />
      </form>
      {erro && <div className="erro-folha" role="alert">{erro}</div>}
    </Folha>
  );
}

type PropsEntrevista = { aberta: boolean; detalhe: DetalheCandidatura | null; aoFechar: () => void; aoGravar: (d: DetalheCandidatura) => void };

/** Folha pequena "Marcar entrevista": "O quê" (padrão "Entrevista"), data e hora. */
export function FolhaEntrevista({ aberta, detalhe, aoFechar, aoGravar }: PropsEntrevista) {
  const c = detalhe?.candidatura;
  const [titulo, setTitulo] = useState("Entrevista");
  const [data, setData] = useState("");
  const [hora, setHora] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (!aberta) return;
    const p = partesLocais(c?.entrevista_em ?? null);
    setTitulo(c?.entrevista_titulo || "Entrevista"); setData(p.data); setHora(p.hora || "10:00"); setErro(null);
  }, [aberta]); // eslint-disable-line react-hooks/exhaustive-deps

  async function gravar() {
    if (!c) return;
    setOcupado(true);
    setErro(null);
    try {
      aoGravar(await api.put<DetalheCandidatura>(`/api/candidaturas/${c.id}/entrevista`,
        { quando: isoLocal(data, hora), titulo: titulo.trim() || null }));
    } catch (e) {
      setErro(mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  const remarcar = !!c?.entrevista_em;
  return (
    <Folha
      aberta={aberta}
      titulo={remarcar ? "Remarcar entrevista" : "Marcar entrevista"}
      largura={460}
      aoFechar={() => { if (!ocupado) aoFechar(); }}
      rodape={
        <>
          <Botao tipo="fant" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
          <Botao tipo="prim" onClick={gravar} ocupado={ocupado} disabled={!data || !hora}>{remarcar ? "Remarcar" : "Marcar"}</Botao>
        </>
      }
    >
      <form className="form-folha" onSubmit={(e) => { e.preventDefault(); if (data && hora && !ocupado) gravar(); }}>
        <label className="rotulo-campo" htmlFor="en-titulo">O quê
          <input id="en-titulo" className="campo" value={titulo} onChange={(e) => setTitulo(e.target.value)} placeholder="Entrevista" />
        </label>
        <div className="campos-2">
          <label className="rotulo-campo" htmlFor="en-data">Data
            <input id="en-data" type="date" className="campo" value={data} onChange={(e) => setData(e.target.value)} />
          </label>
          <label className="rotulo-campo" htmlFor="en-hora">Hora
            <input id="en-hora" type="time" className="campo" value={hora} onChange={(e) => setHora(e.target.value)} />
          </label>
        </div>
        <button type="submit" hidden />
      </form>
      {erro && <div className="erro-folha" role="alert">{erro}</div>}
    </Folha>
  );
}

type PropsEditar = {
  modo: "titulo" | "perfil" | null;
  detalhe: DetalheCandidatura | null;
  perfis: PerfilCurriculo[];
  aoFechar: () => void;
  aoGravar: (d: DetalheCandidatura) => void;
};

/** "Editar título" e "Trocar perfil": a mesma folha, com um campo. */
export function FolhaEditar({ modo, detalhe, perfis, aoFechar, aoGravar }: PropsEditar) {
  const c = detalhe?.candidatura;
  const [valor, setValor] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (!modo || !c) return;
    setValor(modo === "titulo" ? c.titulo ?? "" : c.perfil && c.perfil !== "geral" ? c.perfil : "");
    setErro(null);
  }, [modo]); // eslint-disable-line react-hooks/exhaustive-deps

  async function gravar() {
    if (!c || !modo) return;
    setOcupado(true);
    setErro(null);
    try {
      aoGravar(modo === "titulo"
        ? await api.put<DetalheCandidatura>(`/api/candidaturas/${c.id}/titulo`, { titulo: valor.trim() || null })
        : await api.put<DetalheCandidatura>(`/api/candidaturas/${c.id}/perfil`, { perfil: valor || "geral" }));
    } catch (e) {
      setErro(mensagem(e));
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Folha
      aberta={modo !== null}
      titulo={modo === "perfil" ? "Trocar perfil" : "Editar título"}
      largura={460}
      aoFechar={() => { if (!ocupado) aoFechar(); }}
      rodape={
        <>
          <Botao tipo="fant" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
          <Botao tipo="prim" onClick={gravar} ocupado={ocupado}>Salvar</Botao>
        </>
      }
    >
      <form className="form-folha" onSubmit={(e) => { e.preventDefault(); if (!ocupado) gravar(); }}>
        {modo === "perfil" ? (
          <label className="rotulo-campo" htmlFor="ed-perfil">Perfil do currículo
            <SeletorPerfil id="ed-perfil" valor={valor} perfis={perfis} aoMudar={setValor} vazio="Sem recorte" />
          </label>
        ) : (
          <label className="rotulo-campo" htmlFor="ed-titulo">Cargo
            <input id="ed-titulo" className="campo" value={valor} onChange={(e) => setValor(e.target.value)} />
          </label>
        )}
        <button type="submit" hidden />
      </form>
      {erro && <div className="erro-folha" role="alert">{erro}</div>}
    </Folha>
  );
}

export { SeletorPerfil };
