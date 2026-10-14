"""Vaga: extração dos requisitos, score de aderência e texto de lacunas e riscos.

Mesma divisão de trabalho do currículo. O modelo **lê** a vaga (extrai requisitos) e **escreve**
o comentário das lacunas; o score é calculado aqui, em Python, a partir do nível declarado de
cada competência. O modelo nunca dá a nota — e a fórmula vai gravada junto, para um número
antigo continuar legível depois que ela mudar.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from html.parser import HTMLParser

FORMULA = "v1"
BLOCK_REF_RE = re.compile(r"\^([A-Za-z0-9][A-Za-z0-9_-]*)")
PESO_TIPO = {"obrigatorio": 2, "desejavel": 1}
COBERTURA_NIVEL = {0: 0.00, 1: 0.25, 2: 0.60, 3: 0.85, 4: 1.00}
# nível a partir do qual o requisito pode ir para o currículo (exige evidência)
NIVEL_SUSTENTADO = 2

MIN_CHARS_TEXTO = 200  # menos que isso não é descrição de vaga
MIN_CHARS_URL = 500  # página que devolve menos que isso quase sempre precisa de JavaScript
TIMEOUT_URL = 15.0
TENTATIVAS_URL = 3  # 1 + 2 retries
STATUS = ("novo", "analisado", "aplicado", "descartado")
# "vaga boa": o corte de score da Início, de "Desde a sua última visita" e de Vagas. Um número só.
SCORE_BOM = 75
SEM_INFO = "(não informado)"


class VagaRecusada(Exception):
    """A vaga não pode ser processada. A mensagem diz o que fazer."""


class TextoBloqueado(VagaRecusada):
    """O texto contém termo da denylist e não pode sair da máquina."""


class PaginaSemTexto(VagaRecusada):
    """A URL respondeu, mas sem texto suficiente (página que exige JavaScript)."""


class FalhaDeRede(VagaRecusada):
    """A URL não respondeu depois das tentativas."""


# ------------------------------------------------------------------ texto bruto


def normalizar(texto: str) -> str:
    """O que o dedup compara: sem caixa e sem diferença de espaço ou quebra de linha."""
    return re.sub(r"\s+", " ", texto).strip().lower()


def hash_texto(texto: str) -> str:
    return hashlib.sha256(normalizar(texto).encode("utf-8")).hexdigest()


class _Extrator(HTMLParser):
    IGNORAR = {"script", "style", "noscript", "template", "svg", "head"}
    BLOCO = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []
        self._ignorando = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._ignorando += 1
        elif tag in self.BLOCO:
            self.partes.append("\n")
        if tag == "li" and not self._ignorando:
            self.partes.append("- ")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self._ignorando:
            self._ignorando -= 1
        elif tag in self.BLOCO:
            self.partes.append("\n")

    def handle_data(self, data):
        if not self._ignorando:
            self.partes.append(data)


def texto_de_html(html: str) -> str:
    """Texto legível de uma página: sem script, sem estilo, uma linha por bloco."""
    extrator = _Extrator()
    extrator.feed(html)
    linhas = (re.sub(r"[ \t\xa0]+", " ", l).strip() for l in "".join(extrator.partes).splitlines())
    return "\n".join(l for l in linhas if l and l != "-")


def baixar(url: str, timeout: float = TIMEOUT_URL, tentativas: int = TENTATIVAS_URL) -> str:
    """HTML da URL. Refaz em erro de rede e em 5xx; 4xx não adianta repetir."""
    import httpx
    from tenacity import (
        RetryError,
        retry,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential,
    )

    def transitorio(exc: BaseException) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code >= 500
        return isinstance(exc, httpx.TransportError)

    @retry(
        stop=stop_after_attempt(tentativas),
        wait=wait_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception(transitorio),
    )
    def _get() -> str:
        resposta = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "hermes/0.1 (agente pessoal de carreira)"},
        )
        resposta.raise_for_status()
        return resposta.text

    try:
        return _get()
    except RetryError as e:
        raise FalhaDeRede(f"{url} não respondeu em {tentativas} tentativas: {e.last_attempt.exception()}") from None
    except httpx.HTTPStatusError as e:
        raise FalhaDeRede(f"{url} respondeu {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise FalhaDeRede(f"{url}: {e}") from None


def _termo_bloqueado(texto: str, denylist) -> str | None:
    baixo = texto.lower()
    return next((t for t in denylist if t.lower() in baixo), None)


# -------------------------------------------------------------------- extração

SYSTEM_EXTRACAO = (
    "Você extrai requisitos de descrições de vaga. Responde só com JSON, sem comentário. "
    "Não inventa requisito que o texto não traz."
)

INSTRUCOES_EXTRACAO = """
Extraia da vaga acima e responda SÓ com este JSON:
{
  "empresa": "...", "titulo": "...",
  "senioridade": "estagio|junior|pleno|senior|null", "local": "remoto|hibrido|presencial|null",
  "requisitos": [
    {"texto": "Python básico", "tipo": "obrigatorio", "competencia_sugerida": "python", "confianca": 0.9}
  ]
}

