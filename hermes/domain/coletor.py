"""Coletor de vagas: ATS públicos, com fila, retries, backoff, dedup e robots.txt.

O fluxo de uma execução de `quilha job collect`:

1. **Enfileira**: cada fonte de `fontes.yaml` ganha (ou mantém) uma linha em `fila_coleta`.
2. **Seleciona**: só a fonte cujo `proximo_em` já passou. Fonte que falhou espera um backoff que
   cresce a cada falha seguida (15 min, 30 min, 1 h... até 12 h) — entre execuções, não só dentro.
3. **Coleta**: confere o `robots.txt` do host, busca a API com timeout e 2 retries (erro de rede e
   5xx), normaliza a vaga, filtra pelo título e deduplica por URL e por hash do texto.
4. **Registra**: uma linha em `coletas` por fonte, com vistas, filtradas, novas e duplicadas.

Vaga coletada entra **sem** requisitos: a extração custa uma chamada ao modelo e fica para quando
você pedir (`quilha job extrair <id>`, ou `--extrair N` no próprio collect).

Fontes: Greenhouse e Lever têm API pública de vagas, feita para ser consumida. A Gupy não tem API
pública, mas a página de carreiras (`<empresa>.gupy.io`) é Next.js renderizado no servidor: a lista
de vagas e a descrição de cada uma vêm no JSON `__NEXT_DATA__` do HTML. Não precisa de navegador —
uma requisição para a lista e uma por vaga que passou no filtro, com pausa entre elas e teto por
execução. LinkedIn fica de fora: proíbe acesso automatizado.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import yaml

from hermes.domain import vaga

FONTES = ("greenhouse", "lever", "gupy")
INTERVALO_PADRAO_H = 24
BACKOFF_BASE = timedelta(minutes=15)
BACKOFF_MAX = timedelta(hours=12)
AVISO_FALHAS = 5  # falhas seguidas a partir das quais o aviso pede para conferir a fonte
USER_AGENT = "hermes"  # nome que o robots.txt enxerga
GUPY_MAX_VAGAS = 25  # páginas de vaga baixadas por fonte e execução; o resto fica para a próxima
GUPY_PAUSA_S = 1.0  # entre páginas de vaga do mesmo host
GUPY_TIPOS_IGNORADOS = {"vacancy_type_talent_pool"}  # banco de talentos: não é vaga aberta


class ColetaRecusada(Exception):
    """Configuração inválida. A mensagem diz o que corrigir em `fontes.yaml`."""


class FonteBloqueada(Exception):
    """O robots.txt do host não permite a URL."""


@dataclass(frozen=True)
class Fonte:
    fonte: str
    board: str
    empresa: str
    intervalo_h: int = INTERVALO_PADRAO_H
    incluir: tuple[str, ...] = ()
    excluir: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        if self.fonte == "greenhouse":
            return f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        if self.fonte == "gupy":
            return f"https://{self.board}.gupy.io/"
        return f"https://api.lever.co/v0/postings/{self.board}?mode=json"


# -------------------------------------------------------------------- config


def _termos(valor) -> tuple[str, ...]:
    if valor is None:
        return ()
    if isinstance(valor, str):
        valor = [valor]
    return tuple(_normalizar(str(t)) for t in valor if str(t).strip())


def carregar_fontes(caminho: Path) -> list[Fonte]:
    """Lê `fontes.yaml`. Filtro global vale para toda fonte que não definir o seu."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ColetaRecusada(
            f"{caminho.name} não existe. Copie fontes.example.yaml para {caminho.name} e liste os "
            "boards das empresas que você acompanha."
        )
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    filtro_global = dados.get("filtro") or {}
    fontes, vistos = [], set()
    for i, item in enumerate(dados.get("fontes") or [], 1):
        if not isinstance(item, dict):
            raise ColetaRecusada(f"fonte {i}: esperado um mapa com `tipo`, `board` e `empresa`")
        tipo, board = item.get("tipo"), str(item.get("board") or "").strip()
        if tipo not in FONTES:
            raise ColetaRecusada(f"fonte {i}: `tipo` deve ser um de {list(FONTES)}, veio `{tipo}`")
        if not board or "/" in board or " " in board:
            raise ColetaRecusada(f"fonte {i}: `board` inválido: `{board}`")
        if (tipo, board) in vistos:
            raise ColetaRecusada(f"fonte {i}: {tipo}/{board} repetida")
        vistos.add((tipo, board))
        filtro = item.get("filtro") or filtro_global
        intervalo = int(item.get("intervalo_h", dados.get("intervalo_h", INTERVALO_PADRAO_H)))
        if intervalo < 1:
            raise ColetaRecusada(f"fonte {i}: `intervalo_h` mínimo é 1")
        fontes.append(Fonte(
            fonte=tipo,
            board=board,
            empresa=str(item.get("empresa") or board),
            intervalo_h=intervalo,
            incluir=_termos(filtro.get("incluir")),
            excluir=_termos(filtro.get("excluir")),
        ))
    return fontes


