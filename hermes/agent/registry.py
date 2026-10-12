"""Catálogo de ferramentas do agente: esquema, allowlist, confirmação e despacho.

Cada tool é uma função de `hermes/domain/` — a mesma que a CLI chama. O registry só a descreve
para o modelo e cuida do que acontece em volta da chamada.

Contrato de retorno, igual para toda tool: `{"ok": True, "data": {...}}` ou
`{"ok": False, "error": {"code": ..., "message": ...}}`. Erro de tool **nunca** derruba o loop:
volta como mensagem `role="tool"` e o modelo decide o que fazer.

O registry não conhece terminal. Quem sabe perguntar "s/n" é a CLI, que injeta `confirmar`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from hermes.domain import atividade, candidaturas, competencias, estudos, fatos, vaga
from hermes.run_status import RunStatus


@dataclass(frozen=True)
class Tool:
    nome: str
    descricao: str
    parametros: dict
    funcao: Callable[..., Any]
    escreve: bool = False
    pede_confirmacao: bool = False
    # contexto que a sessão injeta e o modelo não escolhe: `status`, `model`, `denylist`,
    # `repos_conhecidos`
    injeta: tuple[str, ...] = ()
    # tool de servidor MCP: falha dela volta ao loop como erro, nunca derruba a sessão
    externa: bool = False

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.nome,
                "description": self.descricao,
                "parameters": self.parametros,
            },
        }


def _objeto(propriedades: dict, obrigatorios: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": propriedades,
        "required": obrigatorios or [],
    }


CORPO_NO_CHAT = 1500  # caracteres de cada e-mail que vão ao modelo: o começo diz o que a empresa quer


STATUS_VAGA = ("novo", "analisado", "aplicado", "descartado")


ABERTAS = ("novo", "analisado")


def _vagas(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    """`abertas` junta novo e analisado: o modelo tende a filtrar só `novo` e perder as que já têm score."""
    if status is not None and status != "abertas" and status not in STATUS_VAGA:
        raise ValueError(f"status `{status}` inválido; use abertas, {', '.join(STATUS_VAGA)}")
    if status == "abertas":
        return [v for v in vaga.listar(conn) if v["status"] in ABERTAS]
    return vaga.listar(conn, status)


def _candidaturas(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status is not None and status not in candidaturas.STATUS:
        raise ValueError(f"status `{status}` inválido; use {', '.join(candidaturas.STATUS)}")
    campos = ("id", "empresa", "titulo", "perfil", "status", "enviada_em", "teve_avanco",
              "n_emails", "ultimo_email_em", "score")
    return [{k: c[k] for k in campos} for c in candidaturas.listar(conn, status)]


def _candidatura(conn: sqlite3.Connection, candidatura_id: int) -> dict:
    d = candidaturas.detalhe(conn, candidatura_id)
    for e in d["emails"]:
        corpo = e["corpo"] or ""
        e["corpo"] = corpo[:CORPO_NO_CHAT] + ("…" if len(corpo) > CORPO_NO_CHAT else "") or None
    return d


def _notas_perfis(conn: sqlite3.Connection) -> dict:
    return {**candidaturas.notas_por_perfil(conn, date.today()),
            "regra": f"nota 0–5 pela taxa de avanço sobre envios maturados ({candidaturas.MATURACAO_DIAS} dias "
                     f"ou com resposta); sem nota abaixo de {candidaturas.MIN_ENVIOS} maturados"}


TOOLS: tuple[Tool, ...] = (
    Tool(
        nome="vault_search_facts",
        descricao=(
            "Busca fatos no vault do usuário (a fonte da verdade sobre a carreira dele). "
            "Use antes de afirmar qualquer coisa sobre a experiência dele. Todo fato vem com "
            "uma `referencia` (`nota.md#block-id`) — cite-a quando usar o fato."
        ),
        parametros=_objeto(
            {
                "query": {"type": "string", "description": "termos a buscar no texto do fato"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "tags do Obsidian, sem o #, ex: ['python', 'sql']",
                },
                "tipo": {"type": "string", "enum": ["experience", "project"]},
                "limite": {"type": "integer", "description": "padrão 10, máximo 50"},
            }
        ),
        funcao=fatos.buscar,
    ),
    Tool(
        nome="list_competencies",
        descricao=(
            "Lista as competências com o nível vigente, quantas evidências sustentam cada uma e "
            "se já está pronta para entrar no currículo. Com `so_lacunas=true`, devolve só as "
            "que ainda não estão prontas."
        ),
        parametros=_objeto(
            {
                "categoria": {
                    "type": "string",
                    "enum": ["linguagem", "dados", "automacao", "ia", "processo", "idioma", "soft"],
                },
                "so_lacunas": {"type": "boolean"},
            }
        ),
        funcao=competencias.listar,
    ),
    Tool(
        nome="link_evidence",
        descricao=(
            "Liga uma competência a um fato do vault, pela referência `nota.md#block-id` (ou só "
            "o block-id, se for único). É isso que permite subir o nível depois."
        ),
        parametros=_objeto(
            {
                "slug": {"type": "string"},
                "referencia": {"type": "string", "description": "nota.md#block-id ou block-id"},
                "forca": {"type": "integer", "description": "1 fraca, 2 média, 3 forte"},
                "observacao": {"type": "string"},
            },
            ["slug", "referencia"],
        ),
        funcao=competencias.ligar_evidencia,
        escreve=True,
        pede_confirmacao=True,
    ),
    Tool(
        nome="assess_competency",
        descricao=(
            "Grava o nível (0 a 4) de uma competência. A gravação é recusada quando a evidência "
            "não sustenta o nível: 2 exige 1 evidência, 3 exige 2 sendo uma com métrica. "
            "A justificativa é o que o usuário vai repetir numa entrevista — exija que seja concreta."
        ),
        parametros=_objeto(
            {
                "slug": {"type": "string"},
                "nivel": {"type": "integer", "minimum": 0, "maximum": 4},
                "justificativa": {"type": "string"},
            },
            ["slug", "nivel", "justificativa"],
        ),
        funcao=competencias.avaliar,
        escreve=True,
        pede_confirmacao=True,
    ),
    Tool(
        nome="parse_job",
        descricao=(
            "Grava uma vaga a partir do texto colado pelo usuário ou de uma URL e extrai os "
            "requisitos, mapeados às competências cadastradas. Custa uma chamada ao modelo; vaga "
            "já gravada volta de graça com `duplicada=true`. Passe `texto` OU `url`, nunca os dois."
        ),
        parametros=_objeto(
            {
                "texto": {"type": "string", "description": "descrição completa da vaga"},
                "url": {"type": "string"},
            }
        ),
        funcao=vaga.parse_job,
        escreve=True,
        pede_confirmacao=True,
        injeta=("status", "model", "denylist"),
    ),
    Tool(
        nome="match_job",
        descricao=(
            "Avalia a aderência a uma vaga gravada. O score é calculado pelo sistema (fórmula v1, "
            "a partir do nível de cada competência) — apresente-o com N de requisitos, mapeados e "
            "obrigatórios descobertos, nunca sem eles. Devolve lacunas e riscos de entrevista."
        ),
        parametros=_objeto({"job_id": {"type": "integer"}}, ["job_id"]),
        funcao=vaga.match_job,
        escreve=True,
        pede_confirmacao=True,
        injeta=("status", "model"),
    ),
    Tool(
        nome="log_study",
        descricao=(
            "Registra uma sessão de estudo que o USUÁRIO declarou nesta conversa: minutos e o que "
            "fez. Nunca registre estudo que ele não declarou, nem estime minutos por ele."
        ),
        parametros=_objeto(
            {
                "minutos": {"type": "integer", "minimum": 1},
                "o_que_fez": {"type": "string"},
                "slug": {"type": "string", "description": "competência estudada, se houver"},
                "data": {"type": "string", "description": "AAAA-MM-DD; padrão hoje"},
                "dificuldade": {"type": "integer", "minimum": 1, "maximum": 5},
                "travou_em": {"type": "string"},
            },
            ["minutos", "o_que_fez"],
        ),
        funcao=estudos.log_study,
        escreve=True,
        pede_confirmacao=True,
    ),
    Tool(
        nome="git_activity",
        descricao=(
            "Lê os commits recentes do usuário nos repositórios locais e devolve os que ainda não "
            "foram resolvidos. Commit é SINAL, não estudo: use para PERGUNTAR o que ele estudou e "
            "por quanto tempo; só registre depois que ele responder, com `confirm_study_signals`."
        ),
        parametros=_objeto(
            {
                "dias": {"type": "integer", "minimum": 1, "maximum": 31, "description": "padrão 1"},
                "repos": {"type": "array", "items": {"type": "string"},
                          "description": "nomes das pastas; padrão todos"},
            }
        ),
        funcao=atividade.git_activity,
        escreve=True,
        pede_confirmacao=True,
        injeta=("repos_conhecidos", "status"),
    ),
    Tool(
        nome="confirm_study_signals",
        descricao=(
            "Transforma commits (sinais) em UMA sessão de estudo, com os minutos e o que o usuário "
            "disse ter estudado. Só chame depois que ele responder; os minutos são dele, não da "
            "contagem de commits."
        ),
        parametros=_objeto(
            {
                "sinais": {"type": "array", "items": {"type": "integer"}},
                "minutos": {"type": "integer", "minimum": 1},
                "o_que_fez": {"type": "string"},
                "slug": {"type": "string"},
                "dificuldade": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            ["sinais", "minutos", "o_que_fez"],
        ),
        funcao=atividade.confirmar,
        escreve=True,
        pede_confirmacao=True,
    ),
    Tool(
        nome="study_week",
        descricao="Resumo de uma semana: minutos declarados por competência contra o plano.",
        parametros=_objeto({"semana": {"type": "string", "description": "ISO, ex: 2026-W39; padrão a atual"}}),
        funcao=estudos.resumo_semana,
    ),
    Tool(
        nome="plan_week",
        descricao=(
            "Monta o plano de estudo de uma semana a partir das lacunas das vagas abertas. Custa uma "
            "chamada ao modelo. Pergunte antes quantos minutos o usuário tem na semana."
        ),
        parametros=_objeto(
            {
                "minutos_disponiveis": {"type": "integer", "minimum": 30, "maximum": 2400},
                "semana": {"type": "string", "description": "ISO; padrão a próxima"},
                "substituir": {"type": "boolean"},
            },
            ["minutos_disponiveis"],
        ),
        funcao=estudos.plan_week,
        escreve=True,
        pede_confirmacao=True,
        injeta=("status", "model"),
    ),
    Tool(
        nome="list_jobs",
        descricao=(
            "Lista as vagas gravadas, da mais recente para a mais antiga: id, título, empresa, status "
            "(novo, analisado, aplicado, descartado), data de coleta, quantos requisitos foram extraídos e o "
            "score de aderência calculado agora pela fórmula (null = requisitos ainda não extraídos; 0 = nada coberto). Use para achar o `job_id` antes de `match_job` e "
            "para responder quais vagas estão abertas ou combinam mais."
        ),
        parametros=_objeto(
            {"status": {"type": "string", "enum": ["abertas", *STATUS_VAGA],
                        "description": "abertas = novo + analisado (use para 'vagas abertas'); padrão todas"}}
        ),
        funcao=_vagas,
    ),
    Tool(
        nome="list_applications",
        descricao=(
            "Lista as candidaturas do usuário (o que ele enviou e para quem), da mais recente para a mais "
            "antiga, com status, perfil do currículo, quantos e-mails do processo chegaram e a data do último. "
            "Use para perguntas sobre candidaturas, respostas de empresas e resultados de processos."
        ),
        parametros=_objeto(
            {"status": {"type": "string", "enum": list(candidaturas.STATUS),
                        "description": "entrevista = entrevista marcada; em_processo = teve avanço; enviada = sem resposta ainda"}}
        ),
        funcao=_candidaturas,
    ),
    Tool(
        nome="application_detail",
        descricao=(
            "Uma candidatura com a vaga e o currículo de origem e os e-mails do processo em ordem, cada um com "
            "a categoria (avanco, reprovado, pendencia, inscricao_confirmada) e o começo do texto. Use para "
            "dizer o que a empresa respondeu e qual é o próximo passo."
        ),
        parametros=_objeto({"candidatura_id": {"type": "integer"}}, ["candidatura_id"]),
        funcao=_candidatura,
    ),
    Tool(
        nome="profile_scores",
        descricao=(
            "Desempenho de cada perfil de currículo: envios, envios maturados, avanços, taxa e nota 0–5. "
            "É a resposta para 'qual currículo está funcionando melhor'. Nota null = poucos dados ainda; "
            "diga quanto falta em vez de inventar uma comparação."
        ),
        parametros=_objeto({}),
        funcao=_notas_perfis,
    ),
)


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def erro(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


@dataclass
class Registry:
    """Despacha tool calls contra uma conexão. Uma instância por sessão de chat."""

    conn: sqlite3.Connection
    allowlist: set[str] | None = None
    confirmar: Callable[[Tool, dict], bool] | None = None
    status: RunStatus = field(default_factory=RunStatus)
    model: str | None = None
    denylist: tuple[str, ...] = ()
    repos_conhecidos: tuple[Path, ...] = ()
    sem_confirmacao: frozenset[str] = frozenset()
    tools: tuple[Tool, ...] = TOOLS

    def _permitidas(self) -> list[Tool]:
        if self.allowlist is None:
            return list(self.tools)
        return [t for t in self.tools if t.nome in self.allowlist]

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._permitidas()]

    def buscar(self, nome: str) -> Tool | None:
        return next((t for t in self._permitidas() if t.nome == nome), None)

    def dispatch(self, nome: str, argumentos: str | dict | None) -> dict:
        """Executa uma tool call. Nunca levanta: toda falha vira `{"ok": False}`."""
        self.status.tool_calls += 1
        resultado = self._dispatch(nome, argumentos)
        if not resultado["ok"]:
            self.status.tool_errors += 1
        return resultado

    def _dispatch(self, nome: str, argumentos: str | dict | None) -> dict:
        tool = self.buscar(nome)
        if tool is None:
            disponiveis = ", ".join(t.nome for t in self._permitidas()) or "nenhuma"
            return erro(
                "tool_desconhecida",
                f"`{nome}` não existe ou não está liberada nesta sessão. Disponíveis: {disponiveis}",
            )

        try:
            kwargs = _argumentos(argumentos)
        except ValueError as e:
            return erro("argumentos_invalidos", str(e))

        if invasores := [k for k in tool.injeta if k in kwargs]:
            return erro("argumentos_invalidos", f"`{nome}` não aceita {', '.join(invasores)}")

        precisa_confirmar = tool.pede_confirmacao and tool.nome not in self.sem_confirmacao
        if precisa_confirmar and self.confirmar is not None:
            if not self.confirmar(tool, kwargs):
                return erro("cancelado", f"o usuário recusou a gravação de `{nome}`")

        # injetado depois da confirmação: o usuário confirma o que o modelo pediu, não o contexto
        kwargs.update({k: getattr(self, k) for k in tool.injeta})
        try:
            return ok(tool.funcao(self.conn, **kwargs))
        except competencias.RegraViolada as e:
            # regra de negócio: o modelo precisa ler isto e corrigir o rumo, não tentar de novo igual
            return erro("regra_violada", str(e))
        except vaga.VagaRecusada as e:
            return erro("vaga_recusada", str(e))
        except (estudos.EstudoRecusado, atividade.AtividadeRecusada, candidaturas.CandidaturaRecusada) as e:
            return erro("regra_violada", str(e))
        except TypeError as e:
            return erro("argumentos_invalidos", f"argumentos não batem com `{nome}`: {e}")
        except ValueError as e:
            return erro("valor_invalido", str(e))
        except sqlite3.Error as e:
            return erro("erro_banco", str(e))
        except Exception as e:
            if tool.externa:
                return erro("falha_mcp", str(e))
            if not tool.injeta:
                raise
            # tool que chama o modelo: falha do provedor volta ao loop, não derruba a sessão
            return erro("falha_llm", f"{type(e).__name__}: {e}")


def _argumentos(argumentos: str | dict | None) -> dict:
    """O provedor manda os argumentos como string JSON; alguns mandam `""` ou `null`."""
    if argumentos is None or argumentos == "":
        return {}
    if isinstance(argumentos, dict):
        return dict(argumentos)
    try:
        valor = json.loads(argumentos)
    except json.JSONDecodeError as e:
        raise ValueError(f"argumentos não são JSON válido: {e}") from None
    if not isinstance(valor, dict):
        raise ValueError(f"argumentos deveriam ser um objeto JSON, veio {type(valor).__name__}")
    return valor