Regras:
- Extraia TODO item das listas de requisitos e de diferenciais (must-have, nice-to-have,
  requisitos, desejável, "é um plus"): um item da lista vira um requisito, sem pular nenhum.
- `texto`: no idioma original da vaga, o mais próximo possível do texto dela. Não traduza.
- Um requisito por habilidade ou conhecimento. "Python, JavaScript ou C#" é UM requisito.
- `tipo`: "obrigatorio" para requisito; "desejavel" para diferencial, "é um plus", "desejável".
- Responsabilidades do cargo não são requisito — só entram se exigirem uma habilidade explícita.
- `competencia_sugerida`: um slug da lista abaixo, ou null se nenhum servir. Não crie slug.
- `confianca`: de 0 a 1, quão certo você está do mapeamento. null quando a competência for null.

Competências cadastradas (slug: nome):
"""


def _entrada_extracao(texto: str, competencias: list[dict]) -> str:
    catalogo = "\n".join(f"- {c['slug']}: {c['nome']}" for c in competencias) or "(nenhuma)"
    return f"<vaga>\n{texto}\n</vaga>\n{INSTRUCOES_EXTRACAO}{catalogo}\n"


def _limpar_extracao(bruto: dict, slugs: set[str], status) -> dict:
    """Aplica o contrato ao que o modelo devolveu. Nada do modelo entra no banco sem passar aqui."""
    requisitos = []
    sugeridos_fora = []
    for item in bruto.get("requisitos") or []:
        if not isinstance(item, dict) or not str(item.get("texto") or "").strip():
            status.add("requisito sem texto descartado")
            continue
        tipo = item.get("tipo")
        if tipo not in PESO_TIPO:
            # na dúvida, obrigatório: se for lacuna, pesa mais e não passa despercebida
            status.add(f"tipo `{tipo}` inválido; requisito tratado como obrigatório")
            tipo = "obrigatorio"
        sugestao = item.get("competencia_sugerida")
        sugestao = str(sugestao).strip() if sugestao else None
        if sugestao and sugestao.lower() in {"null", "none"}:
            sugestao = None
        if sugestao and sugestao not in slugs:
            sugeridos_fora.append(sugestao)
        try:
            confianca = float(item["confianca"]) if item.get("confianca") is not None else None
        except (TypeError, ValueError):
            confianca = None
        competencia = sugestao if sugestao in slugs else None
        if competencia is None:
            # confiança é do mapeamento: sem competência, não há o que medir
            confianca = None
        elif confianca is not None:
            confianca = min(max(confianca, 0.0), 1.0)
        requisitos.append(
            {
                "texto": str(item["texto"]).strip(),
                "tipo": tipo,
                "competencia": competencia,
                "sugestao": sugestao,
                "confianca": confianca,
            }
        )

    def campo(nome: str) -> str | None:
        valor = bruto.get(nome)
        valor = str(valor).strip() if valor is not None else ""
        return valor if valor and valor.lower() != "null" else None

    return {
        "empresa": campo("empresa"),
        "titulo": campo("titulo"),
        "senioridade": campo("senioridade"),
        "local": campo("local"),
        "requisitos": requisitos,
        "sugeridos_fora": sorted(set(sugeridos_fora)),
    }


def extrair(texto: str, competencias: list[dict], status, model: str | None = None) -> dict:
    """Uma chamada ao modelo, temperatura 0, JSON estruturado."""
    from hermes import llm
    from hermes.json_parse import extract_json_object

    bruto = llm.complete(
        SYSTEM_EXTRACAO,
        _entrada_extracao(texto, competencias),
        status=status,
        model=model,
        temperature=0,
        json_mode=True,
    )
    extracao = _limpar_extracao(
        extract_json_object(bruto, ("requisitos",)), {c["slug"] for c in competencias}, status
    )
    if not extracao["requisitos"]:
        status.add("o modelo não extraiu nenhum requisito")
    return extracao


# ----------------------------------------------------------------- persistência


def _existente(conn: sqlite3.Connection, hash_: str, url: str | None) -> int | None:
    linha = conn.execute(
        "SELECT id FROM jobs WHERE hash_texto = ? OR (? IS NOT NULL AND url = ?)",
        (hash_, url, url),
    ).fetchone()
    return linha["id"] if linha else None


def requisitos(conn: sqlite3.Connection, job_id: int) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT r.id, r.texto, r.tipo, r.confianca, c.slug AS competencia"
            " FROM job_requirements r LEFT JOIN competencies c ON c.id = r.competency_id"
            " WHERE r.job_id = ? ORDER BY r.id",
            (job_id,),
        )
    ]


def buscar(conn: sqlite3.Connection, job_id: int) -> dict:
    linha = conn.execute(
        "SELECT id, empresa, titulo, url, fonte, senioridade, local, status, coletado_em"
        " FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not linha:
        raise VagaRecusada(f"vaga {job_id} não existe (veja `quilha job list`)")
    return dict(linha)


def marcar_vista(conn: sqlite3.Connection, job_id: int) -> str:
    """Abrir a vaga tira o selo de "nova". Só `novo` muda: candidatada ou descartada fica como está."""
    buscar(conn, job_id)
    with conn:
        conn.execute("UPDATE jobs SET status = 'analisado' WHERE id = ? AND status = 'novo'", (job_id,))
    return conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]


def definir_status(conn: sqlite3.Connection, job_id: int, status: str) -> dict:
    """Descartar e desfazer: devolve o status anterior para o aviso poder voltar exatamente a ele."""
    if status not in STATUS:
        raise VagaRecusada(f"status `{status}` inválido; use {', '.join(STATUS)}")
    anterior = buscar(conn, job_id)["status"]
    with conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    return {"job_id": job_id, "status": status, "anterior": anterior}


def listar(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    """Vagas com o score ao vivo (fórmula determinística, sem gravar nada) e `nova` = nunca aberta."""
    sql = (
        "SELECT j.id, j.empresa, j.titulo, j.status, j.coletado_em, j.senioridade, j.local, j.url,"
        " (SELECT COUNT(*) FROM job_requirements r WHERE r.job_id = j.id) AS n_requisitos"
        " FROM jobs j"
    )
    params: list = []
    if status:
        sql += " WHERE j.status = ?"
        params.append(status)
    sql += " ORDER BY j.coletado_em DESC, j.id DESC"
    vagas = [dict(r) for r in conn.execute(sql, params)]
    por_vaga: dict[int, list[dict]] = {}
    # com status, só a cobertura das vagas desse status (não a de todas)
    filtro = "WHERE r.job_id IN (SELECT id FROM jobs WHERE status = ?)" if status else ""
    for r in conn.execute(COBERTURA_TODAS_SQL.format(filtro=filtro), params):
        por_vaga.setdefault(r["job_id"], []).append(_item_cobertura(r))
    for v in vagas:
        # sem requisitos extraídos não há nota: `None` ("—"), não 0, que pareceria "nada coberto"
        v["score"] = calcular_score(por_vaga[v["id"]])["score"] if v["n_requisitos"] else None
        v["nova"] = v["status"] == "novo"
    return vagas


def parse_job(
    conn: sqlite3.Connection,
    texto: str | None = None,
    url: str | None = None,
    *,
    empresa: str | None = None,
    titulo: str | None = None,
    status=None,
    model: str | None = None,
    denylist: tuple[str, ...] | list[str] = (),
) -> dict:
    """Texto colado ou URL → vaga gravada com os requisitos extraídos.

    A ordem importa para o bolso: dedup e denylist rodam **antes** da chamada ao modelo. Vaga
    repetida devolve a existente de graça; vaga com termo bloqueado nem sai da máquina.

    Para extrair de novo uma vaga já gravada, use `extrair_requisitos(job_id)`.
    """
    from hermes.db import store
    from hermes.run_status import RunStatus

    status = status if status is not None else RunStatus()
    if bool(texto) == bool(url):
        raise VagaRecusada("passe o texto da vaga ou a URL — um dos dois")

    fonte = "colado"
    if url:
        fonte = "url"
        texto = texto_de_html(baixar(url))
        if len(texto) < MIN_CHARS_URL:
            raise PaginaSemTexto(
                f"{url} devolveu só {len(texto)} caracteres de texto — a página provavelmente "
                "monta a vaga com JavaScript. Copie a descrição e cole o texto."
            )
    texto = texto.strip()
    if len(texto) < MIN_CHARS_TEXTO:
        raise VagaRecusada(
            f"texto com {len(texto)} caracteres; cole a descrição inteira da vaga"
            f" (mínimo {MIN_CHARS_TEXTO})"
        )

    if termo := _termo_bloqueado(texto, denylist):
        raise TextoBloqueado(f"o texto da vaga contém `{termo}`, que está na denylist")

    hash_ = hash_texto(texto)
    if (existente := _existente(conn, hash_, url)) is not None:
        vaga = buscar(conn, existente)
        return {**_resumo(vaga), "duplicada": True, "reextraida": False,
                "requisitos": requisitos(conn, existente), "sugeridos_fora": []}

    catalogo, ids = _catalogo(conn)
    extracao = extrair(texto, catalogo, status, model)

    with conn:
        cursor = conn.execute(
            "INSERT INTO jobs (empresa, titulo, url, fonte, senioridade, local, texto_bruto,"
            " hash_texto, coletado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                empresa or extracao["empresa"] or SEM_INFO,
                titulo or extracao["titulo"] or SEM_INFO,
                url,
                fonte,
                extracao["senioridade"],
                extracao["local"],
                texto,
                hash_,
                store.utcnow(),
            ),
        )
        job_id = cursor.lastrowid
        _gravar_requisitos(conn, job_id, extracao, ids)

    return _resultado(conn, job_id, extracao, status, reextraida=False)


def _catalogo(conn: sqlite3.Connection) -> tuple[list[dict], dict[str, int]]:
    catalogo = [dict(r) for r in conn.execute("SELECT id, slug, nome FROM competencies ORDER BY slug")]
    return catalogo, {c["slug"]: c["id"] for c in catalogo}


def _gravar_requisitos(conn: sqlite3.Connection, job_id: int, extracao: dict, ids: dict) -> None:
    conn.executemany(
        "INSERT INTO job_requirements (job_id, texto, tipo, competency_id, confianca)"
        " VALUES (?, ?, ?, ?, ?)",
        [
            (job_id, r["texto"], r["tipo"], ids.get(r["competencia"]), r["confianca"])
            for r in extracao["requisitos"]
        ],
    )


def _resultado(conn, job_id: int, extracao: dict, status, reextraida: bool) -> dict:
    sem_competencia = sum(1 for r in extracao["requisitos"] if r["competencia"] is None)
    if sem_competencia:
        status.add(
            f"{sem_competencia} requisito(s) sem competência cadastrada — mapeie com "
            "`quilha job map` ou acrescente a competência em competencias.yaml"
        )
    return {
        **_resumo(buscar(conn, job_id)),
        "duplicada": reextraida,  # a vaga já existia; só os requisitos são novos
        "reextraida": reextraida,
        "requisitos": requisitos(conn, job_id),
        "sugeridos_fora": extracao["sugeridos_fora"],
    }


def extrair_requisitos(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status=None,
    model: str | None = None,
    denylist: tuple[str, ...] | list[str] = (),
) -> dict:
    """(Re)extrai os requisitos de uma vaga gravada, a partir do texto **guardado**.

    Serve para as duas situações: vaga que o coletor trouxe sem requisitos (extração adiada para
    não gastar com vaga que você nem vai olhar) e vaga cuja extração saiu ruim. O texto guardado
    é a origem dos requisitos; é contra ele que a extração é feita. Os requisitos antigos saem
    inteiros — misturar duas extrações deixaria requisito duplicado. Custa uma chamada.
    """
    from hermes.run_status import RunStatus

    status = status if status is not None else RunStatus()
    buscar(conn, job_id)  # vaga inexistente recusa antes de gastar
    texto = conn.execute("SELECT texto_bruto FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
    # a denylist pode ter mudado depois que a vaga foi gravada
    if termo := _termo_bloqueado(texto, denylist):
        raise TextoBloqueado(f"o texto da vaga contém `{termo}`, que está na denylist")
    catalogo, ids = _catalogo(conn)
    anteriores = len(requisitos(conn, job_id))
    # competência com confiança NULL é a marca do `job map` (o modelo raramente omite a confiança)
    manuais = conn.execute(
        "SELECT COUNT(*) FROM job_requirements"
        " WHERE job_id = ? AND competency_id IS NOT NULL AND confianca IS NULL",
        (job_id,),
    ).fetchone()[0]

    extracao = extrair(texto, catalogo, status, model)
    if not extracao["requisitos"]:
        manter = "; os anteriores foram mantidos" if anteriores else ""
        raise VagaRecusada(f"a extração da vaga {job_id} veio sem requisitos{manter}")

    with conn:
        conn.execute("DELETE FROM job_requirements WHERE job_id = ?", (job_id,))
        _gravar_requisitos(conn, job_id, extracao, ids)
        # empresa e título do coletor ou do usuário valem mais que os do modelo; senioridade e
        # local só são preenchidos se estavam vazios
        conn.execute(
            "UPDATE jobs SET senioridade = COALESCE(senioridade, ?), local = COALESCE(local, ?),"
            # a avaliação anterior foi feita sobre outros requisitos: a vaga volta a pedir `match`
            " status = CASE status WHEN 'analisado' THEN 'novo' ELSE status END"
            " WHERE id = ?",
            (extracao["senioridade"], extracao["local"], job_id),
        )
    if manuais:
        status.add(f"{manuais} mapeamento(s) feitos com `job map` foram descartados na reextração")
    return _resultado(conn, job_id, extracao, status, reextraida=anteriores > 0)


def _resumo(vaga: dict) -> dict:
    return {"job_id": vaga["id"], "empresa": vaga["empresa"], "titulo": vaga["titulo"]}


def mapear(conn: sqlite3.Connection, requisito_id: int, slug: str | None) -> dict:
    """Liga (ou desliga, com `slug=None`) um requisito a uma competência. Custo zero."""
    linha = conn.execute("SELECT job_id FROM job_requirements WHERE id = ?", (requisito_id,)).fetchone()
    if not linha:
        raise VagaRecusada(f"requisito {requisito_id} não existe (veja `quilha job show`)")
    competency_id = None
    if slug:
        comp = conn.execute("SELECT id FROM competencies WHERE slug = ?", (slug,)).fetchone()
        if not comp:
            raise VagaRecusada(f"competência `{slug}` não existe (veja `quilha comp list`)")
        competency_id = comp["id"]
    with conn:
        # mapeamento feito por você não é palpite do modelo: a confiança deixa de fazer sentido
        conn.execute(
            "UPDATE job_requirements SET competency_id = ?, confianca = NULL WHERE id = ?",
            (competency_id, requisito_id),
        )
    return {"requisito_id": requisito_id, "job_id": linha["job_id"], "competencia": slug}


# ----------------------------------------------------------------------- score

COBERTURA_SQL = """
SELECT r.id, r.texto, r.tipo, c.slug, c.nome, v.nivel,
       (SELECT json_group_array(e.nota || '#' || e.block_id)
        FROM evidence e WHERE e.competency_id = c.id) AS evidencias