# ------------------------------------------------------------------ filtro


def _normalizar(texto: str) -> str:
    """Sem acento e sem caixa: "Júnior" casa com "junior"."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.lower().split())


def passa_no_filtro(titulo: str, fonte: Fonte) -> bool:
    """Título precisa ter um termo de `incluir` (se houver) e nenhum de `excluir`."""
    t = _normalizar(titulo)
    if fonte.excluir and any(termo in t for termo in fonte.excluir):
        return False
    return not fonte.incluir or any(termo in t for termo in fonte.incluir)


# --------------------------------------------------------------- normalização


def _vaga_greenhouse(item: dict) -> dict:
    # a Greenhouse devolve o HTML da descrição escapado (&lt;p&gt;): desescapa antes de extrair
    conteudo = vaga.texto_de_html(html.unescape(item.get("content") or ""))
    return {
        "titulo": str(item.get("title") or "").strip(),
        "url": item.get("absolute_url"),
        "local": ((item.get("location") or {}).get("name") or None),
        "texto": conteudo,
    }


def _vaga_lever(item: dict) -> dict:
    partes = [item.get("descriptionPlain") or ""]
    for lista in item.get("lists") or []:
        partes.append(str(lista.get("text") or ""))
        partes.append(vaga.texto_de_html(lista.get("content") or ""))
    partes.append(item.get("additionalPlain") or "")
    categorias = item.get("categories") or {}
    return {
        "titulo": str(item.get("text") or "").strip(),
        "url": item.get("hostedUrl"),
        "local": categorias.get("location") or None,
        "texto": "\n".join(p.strip() for p in partes if p and p.strip()),
    }


def normalizar_resposta(fonte: str, corpo: str) -> list[dict]:
    """JSON da API → vagas no formato do Hermes. Formato inesperado é erro, não lista vazia."""
    try:
        dados = json.loads(corpo)
    except json.JSONDecodeError as e:
        raise ValueError(f"resposta não é JSON: {e}") from None
    if fonte == "greenhouse":
        if not isinstance(dados, dict) or not isinstance(dados.get("jobs"), list):
            raise ValueError("resposta da Greenhouse sem a lista `jobs`")
        itens = [_vaga_greenhouse(i) for i in dados["jobs"]]
    else:
        if not isinstance(dados, list):
            raise ValueError("resposta da Lever não é uma lista")
        itens = [_vaga_lever(i) for i in dados]
    return [i for i in itens if i["titulo"] and i["url"] and i["texto"]]


def _next_data(pagina: str) -> dict:
    """`pageProps` do JSON que o Next.js embute no HTML. Sem ele, a página mudou de formato."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', pagina, re.DOTALL)
    if not m:
        raise ValueError("página da Gupy sem `__NEXT_DATA__` (o formato mudou?)")
    try:
        return json.loads(m.group(1))["props"]["pageProps"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ValueError(f"`__NEXT_DATA__` da Gupy ilegível: {e}") from None


def _local_gupy(workplace: dict | None) -> str | None:
    workplace = workplace or {}
    if workplace.get("workplaceType") == "remote":
        return "Remoto"
    endereco = workplace.get("address") or {}
    partes = [p for p in (endereco.get("city"), endereco.get("stateShortName")) if p]
    return "/".join(partes) or None


def listar_gupy(pagina: str, board: str) -> list[dict]:
    """Página de carreiras → vagas sem texto (a descrição exige uma requisição por vaga)."""
    vagas = _next_data(pagina).get("jobs")
    if not isinstance(vagas, list):
        raise ValueError("página de carreiras da Gupy sem a lista `jobs`")
    itens = []
    for v in vagas:
        if v.get("type") in GUPY_TIPOS_IGNORADOS or not v.get("id"):
            continue
        itens.append({
            "titulo": " ".join(str(v.get("title") or "").split()),
            "url": f"https://{board}.gupy.io/jobs/{v['id']}",
            "local": _local_gupy(v.get("workplace")),
        })
    return [i for i in itens if i["titulo"]]


def texto_vaga_gupy(pagina: str) -> str:
    """Página da vaga → texto: descrição, responsabilidades, requisitos e informações adicionais."""
    vaga_ = _next_data(pagina).get("job")
    if not isinstance(vaga_, dict):
        raise ValueError("página de vaga da Gupy sem `job`")
    partes = []
    for campo, titulo in (("description", None), ("responsibilities", "Responsabilidades"),
                          ("prerequisites", "Requisitos"), ("relevantExperiences", "Informações adicionais")):
        texto = vaga.texto_de_html(vaga_.get(campo) or "")
        if texto:
            partes.extend([titulo, texto] if titulo else [texto])
    return "\n".join(partes)


# ------------------------------------------------------------------ robots


@dataclass
class Robots:
    """Cache de robots.txt por host, válido durante uma execução."""

    cache: dict[str, RobotFileParser | None] = field(default_factory=dict)

    def permite(self, url: str) -> bool:
        partes = urlsplit(url)
        host = f"{partes.scheme}://{partes.netloc}"
        if host not in self.cache:
            self.cache[host] = self._ler(host)
        regras = self.cache[host]
        return True if regras is None else regras.can_fetch(USER_AGENT, url)

    @staticmethod
    def _ler(host: str) -> RobotFileParser | None:
        import httpx

        try:
            resposta = httpx.get(f"{host}/robots.txt", timeout=10, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            # sem conseguir ler as regras, não dá para afirmar que é permitido
            raise vaga.FalhaDeRede(f"robots.txt de {host} inacessível: {e}") from None
        if resposta.status_code in (401, 403):
            raise FonteBloqueada(f"{host} recusa até o robots.txt ({resposta.status_code})")
        if resposta.status_code >= 400:
            return None  # sem robots.txt: nada proibido (RFC 9309)
        texto = resposta.text
        # a Gupy serve o robots.txt como página HTML com as regras dentro de um <pre>; lido cru,
        # nenhuma linha começa com `User-agent` e toda regra seria ignorada
        pre = re.search(r"<pre[^>]*>(.*?)</pre>", texto, re.DOTALL | re.IGNORECASE)
        if pre:
            texto = html.unescape(pre.group(1))
        regras = RobotFileParser()
        regras.parse(texto.splitlines())
        return regras


# -------------------------------------------------------------------- fila


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def backoff(falhas: int) -> timedelta:
    """15 min na 1ª falha seguida, dobrando a cada nova falha, até 12 h."""
    return min(BACKOFF_BASE * (2 ** max(falhas - 1, 0)), BACKOFF_MAX)


def enfileirar(conn: sqlite3.Connection, fontes: list[Fonte]) -> None:
    agora = _agora().isoformat()
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO fila_coleta (fonte, board, proximo_em, atualizado_em)"
            " VALUES (?, ?, ?, ?)",
            [(f.fonte, f.board, agora, agora) for f in fontes],
        )


def devidas(conn: sqlite3.Connection, fontes: list[Fonte], forcar: bool = False) -> list[Fonte]:
    """Fontes cuja hora chegou. Fonte que saiu do `fontes.yaml` fica na fila, mas é ignorada."""
    agora = _agora().isoformat()
    prontas = {
        (r["fonte"], r["board"])
        for r in conn.execute("SELECT fonte, board, proximo_em FROM fila_coleta")
        if forcar or r["proximo_em"] <= agora
    }
    return [f for f in fontes if (f.fonte, f.board) in prontas]


def _marcar(conn, fonte: Fonte, ok: bool, erro: str | None = None) -> int:
    agora = _agora()
    linha = conn.execute(
        "SELECT tentativas FROM fila_coleta WHERE fonte = ? AND board = ?", (fonte.fonte, fonte.board)
    ).fetchone()
    falhas = 0 if ok else linha["tentativas"] + 1
    proximo = agora + (timedelta(hours=fonte.intervalo_h) if ok else backoff(falhas))
    with conn:
        conn.execute(
            "UPDATE fila_coleta SET estado = ?, tentativas = ?, proximo_em = ?, ultimo_erro = ?,"
            " ultima_ok_em = CASE WHEN ? THEN ? ELSE ultima_ok_em END, atualizado_em = ?"
            " WHERE fonte = ? AND board = ?",
            ("ok" if ok else "falhou", falhas, proximo.isoformat(), erro, ok, agora.isoformat(),
             agora.isoformat(), fonte.fonte, fonte.board),
        )
    return falhas


# ------------------------------------------------------------------ coleta


def _gravar(conn: sqlite3.Connection, fonte: Fonte, itens: list[dict]) -> tuple[int, int, list[int]]:
    """Insere as vagas novas. Devolve (novas, duplicadas, ids novos)."""
    from hermes.db import store

    novas, duplicadas, ids = 0, 0, []
    agora = store.utcnow()
    with conn:
        for item in itens:
            hash_ = vaga.hash_texto(item["texto"])
            if vaga._existente(conn, hash_, item["url"]) is not None:
                duplicadas += 1
                continue
            cursor = conn.execute(
                "INSERT INTO jobs (empresa, titulo, url, fonte, local, texto_bruto, hash_texto,"
                " coletado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (fonte.empresa, item["titulo"], item["url"], fonte.fonte, item["local"],
                 item["texto"], hash_, agora),
            )
            novas += 1
            ids.append(cursor.lastrowid)
    return novas, duplicadas, ids


