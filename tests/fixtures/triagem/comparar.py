"""Compara os classificadores de e-mail no conjunto fictício com gabarito (`conjunto.jsonl`).

Chama APIs de verdade e gasta crédito (centavos): rode à mão, da raiz do repositório.

    uv run python tests/fixtures/triagem/comparar.py                  # LLM de LLM_MODEL e Jev
    uv run python tests/fixtures/triagem/comparar.py --so llm         # só um dos dois
    uv run python tests/fixtures/triagem/comparar.py --modelo gpt-4o-mini

Para cada classificador: acertos, erros e quantos foram para `revisar` (revisão não é erro, mas
também não é acerto: custa tempo de quem usa). Grava o detalhe por e-mail em `--saida`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from hermes import caminhos
from hermes.domain import triagem_email as tri
from hermes.run_status import RunStatus

AQUI = pathlib.Path(__file__).resolve().parent


def rodar(nome: str, classificador, emails: list[dict]) -> dict:
    status = RunStatus()

    def um(e):
        try:
            return e, classificador({"de": e["de"], "assunto": e["assunto"], "corpo": e["corpo"]}, status), None
        except Exception as exc:  # noqa: BLE001 — falha conta como erro, não derruba a comparação
            return e, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(4) as pool:
        resultados = list(pool.map(um, emails))

    linhas, contagem, confusao = [], Counter(), Counter()
    for e, r, erro in resultados:
        final = r["final"] if r else "falha"
        situacao = "revisar" if final == "revisar" else ("certo" if final == e["rotulo"] else "errado")
        contagem[situacao] += 1
        contagem[f"{situacao}_dificil" if e["dificil"] else f"{situacao}_facil"] += 1
        if situacao == "errado":
            confusao[f"{e['rotulo']} -> {final}"] += 1
        linhas.append({"id": e["id"], "rotulo": e["rotulo"], "final": final, "situacao": situacao,
                       "categoria": r and r["categoria_jev"], "certeza": r and r["prob_categoria"],
                       "latencia_ms": r and r["latencia_ms"], "dificil": e["dificil"],
                       "convencao": e["convencao"], "erro": erro})
    lat = sorted(l["latencia_ms"] for l in linhas if l["latencia_ms"] is not None)
    return {
        "classificador": nome,
        "certo": contagem["certo"], "errado": contagem["errado"], "revisar": contagem["revisar"],
        "faceis": {k: contagem[f"{k}_facil"] for k in ("certo", "errado", "revisar")},
        "dificeis": {k: contagem[f"{k}_dificil"] for k in ("certo", "errado", "revisar")},
        "acerto_entre_decididos": round(contagem["certo"] / max(1, contagem["certo"] + contagem["errado"]), 3),
        "erros_mais_comuns": confusao.most_common(8),
        "custo_usd": status.cost_usd, "chamadas": status.llm_calls,
        "latencia_p50_ms": lat[len(lat) // 2] if lat else None,
        "por_email": linhas,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--so", choices=["llm", "jev"])
    p.add_argument("--modelo", help="modelo do LiteLLM (padrão: LLM_MODEL)")
    p.add_argument("--saida", type=pathlib.Path, default=AQUI / "resultado.json")
    args = p.parse_args()

    load_dotenv(caminhos.base() / ".env")
    emails = [json.loads(l) for l in (AQUI / "conjunto.jsonl").read_text(encoding="utf-8").splitlines() if l]
    relatorio = []
    if args.so in (None, "llm"):
        relatorio.append(rodar(f"llm:{args.modelo or tri.llm.current_model()}", tri.com_llm(args.modelo), emails))
    if args.so in (None, "jev"):
        from typesafe_sdk import TypeSafeClient

        with TypeSafeClient() as jev:
            relatorio.append(rodar("jev", tri.com_jev(jev), emails))

    args.saida.write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in relatorio:
        print(f"\n{r['classificador']}: {r['certo']} certos · {r['errado']} errados · {r['revisar']} para revisão"
              f"  (acerto entre os decididos: {r['acerto_entre_decididos']:.1%})")
        print(f"  fáceis  {r['faceis']}\n  difíceis {r['dificeis']}")
        print(f"  custo US$ {r['custo_usd']}, {r['chamadas']} chamadas, latência p50 {r['latencia_p50_ms']} ms")
        for par, n in r["erros_mais_comuns"]:
            print(f"    {n}× {par}")
    print(f"\ndetalhe por e-mail em {args.saida}", file=sys.stderr)


if __name__ == "__main__":
    main()