FROM job_requirements r
LEFT JOIN competencies c         ON c.id = r.competency_id
LEFT JOIN v_competency_current v ON v.id = r.competency_id
WHERE r.job_id = ?
ORDER BY r.tipo = 'desejavel', r.id
"""


# A mesma cobertura para todas as vagas de uma vez: a lista da tela Vagas mostra o score ao vivo de
# centenas de vagas do coletor sem uma consulta por vaga.
COBERTURA_TODAS_SQL = """
SELECT r.job_id, r.id, r.texto, r.tipo, c.slug, c.nome, v.nivel,
       (SELECT json_group_array(e.nota || '#' || e.block_id)
        FROM evidence e WHERE e.competency_id = c.id) AS evidencias
FROM job_requirements r
LEFT JOIN competencies c         ON c.id = r.competency_id
LEFT JOIN v_competency_current v ON v.id = r.competency_id
{filtro}
ORDER BY r.job_id, r.tipo = 'desejavel', r.id
"""


def _item_cobertura(r: sqlite3.Row) -> dict:
    nivel = r["nivel"] if r["slug"] else None
    return {
        "requisito_id": r["id"],
        "texto": r["texto"],
        "tipo": r["tipo"],
        "competencia": r["slug"],
        "nivel": nivel,
        "evidencias": json.loads(r["evidencias"]) if r["evidencias"] else [],
        "cobertura": COBERTURA_NIVEL[nivel or 0] if r["slug"] else 0.0,
    }


def cobertura(conn: sqlite3.Connection, job_id: int) -> list[dict]:
    """Requisito → competência → nível → evidências. Base do score e do relatório."""
    return [_item_cobertura(r) for r in conn.execute(COBERTURA_SQL, (job_id,))]


def calcular_score(itens: list[dict]) -> dict:
    """Fórmula v1 de `especificacoes.md` §5, com o N e a metodologia que o relatório imprime."""
    peso_total = sum(PESO_TIPO[i["tipo"]] for i in itens)
    coberto = sum(PESO_TIPO[i["tipo"]] * i["cobertura"] for i in itens)
    score = round(100 * coberto / peso_total) if peso_total else 0
    return {
        "score": score,
        "formula": FORMULA,
        "n_requisitos": len(itens),
        "mapeados": sum(1 for i in itens if i["competencia"]),
        "obrigatorios": sum(1 for i in itens if i["tipo"] == "obrigatorio"),
        # "descoberto" = não dá para afirmar no currículo: sem competência ou nível < 2
        "obrigatorios_descobertos": sum(
            1 for i in itens if i["tipo"] == "obrigatorio" and not _sustentado(i)
        ),
    }


def _sustentado(item: dict) -> bool:
    return bool(item["competencia"]) and (item["nivel"] or 0) >= NIVEL_SUSTENTADO


def _fonte_ou_motivo(item: dict) -> str:
    """O que o lado direito do requisito diz: as notas que sustentam, ou por que não sustenta."""
    if _sustentado(item):
        notas = sorted({e.split("#", 1)[0].rsplit("/", 1)[-1].removesuffix(".md") for e in item["evidencias"]})
        if not notas:  # coberto pelo nível declarado, sem nota ligada ainda
            return f"nível declarado: {item['nivel']} de 4"
        return f"{len(notas)} notas" if len(notas) > 2 else ", ".join(notas)
    if not item["competencia"]:
        return "sem competência ligada"
    if item["nivel"] is None:
        return "falta declarar o nível" if item["evidencias"] else "sem evidência no vault"
    return f"seu nível: {item['nivel']} de 4"


def avaliacao(conn: sqlite3.Connection, job_id: int) -> dict:
    """Leitura ao vivo para a tela: score da fórmula, quantos requisitos o vault sustenta e o porquê de cada um."""
    itens = cobertura(conn, job_id)
    return {
        "score": calcular_score(itens)["score"] if itens else None,  # sem requisitos, sem nota (como a lista)
        "cobertos": sum(1 for i in itens if _sustentado(i)),
        "total": len(itens),
        "requisitos": [
            {"id": i["requisito_id"], "texto": i["texto"], "tipo": i["tipo"], "competencia": i["competencia"],
             "coberto": _sustentado(i), "fonte": _fonte_ou_motivo(i)}
            for i in itens
        ],
    }


def lacunas(itens: list[dict]) -> list[dict]:
    """Determinístico: o que a vaga pede e o vault não sustenta, com o motivo."""
    saida = []
    for i in itens:
        if _sustentado(i):
            continue
        if not i["competencia"]:
            motivo = "não mapeado"
        elif i["nivel"] is None:
            motivo = "nível nunca avaliado"
        else:
            motivo = f"nível {i['nivel']}"
        saida.append(
            {"requisito_id": i["requisito_id"], "texto": i["texto"], "tipo": i["tipo"],
             "competencia": i["competencia"], "motivo": motivo}
        )
    return saida


# ---------------------------------------------------------------------- match

SYSTEM_MATCH = (
    "Você é um avaliador técnico honesto preparando um candidato para entrevista. "
    "Responde só com JSON. Não inventa experiência que a cobertura não mostra."
)

INSTRUCOES_MATCH = """
A cobertura acima foi calculada pelo sistema a partir das evidências do candidato. Não recalcule
nem conteste o score. Escreva, SÓ neste JSON:
{
  "lacunas": {"<requisito_id>": "a menor ação concreta e verificável para fechar"},
  "riscos": ["o ponto que um entrevistador ou recrutador usaria contra o candidato"]
}

