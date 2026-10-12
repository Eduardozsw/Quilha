"""Competências: taxonomia, evidência e nível.

A regra que segura tudo: **nível não sobe sem evidência**. Cada evidência aponta
para um fato do vault pelo block id, então o currículo só pode afirmar o que a
nota sustenta. Se o fato sumir do vault, a evidência vira órfã e aparece no
`hermes check` — nunca é apagada em silêncio.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import yaml

from hermes.db import store
from hermes.vault.check import tem_metrica as fato_tem_metrica
from hermes.vault.check import tem_periodo as fato_tem_periodo

CATEGORIAS = ("linguagem", "dados", "automacao", "ia", "processo", "idioma", "soft")
# como a tela chama cada categoria
NOMES_CATEGORIAS = {
    "linguagem": "Linguagem e ferramenta",
    "dados": "Dados",
    "automacao": "Automação",
    "ia": "IA",
    "processo": "Processo",
    "idioma": "Idioma",
    "soft": "Comportamental",
}

# O que cada nível exige de evidência (`hermes comp niveis` mostra a escala).
NIVEIS = {
    0: "nunca usei",
    1: "li, fiz tutorial, não entreguei nada",
    2: "usei em projeto próprio que roda",
    3: "entreguei e mantive; sei explicar decisões e limitações",
    4: "rodou em contexto real, com operação e gente dependendo",
}


class RegraViolada(Exception):
    """Pedido recusado por violar uma regra do domínio. Mensagem vai para o usuário."""


class CompetenciaDuplicada(RegraViolada):
    """Já existe uma competência com esse nome (ou com o mesmo slug)."""


def seed(conn: sqlite3.Connection, caminho: str | Path) -> tuple[int, int]:
    """Carrega a taxonomia do YAML. Idempotente por slug: cria ou atualiza."""
    nome = Path(caminho).name
    try:
        dados = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RegraViolada(f"{nome} não abre ({str(exc).splitlines()[0]}): corrija à mão") from None
    if not isinstance(dados, dict):
        raise RegraViolada(f"{nome} não abre (esperava a chave `competencias:`): corrija à mão")
    itens = dados.get("competencias") or []
    for i, item in enumerate(itens):
        if not isinstance(item, dict) or not all(str(item.get(k) or "").strip() for k in ("slug", "nome", "categoria")):
            raise RegraViolada(f"{nome}: o item #{i + 1} de `competencias` precisa de `slug:`, `nome:` e `categoria:`")
    criadas = atualizadas = 0
    agora = store.utcnow()
    with conn:
        for item in itens:
            slug = str(item["slug"]).strip()
            categoria = str(item["categoria"]).strip()
            if categoria not in CATEGORIAS:
                raise RegraViolada(
                    f"`{slug}`: categoria `{categoria}` inválida (use uma de {list(CATEGORIAS)})"
                )
            existente = conn.execute(
                "SELECT id FROM competencies WHERE slug = ?", (slug,)
            ).fetchone()
            if existente:
                conn.execute(
                    "UPDATE competencies SET nome = ?, categoria = ?, peso = ? WHERE slug = ?",
                    (item["nome"], categoria, int(item.get("peso", 1)), slug),
                )
                atualizadas += 1
            else:
                conn.execute(
                    "INSERT INTO competencies (slug, nome, categoria, peso, criado_em)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (slug, item["nome"], categoria, int(item.get("peso", 1)), agora),
                )
                criadas += 1
    return criadas, atualizadas


def buscar(conn: sqlite3.Connection, slug: str) -> dict:
    linha = conn.execute(
        "SELECT * FROM v_competency_current WHERE slug = ?", (slug,)
    ).fetchone()
    if not linha:
        raise RegraViolada(f"competência `{slug}` não existe (veja `hermes comp list`)")
    return dict(linha)


def remover(conn: sqlite3.Connection, slug: str, com_historico: bool = False) -> dict:
    """Tira uma competência da lista. Sem `com_historico`, só sem histórico: evidência ligada ou nível declarado
    acima de 0 é o que sustenta o currículo, e isso não some por um clique. Com ele (a tela pede confirmação
    dizendo o que se perde), as ligações de evidência e os níveis vão junto; as notas do vault não são tocadas.
    Vaga e estudo ligados perdem a ligação."""
    c = buscar(conn, slug)
    evidencias, niveis = conn.execute(
        "SELECT (SELECT COUNT(*) FROM evidence WHERE competency_id = ?),"
        " (SELECT COUNT(*) FROM competency_state WHERE competency_id = ? AND nivel > 0)",
        (c["id"], c["id"])).fetchone()
    if (evidencias or niveis) and not com_historico:
        raise RegraViolada(
            f"`{slug}` tem {evidencias} evidência(s) e {niveis} avaliação(ões) acima de 0: remover apagaria "
            "o que sustenta o nível. Desligue as evidências antes, se for mesmo o caso.")
    vagas, estudos = conn.execute(
        "SELECT (SELECT COUNT(*) FROM job_requirements WHERE competency_id = ?),"
        " (SELECT COUNT(*) FROM study_sessions WHERE competency_id = ?)", (c["id"], c["id"])).fetchone()
    with conn:  # as FKs apagam evidência e histórico de nível e desligam requisitos e estudos (SET NULL)
        conn.execute("DELETE FROM competencies WHERE id = ?", (c["id"],))
    return {"slug": slug, "nome": c["nome"], "requisitos_desligados": vagas, "estudos_desligados": estudos,
            "evidencias_desligadas": evidencias, "niveis_apagados": niveis}


def ligacoes(conn: sqlite3.Connection, slug: str) -> dict:
    """Estudos e requisitos de vaga ligados à competência (perdem a ligação se ela sair)."""
    c = buscar(conn, slug)
    estudos, requisitos = conn.execute(
        "SELECT (SELECT COUNT(*) FROM study_sessions WHERE competency_id = ?),"
        " (SELECT COUNT(*) FROM job_requirements WHERE competency_id = ?)", (c["id"], c["id"])).fetchone()
    return {"estudos": estudos, "requisitos": requisitos}


def tirar_do_seed(caminho: str | Path, slug: str) -> bool:
    """Apaga o item do YAML da taxonomia, senão o próximo `comp seed` traz a competência de volta.
    Edita o texto em vez de regravar o YAML: os comentários do arquivo ficam."""
    arquivo = Path(caminho)
    if not arquivo.exists():
        return False
    texto = arquivo.read_text(encoding="utf-8")
    bloco = re.compile(rf"^(?P<recuo>[ \t]*)- slug:[ \t]*{re.escape(slug)}[ \t]*\n(?:(?P=recuo)[ \t]+\S.*\n?)*", re.M)
    novo, n = bloco.subn("", texto, count=1)
    if n:
        arquivo.write_text(novo, encoding="utf-8")
    return bool(n)


def _chave_nome(nome: str) -> str:
    """Nome para comparar: sem acento, sem diferença de maiúsculas e espaços; os símbolos ficam (C, C++ e C# são três)."""
    import unicodedata

    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def slug_da_competencia(nome: str) -> str:
    """"Inglês técnico" → `ingles-tecnico`; "C#" → `csharp`, "C++" → `cplusplus` (o símbolo vira palavra, não some)."""
    from hermes.domain.perfis_cv import _slug

    texto = nome.replace("#", "sharp").replace("+", "plus")
    slug = _slug(texto)
    return "competencia" if slug == "recorte" else slug


def nova(caminho_yaml: str | Path, conn: sqlite3.Connection, nome: str, categoria: str, peso: int) -> dict:
    """Cria uma competência pela tela: acrescenta o item no fim de `competencias:` sem regravar o YAML (os
    comentários e a ordem ficam), roda o seed e devolve a linha como `listar` mostra.
    Nome repetido (sem acento e sem diferença de maiúsculas) ou slug repetido levanta `CompetenciaDuplicada`."""
    import os
    import tempfile

    from hermes.domain.perfis_cv import _inserir_no_bloco

    caminho = Path(caminho_yaml)
    nome = " ".join(nome.split())
    if not nome:
        raise RegraViolada("a competência precisa de um nome")
    if categoria not in CATEGORIAS:
        raise RegraViolada(f"categoria `{categoria}` inválida (use uma de {list(CATEGORIAS)})")
    if not isinstance(peso, int) or isinstance(peso, bool) or not 1 <= peso <= 3:
        raise RegraViolada("peso de 1 a 3")
    slug = slug_da_competencia(nome)
    texto = caminho.read_text(encoding="utf-8") if caminho.is_file() else ""
    try:
        do_arquivo = (yaml.safe_load(texto) or {}).get("competencias") or []
    except yaml.YAMLError as exc:
        raise RegraViolada(f"{caminho.name} não abre ({str(exc).splitlines()[0]}); corrija à mão antes") from None
    for n, i in enumerate(do_arquivo, start=1):
        if not isinstance(i, dict) or not i.get("slug"):
            raise RegraViolada(f"{caminho.name}: o item #{n} não tem `slug:`; corrija à mão antes de acrescentar")
    existentes = [(str(i.get("slug", "")), str(i.get("nome", ""))) for i in do_arquivo]
    existentes += [(r["slug"], r["nome"]) for r in conn.execute("SELECT slug, nome FROM competencies")]
    if any(slug == s or _chave_nome(nome) == _chave_nome(n) for s, n in existentes):
        raise CompetenciaDuplicada("Já existe uma competência com esse nome")

    item = {"slug": slug, "nome": nome, "categoria": categoria, "peso": peso}
    bloco = yaml.safe_dump([item], allow_unicode=True, sort_keys=False).splitlines(keepends=True)
    novo = _inserir_no_bloco(texto, bloco, chave="competencias")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=caminho.parent, prefix=".competencias-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(novo)
        # só troca o arquivo se o que já existia continua lá, na mesma ordem, e o item novo entrou por último
        try:
            depois = (yaml.safe_load(Path(temporario).read_text(encoding="utf-8")) or {}).get("competencias") or []
        except yaml.YAMLError:
            depois = []
        if [str(i.get("slug")) for i in depois] != [s for s, _ in existentes[:len(do_arquivo)]] + [slug]:
            raise RegraViolada(f"não deu para acrescentar sem mexer no resto do {caminho.name}; "
                               "acrescente à mão no fim de `competencias:`")
        os.replace(temporario, caminho)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise
    seed(conn, caminho)
    return next(l for l in listar(conn) if l["slug"] == slug)


def listar(
    conn: sqlite3.Connection,
    categoria: str | None = None,
    so_lacunas: bool = False,
) -> list[dict]:
    sql = "SELECT * FROM v_competency_current"
    params: list = []
    if categoria:
        sql += " WHERE categoria = ?"
        params.append(categoria)
    sql += " ORDER BY peso DESC, COALESCE(nivel, 0) ASC, slug"
    linhas = [_com_situacao(dict(r)) for r in conn.execute(sql, params)]
    if so_lacunas:
        linhas = [l for l in linhas if l["lacuna"]]
    return linhas


def _com_situacao(linha: dict) -> dict:
    nivel = linha.get("nivel")
    evidencias = linha.get("n_evidencias", 0)
    if nivel is None:
        situacao = "nunca avaliada"
    elif nivel >= 2 and evidencias == 0:
        situacao = "sem evidencia"
    elif nivel >= 3 and evidencias < 2:
        situacao = "evidencia insuficiente"
    else:
        situacao = "ok"
    linha["situacao"] = situacao
    linha["pronta_para_cv"] = bool(nivel and nivel >= 2 and evidencias >= 1)
    linha["lacuna"] = not linha["pronta_para_cv"]
    return linha


def resolver_fato(conn: sqlite3.Connection, referencia: str) -> dict:
    """Aceita `nota.md#block-id` ou só `block-id`, se ele for único no índice."""
    ref = referencia.strip().lstrip("^")
    if "#" in ref:
        nota, _, block_id = ref.partition("#")
        block_id = block_id.lstrip("^")
        linha = conn.execute(
            "SELECT * FROM facts WHERE nota = ? AND block_id = ?", (nota, block_id)
        ).fetchone()
        if not linha:
            raise RegraViolada(
                f"fato `{nota}#{block_id}` não está no índice — confira a nota e rode `hermes index`"
            )
        return dict(linha)

    linhas = conn.execute("SELECT * FROM facts WHERE block_id = ?", (ref,)).fetchall()
    if not linhas:
        raise RegraViolada(
            f"block id `^{ref}` não está no índice — confira a nota e rode `hermes index`"
        )
    if len(linhas) > 1:
        notas = ", ".join(sorted(f"{l['nota']}#{ref}" for l in linhas))
        raise RegraViolada(f"block id `^{ref}` existe em mais de uma nota: {notas}")
    return dict(linhas[0])


def ligar_evidencia(
    conn: sqlite3.Connection,
    slug: str,
    referencia: str,
    forca: int = 2,
    tem_metrica: bool | None = None,
    observacao: str | None = None,
    restaurar: bool = False,
) -> dict:
    """Liga uma competência a um fato do vault. Idempotente pelo par (competência, fato).

    Fato que saiu do vault (evidência órfã): trocar a força da ligação que já existe vale; ligar de novo só com
    `restaurar` (o "Desfazer" de um desligar, com a referência `nota.md#bloco` exata). Ligação nova continua
    exigindo o fato no índice."""
    comp = buscar(conn, slug)
    if forca not in (1, 2, 3):
        raise RegraViolada("força da evidência deve ser 1, 2 ou 3")
    try:
        fato = resolver_fato(conn, referencia)
    except RegraViolada:
        nota, _, bloco = referencia.strip().lstrip("^").partition("#")
        existente = conn.execute(
            "SELECT tem_metrica FROM evidence WHERE competency_id = ? AND nota = ? AND block_id = ?",
            (comp["id"], nota, bloco.lstrip("^"))).fetchone() if bloco else None
        if existente is None and not (restaurar and bloco):
            raise
        fato = {"nota": nota, "block_id": bloco.lstrip("^"), "texto": None}
        if tem_metrica is None:
            tem_metrica = bool(existente["tem_metrica"]) if existente else False
    metrica = fato_tem_metrica(fato["texto"]) if tem_metrica is None else bool(tem_metrica)
    with conn:
        conn.execute(
            "INSERT INTO evidence"
            " (competency_id, nota, block_id, forca, tem_metrica, observacao, criado_em)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (competency_id, nota, block_id) DO UPDATE SET"
            "   forca = excluded.forca,"
            "   tem_metrica = excluded.tem_metrica,"
            "   observacao = COALESCE(excluded.observacao, evidence.observacao)",
            (
                comp["id"],
                fato["nota"],
                fato["block_id"],
                forca,
                int(metrica),
                observacao,
                store.utcnow(),
            ),
        )
    return {
        "slug": slug,
        "nota": fato["nota"],
        "block_id": fato["block_id"],
        "texto": fato["texto"],
        "tem_metrica": metrica,
        "forca": forca,
    }


def remover_evidencia(conn: sqlite3.Connection, slug: str, referencia: str) -> dict:
    """Desfaz um vínculo. Funciona mesmo se o fato já sumiu do vault (evidência órfã).
    Se o nível vigente perde a base, `nivel_sem_base` diz isso, mas o nível continua o mesmo."""
    comp = buscar(conn, slug)
    ref = referencia.strip().lstrip("^")
    if "#" in ref:
        nota, _, block_id = ref.partition("#")
        candidatos = conn.execute(
            "SELECT * FROM evidence WHERE competency_id = ? AND nota = ? AND block_id = ?",
            (comp["id"], nota, block_id.lstrip("^")),
        ).fetchall()
    else:
        candidatos = conn.execute(
            "SELECT * FROM evidence WHERE competency_id = ? AND block_id = ?",
            (comp["id"], ref),
        ).fetchall()
    if not candidatos:
        raise RegraViolada(f"`{slug}` não tem evidência em `{referencia}`")
    if len(candidatos) > 1:
        notas = ", ".join(sorted(f"{l['nota']}#{ref}" for l in candidatos))
        raise RegraViolada(f"vínculo ambíguo, use `nota.md#block-id`: {notas}")

    alvo = dict(candidatos[0])
    with conn:
        conn.execute("DELETE FROM evidence WHERE id = ?", (alvo["id"],))
    # o nível não muda sozinho; o aviso diz que ele ficou sem base, e reavaliar é com você
    nivel_atual = comp["nivel"]
    sem_base = None
    if nivel_atual is not None and recusa_nivel(slug, nivel_atual, evidencias(conn, slug)):
        sem_base = f"Nível {nivel_atual} fica sem evidência suficiente"
    # a ligação inteira volta junto: o "Desfazer" religa com a mesma força, métrica e observação
    return {"slug": slug, "nota": alvo["nota"], "block_id": alvo["block_id"], "nivel_sem_base": sem_base,
            "forca": alvo["forca"], "tem_metrica": bool(alvo["tem_metrica"]), "observacao": alvo["observacao"]}


def evidencias(conn: sqlite3.Connection, slug: str) -> list[dict]:
    comp = buscar(conn, slug)
    linhas = conn.execute(
        "SELECT e.nota, e.block_id, e.forca, e.tem_metrica, e.observacao, f.texto"
        " FROM evidence e"
        " LEFT JOIN facts f ON f.nota = e.nota AND f.block_id = e.block_id"
        " WHERE e.competency_id = ?"
        " ORDER BY e.forca DESC, e.nota",
        (comp["id"],),
    )
    return [dict(l) for l in linhas]


def _termos_do_slug(slug: str) -> set[str]:
    """`integracao-apis` → {integracao, apis, api}. Plural simples cai para o singular."""
    termos = set()
    for parte in slug.split("-"):
        if len(parte) >= 3:
            termos.add(parte)
            if parte.endswith("s") and len(parte) > 3:
                termos.add(parte[:-1])
    return termos


def fatos_candidatos(conn: sqlite3.Connection, slug: str, limite: int = 3) -> list[dict]:
    """Fatos do vault que **parecem** sustentar a competência e ainda não estão ligados a ela.

    Critério: uma tag do fato é igual a uma parte do slug (`llm-aplicado` casa com `#llm`). É
    sugestão para você conferir, nunca evidência: só `comp evidence` liga um fato a uma competência.
    """
    import json

    termos = _termos_do_slug(slug)
    ligados = {
        (r["nota"], r["block_id"])
        for r in conn.execute(
            "SELECT e.nota, e.block_id FROM evidence e JOIN competencies c ON c.id = e.competency_id"
            " WHERE c.slug = ?",
            (slug,),
        )
    }
    candidatos = []
    for r in conn.execute("SELECT nota, block_id, texto, tags FROM facts ORDER BY nota, block_id"):
        if (r["nota"], r["block_id"]) in ligados:
            continue
        if termos & set(json.loads(r["tags"])):
            candidatos.append({"referencia": f"{r['nota']}#{r['block_id']}", "block_id": r["block_id"],
                               "texto": r["texto"], "tem_metrica": fato_tem_metrica(r["texto"])})
    return candidatos[:limite]


def avaliar(
    conn: sqlite3.Connection,
    slug: str,
    nivel: int,
    justificativa: str,
    origem: str = "declarado",
) -> dict:
    """Grava um nível. Recusa quando a evidência não sustenta o que foi declarado."""
    if nivel not in NIVEIS:
        raise RegraViolada(f"nível deve estar entre 0 e 4 ({NIVEIS})")
    if not justificativa.strip():
        raise RegraViolada("justificativa é obrigatória: é o que você vai repetir na entrevista")
    comp = buscar(conn, slug)
    provas = evidencias(conn, slug)
    _exige_evidencia(slug, nivel, provas)

    with conn:
        conn.execute(
            "INSERT INTO competency_state (competency_id, nivel, justificativa, origem, criado_em)"
            " VALUES (?, ?, ?, ?, ?)",
            (comp["id"], nivel, justificativa.strip(), origem, store.utcnow()),
        )
    return {"slug": slug, "nivel": nivel, "n_evidencias": len(provas)}


def _falta(nivel: int, provas: list[dict]) -> str | None:
    """A regra de evidência por nível, numa só função: a tela (`recusa_nivel`) e a gravação
    (`_exige_evidencia`) leem daqui."""
    if nivel >= 2 and not provas:
        return "evidencia"
    if nivel >= 3:
        if len(provas) < 2:
            return "duas"
        if not any(p["tem_metrica"] for p in provas):
            return "metrica"
    if nivel == 4 and not any(p["tem_metrica"] and fato_tem_periodo(p.get("texto") or "") for p in provas):
        return "periodo"
    return None


def recusa_nivel(slug: str, nivel: int, provas: list[dict], nome: str | None = None) -> dict | None:
    """Por que a evidência não sustenta `nivel`, na língua da tela (`{titulo, texto}`); `None` quando passa."""
    falta = _falta(nivel, provas)
    if falta == "evidencia" and nivel >= 3:
        falta = "duas"  # na tela, o que falta para o 3 e o 4 sem nada ligado são as duas evidências
    if falta == "evidencia":
        return {"titulo": f"Nível {nivel} exige uma evidência do vault",
                "texto": f"Ligue um fato que mostre você usando {nome or slug}, ou fique no nível {nivel - 1}."}
    if falta == "duas":
        ligue = "Ligue mais um fato" if len(provas) == 1 else "Ligue dois fatos"
        return {"titulo": f"Nível {nivel} exige 2 evidências",
                "texto": f"Você tem {len(provas)}. {ligue}, ou fique no nível {nivel - 1}."}
    if falta == "metrica":
        return {"titulo": f"Nível {nivel} exige uma evidência com número medido",
                "texto": f"Você tem {len(provas)} evidências, mas nenhuma traz N, data ou período."
                         f" Ligue um fato com métrica, ou fique no nível {nivel - 1}."}
    if falta == "periodo":
        return {"titulo": "Nível 4 exige métrica e período",
                "texto": "Ligue um fato com número e período (ex.: “de 22/06 a 16/08/2026: 60 execuções”),"
                         " ou fique no nível 3."}
    return None


def _exige_evidencia(slug: str, nivel: int, provas: list[dict]) -> None:
    falta = _falta(nivel, provas)
    if falta == "evidencia":
        raise RegraViolada(
            f"nível {nivel} em `{slug}` exige ao menos 1 evidência."
            " Ligue um fato do vault: `hermes comp evidence " + slug + " <nota.md#block-id>`"
        )
    if falta == "duas":
        raise RegraViolada(
            f"nível {nivel} em `{slug}` exige 2 evidências (você tem {len(provas)})"
        )
    if falta == "metrica":
        raise RegraViolada(
            f"nível {nivel} em `{slug}` exige uma evidência com número medido e fonte."
            " Nenhum dos fatos ligados tem N, data ou período"
        )
    if falta == "periodo":
        raise RegraViolada(
            f"nível 4 em `{slug}` exige uma evidência com métrica E período"
            " (ex.: 'de 22/06 a 16/08/2026: 60 execuções'). Nenhum fato ligado tem os dois"
        )


NOTA_EXPORTADA = "Competencias"


def exportar_markdown(conn: sqlite3.Connection) -> str:
    """Espelho do banco para ler no Obsidian. O banco continua sendo a fonte: editar a nota não muda nada."""
    linhas = listar(conn)
    partes = [
        "---",
        "gerado_por: hermes comp export",
        f"atualizado_em: {store.utcnow()}",
        "---",
        "",
        "# Competências",
        "",
        "> [!warning] Nota gerada pelo Hermes — não edite aqui.",
        "> A fonte é o banco (`data/hermes.db`). Para mudar: `hermes comp evidence` e `hermes comp assess`.",
        "> Só entra no currículo o que tem nível ≥ 2 e evidência.",
        "",
        "| competência | nome | nível | evid. | situação |",
        "|---|---|---|---|---|",
    ]
    for l in linhas:
        nivel = "—" if l["nivel"] is None else str(l["nivel"])
        partes.append(
            f"| {l['slug']} | {l['nome']} | {nivel} | {l['n_evidencias']} | {l['situacao']} |"
        )

    for l in linhas:
        if l["nivel"] is None and not l["n_evidencias"]:
            continue
        partes += ["", f"## {l['nome']} (`{l['slug']}`)", ""]
        if l["nivel"] is not None:
            partes.append(f"**Nível {l['nivel']}** — {NIVEIS[l['nivel']]}. Avaliado em {l['avaliado_em'][:10]}.")
            partes.append("")
            partes.append("> " + l["justificativa"].replace("\n", "\n> "))
            partes.append("")
        for e in evidencias(conn, l["slug"]):
            alvo = e["nota"].removesuffix(".md")
            rotulo = f"{Path(alvo).name} ^{e['block_id']}"
            link = f"[[{alvo}#^{e['block_id']}|{rotulo}]]"
            if e["texto"] is None:
                partes.append(f"- {link} — **fato sumiu do vault**")
            else:
                metrica = ", com métrica" if e["tem_metrica"] else ""
                partes.append(f"- {link} (força {e['forca']}{metrica})")
    return "\n".join(partes) + "\n"


def atualizar_nota_exportada(conn: sqlite3.Connection, vault: Path) -> Path | None:
    """Regrava `Competencias.md` só se você já exportou uma vez. Nunca cria sozinho.

    Devolve o caminho quando atualizou. `EscritaRecusada`/`OSError` sobem: a nota é espelho, e
    quem chama decide se a falha nela vira aviso.
    """
    from hermes.vault import writer

    nota = Path(vault).expanduser() / f"{NOTA_EXPORTADA}.md"
    if not nota.is_file() or not nota.read_text(encoding="utf-8").startswith(writer.MARCA_GERADA):
        return None
    writer.substituir_gerada(vault, NOTA_EXPORTADA, exportar_markdown(conn))
    return nota


def cobertura(conn: sqlite3.Connection) -> dict:
    """Resumo para o relatório de lacunas: o que já dá para levar ao currículo."""
    linhas = listar(conn)
    prontas = [l for l in linhas if l["pronta_para_cv"]]
    lacunas = [l for l in linhas if l["lacuna"]]
    return {
        "total": len(linhas),
        "prontas": len(prontas),
        "lacunas": lacunas,
        "por_peso": {
            peso: {
                "total": sum(1 for l in linhas if l["peso"] == peso),
                "prontas": sum(1 for l in prontas if l["peso"] == peso),
            }
            for peso in (3, 2, 1)
        },
    }
