"""Perfis de currículo: um conteúdo (o vault), vários recortes (`curriculos.yaml`).

O perfil só muda **peso e ordem**. A regra do vault continua intacta: entra fato de competência
com nível ≥ 2 e evidência, seja qual for o perfil. Um perfil não consegue afirmar mais do que o
vault sustenta — só escolher o que aparece primeiro.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hermes.domain.curriculo import IDIOMAS, MAX_FATOS


class PerfilInvalido(ValueError):
    """`curriculos.yaml` com erro. A mensagem diz qual perfil e qual campo."""


@dataclass(frozen=True)
class PerfilCV:
    slug: str
    cargo: dict[str, str]
    foco: str = ""
    competencias: dict[str, float] = field(default_factory=dict)
    peso_fora_do_perfil: float = 0.5
    primeiro: tuple[str, ...] = ()
    excluir: tuple[str, ...] = ()
    limite_fatos: int = MAX_FATOS
    paginas: int = 1
    # linhas da seção Habilidades, na ordem: {"rotulo": {pt, en}, "itens": ({pt, en}, ...)}
    habilidades: tuple[dict, ...] = ()

    def peso(self, slug: str, peso_taxonomia: float) -> float:
        """O peso que vale neste perfil. Competência fora dele entra, com peso reduzido."""
        if slug in self.competencias:
            return float(self.competencias[slug])
        return peso_taxonomia * self.peso_fora_do_perfil

    @property
    def titulo(self) -> str:
        return f"Melhores para vaga de {self.cargo['pt']}"

    def para_hash(self) -> dict:
        return {"slug": self.slug, "cargo": self.cargo, "foco": self.foco,
                "competencias": self.competencias, "fora": self.peso_fora_do_perfil,
                "primeiro": self.primeiro, "excluir": self.excluir, "limite": self.limite_fatos}


def _habilidades(slug: str, bruto) -> tuple[dict, ...]:
    linhas = []
    if bruto is not None and not isinstance(bruto, list):
        raise PerfilInvalido(f"`{slug}`: `habilidades` precisa ser uma lista de itens com `rotulo:` e `itens:`")
    for i, item in enumerate(bruto or []):
        if not isinstance(item, dict):
            raise PerfilInvalido(f"`{slug}`: habilidades #{i + 1} precisa ser um item com `rotulo:` e `itens:`")
        rotulo = item.get("rotulo") or {}
        if not isinstance(rotulo, dict) or any(not rotulo.get(idioma) for idioma in IDIOMAS):
            raise PerfilInvalido(f"`{slug}`: habilidade #{i + 1} precisa de `rotulo` com {list(IDIOMAS)}")
        itens = item.get("itens")
        if not isinstance(itens, list) or not itens:
            raise PerfilInvalido(f"`{slug}`: habilidade `{rotulo['pt']}` sem `itens`")
        traduzidos = []
        for x in itens:
            if isinstance(x, dict) and any(not x.get(idioma) for idioma in IDIOMAS):
                raise PerfilInvalido(f"`{slug}`: item `{x}` em `{rotulo['pt']}` precisa de {list(IDIOMAS)}")
            traduzidos.append({idioma: str(x[idioma] if isinstance(x, dict) else x) for idioma in IDIOMAS})
        linhas.append({"rotulo": {idioma: str(rotulo[idioma]) for idioma in IDIOMAS},
                       "itens": tuple(traduzidos)})
    return tuple(linhas)


def _ler_yaml(caminho: Path) -> dict:
    """O arquivo é editado à mão: YAML quebrado vira recusa que diz o arquivo e o que fazer, nunca erro 500."""
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise PerfilInvalido(f"{caminho.name} não abre ({str(exc).splitlines()[0]}): corrija à mão") from None
    if not isinstance(dados, dict):
        raise PerfilInvalido(f"{caminho.name} não abre (esperava chaves como `perfis:`): corrija à mão")
    return dados


def carregar_nomes(caminho: str | Path) -> dict[str, str]:
    """`nomes:` do yaml: slug da stack (`fastapi`) → como aparece no currículo (`FastAPI`)."""
    caminho = Path(caminho)
    if not caminho.is_file():
        return {}
    dados = _ler_yaml(caminho)
    nomes = dados.get("nomes") or {}
    if not isinstance(nomes, dict):
        raise PerfilInvalido(f"{caminho.name}: `nomes` precisa ser um mapa (`fastapi: FastAPI`), não uma lista")
    return {str(k): str(v) for k, v in nomes.items()}


def carregar(caminho: str | Path) -> list[PerfilCV]:
    """Lê `curriculos.yaml`. Arquivo ausente = nenhum perfil (o currículo geral continua)."""
    caminho = Path(caminho)
    if not caminho.is_file():
        return []
    dados = _ler_yaml(caminho)
    perfis, vistos = [], set()
    for i, item in enumerate(dados.get("perfis") or []):
        if item is not None and not isinstance(item, dict):
            raise PerfilInvalido(f"{caminho.name}: perfil #{i + 1} não é um item de lista com `slug:`")
        slug = str((item or {}).get("slug") or "").strip()
        if not slug:
            raise PerfilInvalido(f"{caminho.name}: perfil #{i + 1} sem `slug`")
        if slug in vistos:
            raise PerfilInvalido(f"perfil `{slug}` repetido")
        vistos.add(slug)
        cargo = item.get("cargo") or {}
        if not isinstance(cargo, dict) or any(not cargo.get(idioma) for idioma in IDIOMAS):
            raise PerfilInvalido(f"`{slug}`: `cargo` precisa de {list(IDIOMAS)}")
        projetos = item.get("projetos") or {}
        for chave, valor in (("competencias", item.get("competencias")), ("projetos", projetos)):
            if valor is not None and not isinstance(valor, dict):
                raise PerfilInvalido(f"`{slug}`: `{chave}` precisa ser um mapa (`chave: valor`), não uma lista")
        habilidades = _habilidades(slug, item.get("habilidades"))  # PerfilInvalido já diz o perfil
        try:
            perfis.append(PerfilCV(
                slug=slug,
                cargo={idioma: str(cargo[idioma]) for idioma in IDIOMAS},
                foco=str(item.get("foco") or "").strip(),
                competencias={str(k): float(v) for k, v in (item.get("competencias") or {}).items()},
                peso_fora_do_perfil=float(item.get("peso_fora_do_perfil", 0.5)),
                primeiro=tuple(projetos.get("primeiro") or ()),
                excluir=tuple(projetos.get("excluir") or ()),
                limite_fatos=int(item.get("limite_fatos", MAX_FATOS)),
                paginas=int(item.get("paginas", 1)),
                habilidades=habilidades,
            ))
        except (TypeError, ValueError) as exc:
            raise PerfilInvalido(f"`{slug}`: {exc}") from None
    return perfis


def validar(conn: sqlite3.Connection, perfis: list[PerfilCV]) -> None:
    """Competência que não existe na taxonomia é erro de digitação, não intenção."""
    existentes = {r["slug"] for r in conn.execute("SELECT slug FROM competencies")}
    for p in perfis:
        desconhecidas = sorted(set(p.competencias) - existentes)
        if desconhecidas:
            raise PerfilInvalido(
                f"`{p.slug}`: competência(s) fora da taxonomia: {', '.join(desconhecidas)}"
            )


def buscar(perfis: list[PerfilCV], slug: str) -> PerfilCV:
    for p in perfis:
        if p.slug == slug:
            return p
    disponiveis = ", ".join(p.slug for p in perfis) or "nenhum (crie curriculos.yaml)"
    raise PerfilInvalido(f"perfil `{slug}` não existe. Disponíveis: {disponiveis}")


def _slug(texto: str) -> str:
    import re
    import unicodedata

    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-") or "recorte"


def _inserir_no_bloco(texto: str, bloco: list[str], chave: str = "perfis") -> str:
    """Acrescenta os itens no fim da lista `<chave>:` sem reescrever nada do que já está no arquivo."""
    import re

    linhas = texto.splitlines(keepends=True)
    inicio = next((i for i, l in enumerate(linhas)
                   if re.match(rf"^{re.escape(chave)}:\s*(#.*)?$", l.rstrip("\n"))), None)
    if inicio is None:
        separador = "" if not texto or texto.endswith("\n\n") else ("\n" if texto.endswith("\n") else "\n\n")
        return texto + separador + f"{chave}:\n" + "".join("  " + l for l in bloco)
    # o bloco acaba na próxima chave de topo; item `- ` na coluna 0 (o estilo do `yaml.safe_dump`) ainda é da lista
    fim = next((j for j in range(inicio + 1, len(linhas))
                if linhas[j].strip() and not linhas[j][0].isspace() and not linhas[j].startswith(("#", "- "))),
               len(linhas))
    # o recuo dos itens que já existem (`  - slug:` ou `- slug:`)
    recuo = next((len(l) - len(l.lstrip()) for l in linhas[inicio + 1:fim] if l.lstrip().startswith("- ")), 2)
    ultimo = max((j for j in range(inicio, fim) if linhas[j].strip()), default=inicio)
    if not linhas[ultimo].endswith("\n"):
        linhas[ultimo] += "\n"
    novo = [" " * recuo + l for l in bloco]
    return "".join(linhas[: ultimo + 1] + novo + linhas[ultimo + 1 :])


def criar(
    caminho: str | Path,
    conn: sqlite3.Connection,
    *,
    cargo_pt: str,
    cargo_en: str,
    foco: str = "",
    competencias: dict[str, int],
    limite_fatos: int = MAX_FATOS,
    paginas: int = 1,
) -> PerfilCV:
    """Cria um recorte pela tela. Acrescenta no fim de `perfis:` e não reescreve o resto do arquivo:
    os seus comentários, o `nomes:` e a ordem continuam como você deixou. Só troca o arquivo depois de
    validar o resultado com o mesmo leitor do app; com erro, o arquivo original fica intacto."""
    import os
    import tempfile

    caminho = Path(caminho)
    cargo_pt, cargo_en = cargo_pt.strip(), cargo_en.strip()
    if not cargo_pt or not cargo_en:
        raise PerfilInvalido("o recorte precisa do cargo em português e em inglês")
    if not competencias:
        raise PerfilInvalido("escolha ao menos uma competência para o recorte")
    existentes = {r["slug"] for r in conn.execute("SELECT slug FROM competencies")}
    desconhecidas = sorted(set(competencias) - existentes)
    if desconhecidas:
        raise PerfilInvalido(f"competência(s) fora da taxonomia: {', '.join(desconhecidas)}")
    fora = [k for k, v in competencias.items() if not isinstance(v, int) or not 1 <= v <= 3]
    if fora:
        raise PerfilInvalido(f"peso de 1 a 3 (veja {', '.join(fora)})")
    if not 3 <= limite_fatos <= 30:
        raise PerfilInvalido("o limite de fatos vai de 3 a 30")
    if paginas not in (1, 2):
        raise PerfilInvalido("o currículo tem 1 ou 2 páginas")

    atuais = carregar(caminho)  # YAML quebrado já vira PerfilInvalido com o nome do arquivo
    nomes_antes = carregar_nomes(caminho)
    base = _slug(cargo_pt)
    slug, n = base, 2
    while any(p.slug == slug for p in atuais):
        slug, n = f"{base}-{n}", n + 1
    item = {"slug": slug, "cargo": {"pt": cargo_pt, "en": cargo_en}}
    if foco.strip():
        item["foco"] = foco.strip()
    item["competencias"] = dict(competencias)
    if limite_fatos != MAX_FATOS:
        item["limite_fatos"] = limite_fatos
    if paginas != 1:
        item["paginas"] = paginas
    bloco = yaml.safe_dump([item], allow_unicode=True, sort_keys=False, default_flow_style=False).splitlines(keepends=True)

    bruto = caminho.read_bytes() if caminho.is_file() else b""
    crlf = b"\r\n" in bruto  # quem editou no Windows continua com CRLF
    texto = bruto.decode("utf-8").replace("\r\n", "\n")
    novo = _inserir_no_bloco(texto, bloco)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=caminho.parent, prefix=".curriculos-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as f:
            f.write(novo)
        try:
            todos = carregar(temporario)
            nomes_depois = carregar_nomes(temporario)
        except PerfilInvalido as exc:
            # o arquivo de verdade está intacto; o motivo cita o temporário, que some daqui a pouco
            motivo = str(exc).replace(Path(temporario).name, caminho.name)
            raise PerfilInvalido(f"não deu para acrescentar o recorte sem mexer no resto do {caminho.name} ({motivo}); "
                                 "acrescente à mão no fim de `perfis:`") from None
        # só troca o arquivo se tudo o que já existia continua lá, na mesma ordem, e o recorte novo entrou por
        # último. Formato que o inseridor não entende (lista em estilo `[...]`, BOM, chave entre aspas) é recusado
        # com o arquivo intacto, em vez de esconder os recortes que você já tem
        if [p.slug for p in todos] != [p.slug for p in atuais] + [slug] or nomes_depois != nomes_antes:
            raise PerfilInvalido(f"não deu para acrescentar o recorte sem mexer no resto do {caminho.name}; "
                                 "acrescente à mão no fim de `perfis:`")
        validar(conn, todos)
        os.replace(temporario, caminho)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise
    return todos[-1]