Regras de `lacunas` (só para os requisito_id listados como lacuna; no máximo 25 palavras cada):
- Lacuna com evidência já ligada: só falta o candidato declarar o nível. A ação é essa
  (ex.: "declarar o nível; ^<id da evidência> já sustenta"). Não mande estudar.
- Lacuna com fatos candidatos: o candidato provavelmente já tem, só não registrou. A ação é
  conferir e ligar o fato citado (ex.: "ligar ^<id do fato> como evidência e declarar o nível").
  Não mande estudar o que o fato já mostra.
- Só cite um ^block-id que apareça na própria lacuna. Lacuna sem evidência nem candidato não
  tem block-id para citar.
- Demais lacunas: uma ação que produz prova (um projeto, um repositório, uma nota no vault), não
  "estudar o tema", "participar de discussões" ou "buscar experiência".

Regras de `riscos` (de 2 a 5 itens):
- Comece pelos possíveis bloqueios: requisito obrigatório de tempo de experiência, idioma,
  formação ou senioridade é o primeiro filtro de um recrutador. Diga o requisito e por que pesa.
- Depois, o que o candidato AFIRMA ter (nível ≥ 2): a pergunta técnica que testaria isso.
- Não invente experiência do candidato: você só sabe o que está na cobertura.
"""


def _entrada_match(vaga: dict, itens: list[dict], faltas: list[dict]) -> str:
    linhas = [f"Vaga: {vaga['titulo']} — {vaga['empresa']}", "", "Cobertura:"]
    for i in itens:
        nivel = "—" if i["nivel"] is None else i["nivel"]
        linhas.append(
            f"- [{i['requisito_id']}] ({i['tipo']}) {i['texto']} → "
            f"{i['competencia'] or 'sem competência'}, nível {nivel}, "
            f"{len(i['evidencias'])} evidência(s)"
        )
    linhas += ["", "Lacunas:"]
    for f in faltas:
        extra = ""
        if f.get("ligadas"):
            extra = " · evidência já ligada: " + ", ".join(f"^{b}" for b in f["ligadas"])
        elif f.get("candidatos"):
            extra = " · fatos candidatos: " + "; ".join(
                f"^{c['block_id']} ({c['texto'][:80]})" for c in f["candidatos"])
        linhas.append(f"- [{f['requisito_id']}] {f['motivo']}{extra}")
    if not faltas:
        linhas.append("nenhuma")
    bloqueios = bloqueios_possiveis(itens)
    linhas += ["", "Possíveis bloqueios (obrigatórios sem competência que os cubra):"]
    linhas += [f"- [{b['requisito_id']}] {b['texto']}" for b in bloqueios] or ["nenhum"]
    return "\n".join(linhas) + "\n" + INSTRUCOES_MATCH


def bloqueios_possiveis(itens: list[dict]) -> list[dict]:
    """Obrigatório sem competência mapeada: tempo de experiência, idioma, formação costumam cair
    aqui. O sistema não sabe julgar; só aponta para o modelo e para você olharem primeiro."""
    return [i for i in itens if i["tipo"] == "obrigatorio" and not i["competencia"]]


def redigir_match(vaga: dict, itens: list[dict], faltas: list[dict], status, model=None) -> dict:
    """Uma chamada, só texto. Comentário para lacuna que não existe é descartado com aviso."""
    from hermes import llm
    from hermes.json_parse import extract_json_object

    bruto = llm.complete(
        SYSTEM_MATCH,
        _entrada_match(vaga, itens, faltas),
        status=status,
        model=model,
        temperature=0.2,
        json_mode=True,
    )
    resposta = extract_json_object(bruto, ("lacunas", "riscos"))

    por_id = {str(f["requisito_id"]): f for f in faltas}
    # `^12` escrito pelo modelo é o id do requisito, não um block id: não é citação de fato
    ids_requisitos = {str(i["requisito_id"]) for i in itens}
    comentarios = {}
    for chave, texto in (resposta.get("lacunas") or {}).items():
        falta = por_id.get(str(chave))
        if falta is None or not isinstance(texto, str) or not texto.strip():
            status.add(f"comentário ignorado para requisito que não é lacuna: `{chave}`")
            continue
        # o modelo só pode citar o que o sistema mostrou para aquela lacuna
        permitidos = set(falta.get("ligadas") or []) | {
            c["block_id"] for c in falta.get("candidatos") or []}
        inventados = set(BLOCK_REF_RE.findall(texto)) - permitidos - ids_requisitos
        if inventados:
            status.add(
                f"comentário da lacuna {chave} descartado: cita "
                f"{', '.join('^' + b for b in sorted(inventados))}, que não sustenta essa lacuna"
            )
            continue
        comentarios[str(chave)] = texto.strip()
    riscos = [str(r).strip() for r in resposta.get("riscos") or [] if str(r).strip()]
    return {"comentarios": comentarios, "riscos": riscos}


def match_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    redigir: bool = True,
    status=None,
    model: str | None = None,
) -> dict:
    """Score determinístico + (opcional) uma chamada para o texto. Grava em `job_matches`."""
    from hermes.db import store
    from hermes.run_status import RunStatus

    status = status if status is not None else RunStatus()
    vaga = buscar(conn, job_id)
    itens = cobertura(conn, job_id)
    if not itens:
        raise VagaRecusada(f"vaga {job_id} não tem requisitos extraídos; nada a avaliar")

    placar = calcular_score(itens)
    faltas = lacunas(itens)
    from hermes.domain import competencias

    evidencias_por_req = {i["requisito_id"]: i["evidencias"] for i in itens}
    for f in faltas:
        # nunca avaliada, mas com evidência ligada ou fato no vault que parece sustentar:
        # lacuna de registro, não de estudo
        if f["motivo"] != "nível nunca avaliado":
            continue
        if ligadas := evidencias_por_req[f["requisito_id"]]:
            f["motivo"] = f"nível nunca declarado ({len(ligadas)} evidência(s) já ligada(s))"
            f["ligadas"] = [r.split("#", 1)[1] for r in ligadas]
        elif candidatos := competencias.fatos_candidatos(conn, f["competencia"]):
            f["candidatos"] = candidatos
    riscos: list[str] = []
    usou_modelo = custo = None
    if redigir:
        from hermes import llm

        antes = status.cost_usd
        texto = redigir_match(vaga, itens, faltas, status, model)
        for f in faltas:
            if comentario := texto["comentarios"].get(str(f["requisito_id"])):
                f["comentario"] = comentario
        riscos = texto["riscos"]
        usou_modelo = model or llm.current_model()
        # no chat o status acumula o turno inteiro: grava só o que esta chamada custou
        depois = status.cost_usd
        custo = None if antes is None or depois is None else depois - antes

    with conn:
        conn.execute(
            "INSERT INTO job_matches (job_id, score, formula, cobertura, lacunas, riscos, model,"
            " cost_usd, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                placar["score"],
                placar["formula"],
                json.dumps(itens, ensure_ascii=False),
                json.dumps(faltas, ensure_ascii=False),
                json.dumps(riscos, ensure_ascii=False),
                usou_modelo,
                custo,
                store.utcnow(),
            ),
        )
        conn.execute(
            "UPDATE jobs SET status = 'analisado' WHERE id = ? AND status = 'novo'", (job_id,)
        )

    return {**_resumo(vaga), **placar, "cobertura": itens, "lacunas": faltas, "riscos": riscos}