def _detalhar_gupy(
    conn: sqlite3.Connection, fonte: Fonte, filtradas: list[dict], robots: Robots, status
) -> tuple[list[dict], int]:
    """Baixa a página de cada vaga filtrada que ainda não está no banco.

    Vaga cuja URL já existe conta como duplicada sem gastar requisição. Uma página que falha vira
    aviso e fica para a próxima coleta; só quando todas falham a fonte inteira falha.
    """
    ja_vistas, pendentes = 0, []
    for item in filtradas:
        if conn.execute("SELECT 1 FROM jobs WHERE url = ?", (item["url"],)).fetchone():
            ja_vistas += 1
        else:
            pendentes.append(item)
    if len(pendentes) > GUPY_MAX_VAGAS:
        status.add(f"gupy/{fonte.board}: {len(pendentes) - GUPY_MAX_VAGAS} vaga(s) ficaram para a"
                   f" próxima coleta (teto de {GUPY_MAX_VAGAS} por execução)")
        pendentes = pendentes[:GUPY_MAX_VAGAS]

    com_texto, erros = [], []
    for n, item in enumerate(pendentes):
        if n:
            time.sleep(GUPY_PAUSA_S)
        try:
            if not robots.permite(item["url"]):
                raise FonteBloqueada(f"robots.txt não permite {item['url']}")
            texto = texto_vaga_gupy(vaga.baixar(item["url"]))
        except (vaga.VagaRecusada, ValueError) as e:
            erros.append(str(e))
            continue
        if texto:
            com_texto.append({**item, "texto": texto})
        else:
            erros.append(f"{item['url']} sem descrição")
    if erros and not com_texto:
        raise vaga.FalhaDeRede(f"nenhuma das {len(pendentes)} vaga(s) baixou: {erros[0]}")
    if erros:
        status.add(f"gupy/{fonte.board}: {len(erros)} vaga(s) não baixaram, ficam para a próxima"
                   f" coleta ({erros[0]})")
    return com_texto, ja_vistas


