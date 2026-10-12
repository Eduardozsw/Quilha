"""Currículo: seleção determinística dos fatos, redação pelo modelo, origem garantida.

A divisão de trabalho é a regra central desta fase. **O código escolhe quais fatos entram e
carrega a origem de cada um**; o modelo só reescreve o texto. Fosse o modelo a montar o
documento, a rastreabilidade dependeria de ele obedecer ao prompt — aqui ela é construção.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes.domain.perfis_cv import PerfilCV

# Teto de uma página. Passar disso não é currículo, é histórico.
MAX_FATOS = 12

SELECAO_SQL = """
SELECT f.nota, f.block_id, f.texto, f.tipo, f.entidade,
       c.slug, c.peso, e.forca, e.tem_metrica, v.nivel
FROM evidence e
JOIN competencies c          ON c.id = e.competency_id
JOIN v_competency_current v  ON v.id = c.id
JOIN facts f                 ON f.nota = e.nota AND f.block_id = e.block_id
WHERE v.nivel >= 2
"""

# Sob medida: só competência que a vaga pede, e o peso passa a ser o do requisito
# (2 obrigatório, 1 desejável) — o que importa para a vaga, não para a taxonomia.
SELECAO_VAGA_SQL = """
SELECT f.nota, f.block_id, f.texto, f.tipo, f.entidade,
       c.slug, MAX(CASE r.tipo WHEN 'obrigatorio' THEN 2 ELSE 1 END) AS peso,
       e.forca, e.tem_metrica, v.nivel
FROM evidence e
JOIN competencies c          ON c.id = e.competency_id
JOIN v_competency_current v  ON v.id = c.id
JOIN facts f                 ON f.nota = e.nota AND f.block_id = e.block_id
JOIN job_requirements r      ON r.competency_id = c.id AND r.job_id = ?
WHERE v.nivel >= 2
GROUP BY e.id
"""


def selecionar(
    conn: sqlite3.Connection,
    limite: int = MAX_FATOS,
    job_id: int | None = None,
    perfil: PerfilCV | None = None,
) -> list[dict]:
    """Fatos que sustentam o currículo, do mais forte para o mais fraco.

    Entra o fato ligado a competência de nível ≥ 2 — o nível a partir do qual a evidência é
    exigida. A força é `peso × força da evidência`; um fato que prova mais de uma competência
    entra uma vez só, com a maior das forças e a lista do que ele prova.

    Sem vaga, o peso é o da competência na taxonomia. Com `job_id`, entra só fato de competência
    que algum requisito da vaga pede, e o peso é o do requisito.

    Com `perfil` (e sem vaga), o peso é o que o perfil dá à competência; as que ele não lista
    entram com peso reduzido. Projeto em `excluir` sai; projeto em `primeiro` sobe na ordem, mas
    só se já tiver entrado pela força — o perfil não fura o limite.
    """
    agrupados: dict[tuple[str, str], dict] = {}
    linhas = (
        conn.execute(SELECAO_SQL) if job_id is None else conn.execute(SELECAO_VAGA_SQL, (job_id,))
    )

    for r in linhas:
        if perfil is not None and r["entidade"] in perfil.excluir:
            continue
        chave = (r["nota"], r["block_id"])
        peso = r["peso"] if perfil is None or job_id is not None else perfil.peso(r["slug"], r["peso"])
        forca = peso * r["forca"]
        fato = agrupados.get(chave)
        if fato is None:
            agrupados[chave] = {
                "nota": r["nota"],
                "block_id": r["block_id"],
                "referencia": f"{r['nota']}#{r['block_id']}",
                "origem": f"^{r['block_id']} @ {r['nota']}",
                "texto": r["texto"],
                "tipo": r["tipo"],
                "entidade": r["entidade"],
                "tem_metrica": bool(r["tem_metrica"]),
                "forca": forca,
                "competencias": [r["slug"]],
            }
        else:
            fato["forca"] = max(fato["forca"], forca)
            fato["tem_metrica"] = fato["tem_metrica"] or bool(r["tem_metrica"])
            if r["slug"] not in fato["competencias"]:
                fato["competencias"].append(r["slug"])

    ordenados = sorted(
        agrupados.values(),
        # empate: quem tem métrica passa na frente; depois a ordem do vault, para a saída ser estável
        key=lambda f: (-f["forca"], not f["tem_metrica"], f["nota"], f["block_id"]),
    )
    for fato in ordenados:
        fato["competencias"].sort()
    escolhidos = ordenados[:limite]
    if perfil is not None and perfil.primeiro:
        escolhidos.sort(key=lambda f: f["entidade"] not in perfil.primeiro)  # estável
    return escolhidos


# --------------------------------------------------------------------- redação

SECOES = {
    "pt": {
        "experience": "Experiência",
        "project": "Projetos",
        "competencias": "Habilidades",
        "formacao": "Formação",
        "idiomas": "Idiomas",
    },
    "en": {
        "experience": "Experience",
        "project": "Projects",
        "competencias": "Skills",
        "formacao": "Education",
        "idiomas": "Languages",
    },
}

IDIOMAS = tuple(SECOES)

SYSTEM_REDACAO = {
    "pt": (
        "Você reescreve fatos de currículo em português. Recebe fatos já selecionados e devolve "
        "cada um reescrito em uma linha, começando por verbo de ação no pretérito perfeito, primeira "
        "pessoa do singular (Implementei, Construí, Reduzi), no máximo 25 palavras."
    ),
    "en": (
        "You rewrite résumé facts in English. You receive pre-selected facts and return each one "
        "rewritten as a single line, starting with a past-tense action verb (Built, Implemented, "
        "Reduced), at most 25 words."
    ),
}

REGRAS_REDACAO = """
Regras invioláveis:
- Não invente nada. Só reescreva o que está no fato. Sem número que o fato não traga.
- Preserve todo número, data e N exatamente como vieram.
- Não repita a mesma informação em dois bullets.
- O resumo tem no máximo 3 linhas e não pode afirmar nada fora dos fatos.

Responda SÓ com este JSON:
{"resumo": "...", "bullets": {"<referencia>": "<texto reescrito>", ...}}
As chaves de `bullets` são exatamente as referências recebidas, sem alterar.
"""


def _entrada_para_o_modelo(
    selecao: list[dict], perfil: dict, idioma: str, vaga: dict | None = None
) -> str:
    linhas = [
        f"Cargo alvo: {perfil.get('cargo_alvo', '(não informado)')}",
        f"Idioma da saída: {'português' if idioma == 'pt' else 'inglês'}",
    ]
    if perfil.get("foco"):
        linhas.append(f"Foco deste currículo: {perfil['foco']}")
    if vaga:
        # contexto para a ênfase do texto; a seleção dos fatos já foi feita pelo código
        linhas.append(f"Vaga: {vaga['titulo']} — {vaga['empresa']}")
        linhas += [f"  requisito ({r['tipo']}): {r['texto']}" for r in vaga["requisitos"]]
    linhas += ["", "Fatos selecionados:"]
    linhas += [f'- {f["referencia"]} :: {f["texto"]}' for f in selecao]
    return "\n".join(linhas) + "\n" + REGRAS_REDACAO


def redigir(
    selecao: list[dict],
    perfil: dict,
    idioma: str,
    status,
    model: str | None = None,
    vaga: dict | None = None,
) -> dict:
    """Uma chamada ao modelo. Devolve `{"resumo": str, "bullets": {referencia: texto}}`.

    Tudo que o modelo devolver fora da seleção é descartado com aviso: ele reescreve fatos, não
    acrescenta. Fato que ele deixar de reescrever entra com o texto original do vault.
    """
    from hermes import llm
    from hermes.json_parse import extract_json_object

    bruto = llm.complete(
        SYSTEM_REDACAO[idioma],
        _entrada_para_o_modelo(selecao, perfil, idioma, vaga),
        status=status,
        model=model,
        temperature=0.3,
        json_mode=True,
    )
    redacao = extract_json_object(bruto, ("resumo", "bullets"))

    validas = {f["referencia"] for f in selecao}
    bullets = {}
    for referencia, texto in (redacao.get("bullets") or {}).items():
        if referencia in validas and isinstance(texto, str) and texto.strip():
            bullets[referencia] = texto.strip()
        else:
            status.add(f"redação ignorada para referência desconhecida: `{referencia}`")

    faltando = validas - set(bullets)
    if faltando:
        status.add(f"{len(faltando)} fato(s) entraram com o texto original do vault")

    return {"resumo": str(redacao.get("resumo") or "").strip(), "bullets": bullets}


# -------------------------------------------------------------------- montagem

ATUAL = {"pt": "Atual", "en": "Present"}


def _mes_ano(valor) -> str:
    """`2026-08` (ou uma data do YAML) → `08/2026`. Outro formato passa como veio."""
    if hasattr(valor, "month"):
        return f"{valor.month:02d}/{valor.year}"
    texto = str(valor).strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", texto):
        return f"{int(m.group(2)):02d}/{m.group(1)}"
    return texto


def periodo(inicio, fim, idioma: str) -> str:
    """`08/2026 – Atual`. Sem fim, só o início; sem início, nada."""
    if not inicio:
        return ""
    if not fim:
        return _mes_ano(inicio)
    fim_txt = ATUAL[idioma] if str(fim).strip().lower() in ("atual", "present") else _mes_ano(fim)
    return f"{_mes_ano(inicio)} – {fim_txt}"


def _no_idioma(valor, idioma: str) -> str:
    """Campo que pode vir como texto único ou como `{pt: ..., en: ...}`."""
    if isinstance(valor, dict):
        valor = valor.get(idioma) or next(iter(valor.values()), "")
    return str(valor or "").strip()


def _contato(perfil: dict) -> list[dict]:
    """Email · telefone · cidade · github · linkedin, com o link de cada um quando há."""
    itens = []
    for campo in ("cidade", "telefone", "email", "github", "linkedin"):
        valor = str(perfil.get(campo) or "").strip()
        if not valor:
            continue
        if campo == "email":
            itens.append({"texto": valor, "url": f"mailto:{valor}"})
        elif re.match(r"https?://", valor):
            itens.append({"texto": re.sub(r"^https?://(www\.)?", "", valor).rstrip("/"), "url": valor})
        else:
            itens.append({"texto": valor, "url": None})
    return itens


def estruturar(
    perfil: dict,
    selecao: list[dict],
    redacao: dict,
    idioma: str,
    competencias_prontas: list[dict] | None = None,
    entidades: dict[str, dict] | None = None,
    perfil_cv: PerfilCV | None = None,
    nomes: dict[str, str] | None = None,
) -> dict:
    """O currículo como dado: de onde saem o Markdown, o JSON e o PDF.

    A origem de cada bullet é escrita aqui, não pelo modelo. `entidades` é o frontmatter das notas
    (`_entidades`): título, cargo, datas, local, stack e link. `nomes` traduz o slug da stack para
    o nome de exibição. Experiências saem da mais recente para a mais antiga; projetos, na ordem da
    seleção (força, com o `primeiro` do perfil).
    """
    entidades = entidades or {}
    nomes = nomes or {}

    def entrada(entidade: str, fatos: list[dict]) -> dict:
        meta = entidades.get(entidade, {})
        return {
            "entidade": entidade,
            "titulo": meta.get("titulo") or entidade,
            "subtitulo": _no_idioma(meta.get("subtitulo"), idioma),
            "cargo": _no_idioma(meta.get("cargo"), idioma),
            "periodo": periodo(meta.get("inicio"), meta.get("fim"), idioma),
            "local": _no_idioma(meta.get("local"), idioma),
            "stack": [nomes.get(str(s), str(s)) for s in meta.get("stack") or []],
            "link": meta.get("link") or None,
            "bullets": [
                {"texto": redacao["bullets"].get(f["referencia"], f["texto"]),
                 "origem": f["origem"], "referencia": f["referencia"]}
                for f in fatos
            ],
        }

    secoes = {}
    for tipo in ("experience", "project"):
        do_tipo = [f for f in selecao if f["tipo"] == tipo]
        secoes[tipo] = [entrada(e, [f for f in do_tipo if f["entidade"] == e])
                        for e in dict.fromkeys(f["entidade"] for f in do_tipo)]
    # `2026-08` ordena como texto; experiência sem início vai para o fim
    secoes["experience"].sort(key=lambda e: str(entidades.get(e["entidade"], {}).get("inicio") or ""),
                              reverse=True)

    if perfil_cv is not None and perfil_cv.habilidades:
        habilidades = [{"rotulo": h["rotulo"][idioma], "itens": [i[idioma] for i in h["itens"]]}
                       for h in perfil_cv.habilidades]
    elif competencias_prontas:
        habilidades = [{"rotulo": "", "itens": [c["nome"] for c in competencias_prontas]}]
    else:
        habilidades = []

    # item de formação sem nenhum campo preenchido (template ainda vazio) não entra
    formacao = [
        {c: str(item.get(c) or "") for c in ("curso", "instituicao", "periodo")}
        for item in perfil.get("formacao") or []
        if isinstance(item, dict) and any(item.get(c) for c in ("curso", "instituicao", "periodo"))
    ]

    return {
        "idioma": idioma,
        "rotulos": SECOES[idioma],
        "nome": perfil["nome"],
        "cargo": perfil.get("cargo_alvo") or "",
        "contato": _contato(perfil),
        "idiomas": [str(i) for i in perfil.get("idiomas") or []],
        "resumo": redacao.get("resumo") or "",
        "experiencias": secoes["experience"],
        "projetos": secoes["project"],
        "habilidades": habilidades,
        "formacao": formacao,
    }


def para_markdown(estrutura: dict) -> str:
    """Markdown a partir da estrutura. A origem vive num comentário HTML: invisível no render,
    auditável no diff."""
    rotulos = estrutura["rotulos"]
    partes = [f"# {estrutura['nome']}"]
    if estrutura["cargo"]:
        partes.append(f"**{estrutura['cargo']}**")
    if estrutura["contato"]:
        partes.append(" · ".join(c["texto"] for c in estrutura["contato"]))
    if estrutura["resumo"]:
        partes.append(f"\n{estrutura['resumo']}")

    for chave, rotulo in (("experiencias", "experience"), ("projetos", "project")):
        if not estrutura[chave]:
            continue
        partes.append(f"\n## {rotulos[rotulo]}")
        for e in estrutura[chave]:
            titulo = f"[{e['titulo']}]({e['link']})" if e["link"] else e["titulo"]
            complemento = e["cargo"] if chave == "experiencias" else e["subtitulo"]
            partes.append(f"\n### {titulo}" + (f" — {complemento}" if complemento else ""))
            detalhe = [e["periodo"], e["local"]] if chave == "experiencias" else [", ".join(e["stack"])]
            if detalhe := " · ".join(d for d in detalhe if d):
                partes.append(f"*{detalhe}*")
            partes += [f"- {b['texto']} <!-- {b['origem']} -->" for b in e["bullets"]]

    if estrutura["habilidades"]:
        partes.append(f"\n## {rotulos['competencias']}\n")
        for h in estrutura["habilidades"]:
            itens = ", ".join(h["itens"])
            partes.append(f"- **{h['rotulo']}:** {itens}" if h["rotulo"] else itens)

    if estrutura["formacao"]:
        partes.append(f"\n## {rotulos['formacao']}")
        partes += ["- " + " · ".join(v for v in f.values() if v) for f in estrutura["formacao"]]

    if estrutura["idiomas"]:
        partes.append(f"\n## {rotulos['idiomas']}\n\n{', '.join(estrutura['idiomas'])}")

    return "\n".join(partes) + "\n"


def montar(perfil: dict, selecao: list[dict], redacao: dict, idioma: str,
           competencias_prontas: list[dict] | None = None, **kwargs) -> str:
    """Atalho: estrutura e Markdown numa chamada só."""
    return para_markdown(estruturar(perfil, selecao, redacao, idioma, competencias_prontas, **kwargs))


def contar_palavras(markdown: str) -> int:
    """Palavras que o recrutador lê: sem as origens e sem a marcação do Markdown."""
    texto = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
    texto = re.sub(r"^[#\-*>\s]+", "", texto, flags=re.MULTILINE).replace("**", "")
    return len(texto.split())


# ------------------------------------------------------------------- orquestra


CAMPOS_DA_ENTIDADE = ("cargo", "subtitulo", "inicio", "fim", "local", "stack", "link")


def _entidades(vault_path) -> dict[str, dict]:
    """`id` → cabeçalho da entrada (título, cargo, datas, local, stack, link), do frontmatter das
    notas de `Carreira/`."""
    from hermes.vault.reader import read_notes

    return {
        n.entidade: {"titulo": n.titulo, **{c: n.frontmatter.get(c) for c in CAMPOS_DA_ENTIDADE}}
        for n in read_notes(vault_path)
        if n.entidade
    }


class SemFatos(RuntimeError):
    """Não há fato que sustente currículo. A mensagem diz qual é o passo que falta."""


def _hash_da_selecao(**partes) -> str:
    import hashlib
    import json

    bruto = json.dumps(partes, ensure_ascii=False, sort_keys=True, default=list)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def gerar(
    conn: sqlite3.Connection,
    vault_path,
    saida_dir,
    status,
    idiomas: tuple[str, ...] = IDIOMAS,
    model: str | None = None,
    job_id: int | None = None,
    limite: int | None = None,
    perfil: PerfilCV | None = None,
    forcar: bool = False,
    nomes: dict[str, str] | None = None,
) -> list[dict]:
    """Gera o currículo nos idiomas pedidos, **a partir de uma única seleção**.

    A seleção é feita uma vez de propósito: PT e EN precisam afirmar exatamente os mesmos fatos.
    Selecionar por idioma abriria a porta para as duas versões divergirem sem ninguém notar.

    Se a mesma seleção (fatos, textos, cabeçalho, perfil, vaga e idioma) já foi redigida, a redação
    guardada é reaproveitada sem chamar o modelo — a menos que `forcar` peça texto novo. Cabeçalho
    das entradas e habilidades vêm sempre do vault e do perfil atuais.

    Grava `cv-<idioma>.md` e `cv-<idioma>.json` (a estrutura que o template do PDF lê).
    """
    import json
    from pathlib import Path

    from hermes.db import store
    from hermes.domain import competencias
    from hermes.domain.perfil import carregar

    desconhecido = [i for i in idiomas if i not in IDIOMAS]
    if desconhecido:
        raise ValueError(f"idioma não suportado: {desconhecido} (use {list(IDIOMAS)})")

    cabecalho = carregar(vault_path)
    vaga = None
    if job_id is not None:
        from hermes.domain import vaga as vaga_mod

        vaga = {**vaga_mod.buscar(conn, job_id), "requisitos": vaga_mod.requisitos(conn, job_id)}

    if limite is None:
        limite = perfil.limite_fatos if perfil is not None else MAX_FATOS
    selecao = selecionar(conn, limite, job_id, perfil)
    if not selecao and vaga is not None:
        raise SemFatos(
            f"nenhum fato sustenta os requisitos da vaga {job_id}. Veja as lacunas com "
            f"`hermes job match {job_id} --sem-texto` e mapeie requisitos com `hermes job map`."
        )
    if not selecao:
        raise SemFatos(
            "nenhum fato sustenta currículo ainda. É preciso ligar evidência a uma competência "
            "(`hermes comp evidence <slug> <ref>`) e declarar nível ≥ 2 (`hermes comp assess`)."
        )

    prontas = [c for c in competencias.listar(conn) if c["pronta_para_cv"]]
    if perfil is not None:
        prontas.sort(key=lambda c: -perfil.peso(c["slug"], c["peso"]))  # estável
    entidades = _entidades(vault_path)
    referencias = [f["referencia"] for f in selecao]
    saida = Path(saida_dir) / perfil.slug if perfil is not None else Path(saida_dir)
    saida.mkdir(parents=True, exist_ok=True)

    resultados = []
    versao_id = None
    for idioma in idiomas:
        perfil_dict = cabecalho if perfil is None else {
            **cabecalho, "cargo_alvo": perfil.cargo[idioma], "foco": perfil.foco,
        }
        hash_ = _hash_da_selecao(
            perfil=perfil.para_hash() if perfil is not None else None, job_id=job_id,
            idioma=idioma, cabecalho=perfil_dict, prontas=[c["nome"] for c in prontas],
            fatos=[(f["referencia"], f["texto"]) for f in selecao],
        )
        # versão anterior à 004 não guardou a redação: sem ela não há como remontar, redige de novo
        guardada = None if forcar else conn.execute(
            "SELECT id, conteudo, redacao, estrutura FROM cv_versions WHERE selecao_hash = ?"
            " AND redacao IS NOT NULL ORDER BY id DESC LIMIT 1",
            (hash_,),
        ).fetchone()

        redacao = json.loads(guardada["redacao"]) if guardada is not None else None
        if redacao is None:
            antes = status.cost_usd
            redacao = redigir(selecao, perfil_dict, idioma, status, model, vaga)
            depois = status.cost_usd
        # a redação é o que se paga; o resto (cargo, datas, link, habilidades) é remontado do vault
        estrutura = estruturar(perfil_dict, selecao, redacao, idioma, prontas, entidades, perfil, nomes)
        markdown = para_markdown(estrutura)

        # o currículo base não é sobrescrito pelo sob medida
        base = f"cv-{idioma}" if job_id is None else f"cv-{idioma}-vaga-{job_id}"
        caminho = saida / f"{base}.md"
        with conn:
            if guardada is None:
                cur = conn.execute(
                    "INSERT INTO cv_versions (job_id, idioma, caminho, fatos, model, cost_usd,"
                    " criado_em, perfil, selecao_hash, palavras, conteudo, redacao, estrutura)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        job_id,
                        idioma,
                        str(caminho),
                        json.dumps(referencias, ensure_ascii=False),
                        model,
                        None if antes is None or depois is None else depois - antes,
                        store.utcnow(),
                        perfil.slug if perfil is not None else None,
                        hash_,
                        contar_palavras(markdown),
                        markdown,
                        json.dumps(redacao, ensure_ascii=False),
                        json.dumps(estrutura, ensure_ascii=False),
                    ),
                )
            elif guardada["conteudo"] != markdown or guardada["estrutura"] is None:
                # o vault mudou o cabeçalho (ou a versão é de antes da 008): a galeria mostra o que foi
                # para o arquivo, e a página e o PDF saem da mesma estrutura
                conn.execute("UPDATE cv_versions SET conteudo = ?, palavras = ?, estrutura = ? WHERE id = ?",
                             (markdown, contar_palavras(markdown), json.dumps(estrutura, ensure_ascii=False),
                              guardada["id"]))
        # a candidatura aponta para a versão em português, se pedida (em qualquer ordem); senão, a primeira
        if versao_id is None or idioma == "pt":
            versao_id = cur.lastrowid if guardada is None else guardada["id"]
        caminho.write_text(markdown, encoding="utf-8")
        (saida / f"{base}.json").write_text(
            json.dumps(estrutura, ensure_ascii=False, indent=2), encoding="utf-8")
        resultados.append(
            {
                "idioma": idioma,
                "caminho": caminho,
                "palavras": contar_palavras(markdown),
                "fatos": referencias,
                "perfil": perfil.slug if perfil is not None else None,
                "reaproveitado": guardada is not None,
                "estrutura": estrutura,
            }
        )
    if job_id is not None:
        from hermes.domain import candidaturas

        # gerar para a vaga conta como envio (fase 10); `hermes app cancelar` desfaz
        # a candidatura aponta para a versão em português; gerar só o inglês não troca
        candidaturas.registrar_do_cv(conn, job_id, perfil.slug if perfil is not None else None, versao_id,
                                     trocar_versao="pt" in idiomas)
    return resultados


class CurriculoRecusado(Exception):
    pass


def versao(conn: sqlite3.Connection, versao_id: int, vault_path) -> dict:
    """Uma versão para a tela: a estrutura gravada (None nas de antes da 008) e, para cada linha, o fato
    de onde ela veio como está hoje no vault, com o link para abrir a nota no Obsidian."""
    import json
    from pathlib import Path
    from urllib.parse import quote

    linha = conn.execute(
        "SELECT v.id, v.perfil, v.idioma, v.job_id, v.caminho, v.fatos, v.criado_em, v.palavras, v.conteudo,"
        " v.estrutura, j.titulo AS vaga_titulo, j.empresa AS vaga_empresa"
        " FROM cv_versions v LEFT JOIN jobs j ON j.id = v.job_id WHERE v.id = ?", (versao_id,)).fetchone()
    if linha is None:
        raise CurriculoRecusado(f"versão {versao_id} não existe")
    v = dict(linha)
    v["fatos"] = json.loads(v["fatos"])
    estrutura = json.loads(v.pop("estrutura")) if linha["estrutura"] else None
    # a irmã é a mesma geração no outro idioma: mesmos fatos, mesma vaga, mesmo recorte. Com redações
    # repetidas, a mais perto no relógio (gravada junto); o id só desempata
    irma = conn.execute(
        "SELECT id FROM cv_versions WHERE id != ? AND idioma != ? AND fatos = ? AND job_id IS ?"
        " AND perfil IS ? ORDER BY ABS(julianday(criado_em) - julianday(?)), ABS(id - ?), id LIMIT 1",
        (versao_id, v["idioma"], linha["fatos"], v["job_id"], v["perfil"], v["criado_em"], versao_id)).fetchone()
    v["irma_id"] = irma[0] if irma else None

    pares = [ref.split("#", 1) for ref in v["fatos"] if "#" in ref]
    textos = {}
    if pares:
        filtro = " OR ".join(["(nota = ? AND block_id = ?)"] * len(pares))
        textos = {(r["nota"], r["block_id"]): r["texto"] for r in conn.execute(
            f"SELECT nota, block_id, texto FROM facts WHERE {filtro}", [x for par in pares for x in par])}
    nome_vault = quote(Path(vault_path).name)
    fontes = {}
    for nota, bloco in pares:
        texto = textos.get((nota, bloco))
        fontes[f"{nota}#{bloco}"] = {
            "nota": nota, "block_id": bloco, "texto": texto, "no_vault": texto is not None,
            "obsidian": (f"obsidian://open?vault={nome_vault}&file={quote(nota.removesuffix('.md'))}"
                         if texto is not None else None),
        }
    return {"versao": v, "estrutura": estrutura, "fontes": fontes}


# prévias já compiladas: (versão, hash do que entra no Typst) → resposta. Pequeno: a tela abre poucas por vez.
_CACHE_PREVIA: dict[tuple[int, str], dict] = {}
_MAX_CACHE_PREVIA = 16
_TRAVA_PREVIA = threading.Lock()  # o servidor atende pedidos em paralelo


def _guardar_previa(chave: tuple[int, str], resposta: dict) -> None:
    with _TRAVA_PREVIA:
        while len(_CACHE_PREVIA) >= _MAX_CACHE_PREVIA:
            _CACHE_PREVIA.pop(next(iter(_CACHE_PREVIA)), None)
        _CACHE_PREVIA[chave] = resposta


def previa_da_versao(conn: sqlite3.Connection, versao_id: int, perfis: list[PerfilCV]) -> dict:
    """As páginas do mesmo PDF que "Baixar PDF" gera, como imagens, e onde cada fato caiu nelas. Mostra mesmo
    passando do limite de páginas do recorte (`passou`): quem recusa o excesso é o download."""
    import base64
    import hashlib
    import json

    from hermes.domain import pdf

    linha = conn.execute("SELECT perfil, estrutura FROM cv_versions WHERE id = ?", (versao_id,)).fetchone()
    if linha is None:
        raise CurriculoRecusado(f"versão {versao_id} não existe")
    if not linha["estrutura"]:
        raise CurriculoRecusado("versão antiga, sem a estrutura do currículo: redija de novo para ver a página")
    recorte = next((p for p in perfis if p.slug == linha["perfil"]), None)
    limite = recorte.paginas if recorte is not None else 1
    chave = (versao_id, hashlib.sha256(f"{limite}|{linha['estrutura']}".encode()).hexdigest())
    guardada = _CACHE_PREVIA.get(chave)
    if guardada is not None:
        return guardada
    try:
        bruta = pdf.previa(json.loads(linha["estrutura"]))
    except pdf.PdfFalhou as exc:
        raise CurriculoRecusado(f"não deu para montar a página: {exc}") from exc
    altura = bruta["altura"]
    resposta = {
        "largura": bruta["largura"], "altura": altura,
        "paginas": ["data:image/png;base64," + base64.b64encode(p).decode() for p in bruta["paginas"]],
        # fato que atravessa a quebra de página: a área fica na página onde ele começa, sem sair dela
        "linhas": [{**l, "h": min(l["h"], altura - l["y"])} for l in bruta["linhas"]],
        "limite": limite, "passou": len(bruta["paginas"]) > limite,
    }
    _guardar_previa(chave, resposta)
    return resposta


def pdf_da_versao(conn: sqlite3.Connection, versao_id: int, perfis: list[PerfilCV], destino=None) -> dict:
    """Compila o PDF de uma versão a partir da estrutura dela. Um arquivo por versão (`cv-pt-v12.pdf`, ao
    lado do Markdown): baixar uma versão antiga não sobrescreve a de hoje. Com `destino` ("Salvar como…" do
    app), copia o PDF para lá. Devolve também o nome que a janela de salvar sugere."""
    import json
    import shutil
    from pathlib import Path

    from hermes.domain import pdf

    linha = conn.execute(
        "SELECT v.caminho, v.perfil, v.idioma, v.estrutura, j.empresa FROM cv_versions v"
        " LEFT JOIN jobs j ON j.id = v.job_id WHERE v.id = ?", (versao_id,)).fetchone()
    if linha is None:
        raise CurriculoRecusado(f"versão {versao_id} não existe")
    if not linha["estrutura"]:
        raise CurriculoRecusado("versão antiga, sem a estrutura do currículo: redija de novo para gerar o PDF")
    if destino is not None and Path(destino).suffix.lower() != ".pdf":
        raise CurriculoRecusado("o arquivo precisa terminar em .pdf")
    estrutura = json.loads(linha["estrutura"])
    recorte = next((p for p in perfis if p.slug == linha["perfil"]), None)
    limite = recorte.paginas if recorte is not None else 1
    md = Path(linha["caminho"])
    gerado = md.with_name(f"{md.stem}-v{versao_id}.pdf")
    try:
        feito = pdf.compilar(estrutura, gerado, limite)
    except pdf.PdfFalhou as exc:
        raise CurriculoRecusado(f"não deu para montar o PDF: {exc}") from exc
    except pdf.PaginasDemais as exc:
        raise CurriculoRecusado(
            f"passou de {exc.paginas} páginas (limite {exc.limite}): tire fatos do recorte ou baixe o limite de fatos"
        ) from exc
    final = gerado.resolve()
    if destino is not None:
        final = Path(destino)
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gerado, final)
    partes = [str(estrutura.get("nome") or "Currículo").strip()]
    if linha["empresa"]:
        partes.append(linha["empresa"])
    nome = " - ".join(partes) + (" (EN)" if linha["idioma"] == "en" else "")
    nome = "".join(c for c in nome if c not in '\\/:*?"<>|')
    return {"caminho": str(final), "paginas": feito["paginas"], "nome_sugerido": f"{nome}.pdf"}


def galeria(conn: sqlite3.Connection, perfis: list[PerfilCV]) -> list[dict]:
    """Versões geradas agrupadas por perfil: "Melhores para vaga de <cargo>".

    Todo perfil do `curriculos.yaml` aparece, mesmo sem versão (é o convite para gerar). Versão de
    perfil que saiu do yaml continua visível, marcada como removida; a geral vem por último.
    """
    import json

    linhas = [dict(r) for r in conn.execute(
        "SELECT v.id, v.perfil, v.idioma, v.job_id, v.caminho, v.fatos, v.model, v.cost_usd,"
        " v.criado_em, v.palavras, v.conteudo, v.estrutura IS NOT NULL AS tem_estrutura,"
        " j.titulo AS vaga_titulo, j.empresa AS vaga_empresa"
        " FROM cv_versions v LEFT JOIN jobs j ON j.id = v.job_id"
        " WHERE v.conteudo IS NOT NULL ORDER BY v.criado_em DESC, v.id DESC"
    )]
    for linha in linhas:
        linha["fatos"] = json.loads(linha["fatos"])
        linha["tem_estrutura"] = bool(linha["tem_estrutura"])

    grupos = [{"perfil": p.slug, "titulo": p.titulo, "cargo": p.cargo, "foco": p.foco,
               "versoes": [l for l in linhas if l["perfil"] == p.slug]} for p in perfis]
    conhecidos = {p.slug for p in perfis}
    for orfao in dict.fromkeys(l["perfil"] for l in linhas if l["perfil"] and l["perfil"] not in conhecidos):
        grupos.append({"perfil": orfao, "titulo": f"Perfil {orfao} (removido do curriculos.yaml)",
                       "cargo": None, "foco": "",
                       "versoes": [l for l in linhas if l["perfil"] == orfao]})
    gerais = [l for l in linhas if l["perfil"] is None]
    # sem curriculos.yaml (o primeiro dia de quem instala) o currículo geral é o recorte "Geral": a tela
    # nunca abre sem nada para gerar
    if gerais or not perfis:
        grupos.append({"perfil": None, "titulo": "Geral" if not perfis else "Currículo geral", "cargo": None,
                       "foco": "", "versoes": gerais})
    return grupos