def coletar_fonte(
    conn: sqlite3.Connection, fonte: Fonte, execucao: str, robots: Robots, status
) -> dict:
    """Uma fonte, do robots.txt ao registro. Falha vira linha `falhou`, nunca exceção."""
    from hermes.db import store

    inicio = time.monotonic()
    resultado = {"fonte": fonte.fonte, "board": fonte.board, "status": "ok", "vagas_vistas": None,
                 "vagas_filtradas": None, "vagas_novas": None, "duplicadas": None, "erro": None,
                 "ids_novos": []}
    try:
        if not robots.permite(fonte.url):
            raise FonteBloqueada(f"robots.txt de {urlsplit(fonte.url).netloc} não permite {fonte.url}")
        if fonte.fonte == "gupy":
            itens = listar_gupy(vaga.baixar(fonte.url), fonte.board)
            filtradas = [i for i in itens if passa_no_filtro(i["titulo"], fonte)]
            com_texto, ja_vistas = _detalhar_gupy(conn, fonte, filtradas, robots, status)
        else:
            itens = normalizar_resposta(fonte.fonte, vaga.baixar(fonte.url))
            filtradas = [i for i in itens if passa_no_filtro(i["titulo"], fonte)]
            com_texto, ja_vistas = filtradas, 0
        novas, duplicadas, ids = _gravar(conn, fonte, com_texto)
        resultado.update(vagas_vistas=len(itens), vagas_filtradas=len(filtradas),
                         vagas_novas=novas, duplicadas=duplicadas + ja_vistas, ids_novos=ids)
        _marcar(conn, fonte, ok=True)
    except FonteBloqueada as e:
        resultado.update(status="bloqueada", erro=str(e))
        falhas = _marcar(conn, fonte, ok=False, erro=str(e))
        status.add(f"{fonte.fonte}/{fonte.board}: {e}")
    except (vaga.VagaRecusada, ValueError) as e:
        resultado.update(status="falhou", erro=str(e))
        falhas = _marcar(conn, fonte, ok=False, erro=str(e))
        aviso = f"{fonte.fonte}/{fonte.board}: {e}"
        if falhas >= AVISO_FALHAS:
            aviso += f" — {falhas} falhas seguidas; confira o board em fontes.yaml"
        status.add(aviso)

    resultado["duracao_ms"] = int((time.monotonic() - inicio) * 1000)
    with conn:
        conn.execute(
            "INSERT INTO coletas (execucao, fonte, board, status, vagas_vistas, vagas_filtradas,"
            " vagas_novas, duplicadas, duracao_ms, erro, criado_em)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (execucao, fonte.fonte, fonte.board, resultado["status"], resultado["vagas_vistas"],
             resultado["vagas_filtradas"], resultado["vagas_novas"], resultado["duplicadas"],
             resultado["duracao_ms"], resultado["erro"], store.utcnow()),
        )
    return resultado


def coletar(
    conn: sqlite3.Connection,
    fontes: list[Fonte],
    execucao: str,
    status,
    forcar: bool = False,
    robots: Robots | None = None,
) -> dict:
    """Processa a fila. Uma fonte que falha não impede as outras."""
    enfileirar(conn, fontes)
    alvo = devidas(conn, fontes, forcar)
    robots = robots or Robots()
    resultados = [coletar_fonte(conn, f, execucao, robots, status) for f in alvo]
    return {
        "fontes": len(fontes),
        "processadas": len(alvo),
        "adiadas": len(fontes) - len(alvo),
        "ok": sum(1 for r in resultados if r["status"] == "ok"),
        "vagas_novas": sum(r["vagas_novas"] or 0 for r in resultados),
        "ids_novos": [i for r in resultados for i in r["ids_novos"]],
        "resultados": resultados,
    }


def fila(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT fonte, board, estado, tentativas, proximo_em, ultima_ok_em, ultimo_erro"
        " FROM fila_coleta ORDER BY fonte, board"
    )]
