"""Banco fictício para os prints da V3 (Vagas, Currículos, Início e Candidaturas). Tudo inventado; nada do vault real.

    uv run python tests/fixtures/v3/semente.py /caminho/para/v3.db [/caminho/para/curriculos.yaml]

Com o segundo argumento, grava também os recortes nesse yaml e versões de currículo com estrutura.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from hermes.db import store

AGORA = datetime.now(timezone.utc)
PAINEL, AGENDA, LOJA = "Carreira/Projetos/painel-vendas.md", "Carreira/Projetos/agenda-online.md", "Carreira/Projetos/loja-bairro.md"

# slug, nome, categoria, nível (None = nunca avaliada), notas com evidência
COMPETENCIAS = [
    ("react", "React", "linguagem", 3, [PAINEL, AGENDA]),
    ("typescript", "TypeScript", "linguagem", 3, [PAINEL, AGENDA]),
    ("rest", "APIs REST", "linguagem", 2, [AGENDA]),
    ("acessibilidade", "Acessibilidade", "processo", 2, [PAINEL]),
    ("playwright", "Testes end-to-end", "automacao", None, [AGENDA]),
    ("graphql", "GraphQL", "linguagem", None, []),
    ("git", "Git e revisão de código", "processo", 3, [PAINEL, AGENDA, LOJA]),
    ("python", "Python", "linguagem", 1, []),
    ("sql", "SQL", "dados", 2, [AGENDA]),
    ("java", "Java", "linguagem", 0, []),
]

SOBRE = {
    "Orla Tech": "Time de produto de pagamentos para pequenos negócios. Você vai construir a nova área do cliente em React e "
                 "TypeScript, com foco em acessibilidade e performance, junto de design e backend.",
}

# empresa, título, local, senioridade, dias atrás, status, requisitos [(texto, tipo, slug)]
VAGAS = [
    ("Vértice Pay", "Desenvolvedor Front-end", "remoto", "pleno", 0, "novo",
     [("React e TypeScript em produção", "obrigatorio", "react"), ("Design system e Storybook", "obrigatorio", "typescript"),
      ("Acessibilidade", "obrigatorio", "acessibilidade"), ("Experiência com pagamentos", "desejavel", None)]),
    ("Orla Tech", "Desenvolvedor React", "remoto", "pleno", 17, "analisado",
     [("3+ anos com React e TypeScript em produção", "obrigatorio", "react"),
      ("Consumo de APIs REST e gestão de estado", "obrigatorio", "rest"),
      ("Acessibilidade e boas práticas de HTML semântico", "obrigatorio", "acessibilidade"),
      ("Testes end-to-end com Playwright ou Cypress", "obrigatorio", "playwright"),
      ("GraphQL (desejável)", "desejavel", "graphql"), ("Git e revisão de código em equipe", "desejavel", "git")]),
    ("Lumina Saúde", "Engenheiro de Software", "híbrido", "pleno", 19, "analisado",
     [("APIs REST em produção", "obrigatorio", "rest"), ("SQL e modelagem de dados", "obrigatorio", "sql"),
      ("Mensageria (Kafka ou RabbitMQ)", "desejavel", None)]),
    ("Nimbo Logística", "Desenvolvedor Full Stack", "remoto", "pleno", 1, "novo",
     [("React no front", "obrigatorio", "react"), ("Node.js ou Python no back", "obrigatorio", "python"),
      ("Containers e deploy", "desejavel", None)]),
    ("Grupo Tavares", "Estágio Corporativo", "São Paulo", "estágio", 22, "analisado",
     [("Cursando graduação em tecnologia", "obrigatorio", None), ("Git", "desejavel", "git"),
      ("Inglês intermediário", "desejavel", None)]),
    ("Banco Meridiano", "Analista de Dados Jr", "híbrido", "júnior", 25, "analisado",
     [("Python para análise", "obrigatorio", "python"), ("SQL avançado", "obrigatorio", "sql"),
      ("Power BI", "obrigatorio", None), ("Estatística", "desejavel", None)]),
    ("Banco Meridiano", "Backend Java Jr", "presencial", "júnior", 26, "analisado",
     [("Java 17 e Spring", "obrigatorio", "java"), ("Microsserviços", "obrigatorio", None), ("SQL", "desejavel", "sql")]),
    ("Cooperativa Aurora", "Analista Jr", "remoto", "júnior", 30, "aplicado",
     [("SQL", "obrigatorio", "sql"), ("Git", "desejavel", "git")]),
    ("Atlas Seguros", "Desenvolvedor PHP", "presencial", "pleno", 28, "descartado",
     [("PHP 8 e Laravel", "obrigatorio", None)]),
]


# o texto de cada fato (nota, bloco) que as evidências acima apontam; tipo e entidade da nota
FATOS = {
    (PAINEL, "react-0"): "Construí 14 telas em React e TypeScript com gráficos em tempo real e testes de componente.",
    (PAINEL, "typescript-0"): "Tipei a camada de dados do painel e removi 230 usos de `any`.",
    (PAINEL, "acessibilidade-0"): "Auditoria de acessibilidade que levou o painel de 61 para 96 pontos no Lighthouse.",
    (PAINEL, "git-0"): "Revisei 120 pull requests em equipe de 5 pessoas.",
    (AGENDA, "react-1"): "Agenda online com reserva em 3 cliques, usada por 40 clínicas.",
    (AGENDA, "typescript-1"): "Migrei a agenda de JavaScript para TypeScript sem parar as reservas.",
    (AGENDA, "rest-0"): "API REST de agendamento com 18 rotas e documentação OpenAPI.",
    (AGENDA, "playwright-0"): "Suíte de 40 testes end-to-end no CI, rodando em menos de 4 minutos.",
    (AGENDA, "sql-0"): "Modelei o banco da agenda com 9 tabelas e consultas abaixo de 50 ms.",
    (AGENDA, "git-1"): "Fluxo de branches e revisão para 3 pessoas contribuindo.",
    (LOJA, "git-2"): "Publiquei a loja do bairro com deploy automático a cada merge.",
}
EN = {
    "react-0": "Built 14 React and TypeScript screens with real-time charts and component tests.",
    "typescript-0": "Typed the dashboard data layer and removed 230 uses of `any`.",
    "acessibilidade-0": "Accessibility audit that took the dashboard from 61 to 96 on Lighthouse.",
    "git-0": "Reviewed 120 pull requests in a team of 5.",
    "react-1": "Online scheduling with 3-click booking, used by 40 clinics.",
    "typescript-1": "Migrated the scheduler from JavaScript to TypeScript with zero downtime.",
    "rest-0": "Scheduling REST API with 18 routes and OpenAPI docs.",
    "playwright-0": "40 end-to-end tests in CI, running in under 4 minutes.",
    "sql-0": "Designed the scheduler database with 9 tables and queries under 50 ms.",
    "git-1": "Branching and review flow for 3 contributors.",
    "git-2": "Shipped the neighborhood store with automatic deploys on every merge.",
}
NOTAS = {PAINEL: ("experience", "painel-vendas"), AGENDA: ("project", "agenda-online"), LOJA: ("project", "loja-bairro")}
ENTIDADES = {
    "painel-vendas": {"titulo": "Painel de vendas", "subtitulo": "Agência Norte", "cargo": "Desenvolvedora Front-end",
                      "inicio": "2024-03", "fim": "2026-02", "local": "São Paulo"},
    "agenda-online": {"titulo": "Agenda Online", "subtitulo": "projeto próprio", "inicio": "2023-05", "fim": "2024-02"},
    "loja-bairro": {"titulo": "Loja do Bairro", "subtitulo": "projeto voluntário", "inicio": "2023-01", "fim": "2023-04"},
}
CABECALHO = {"nome": "Ana Ribeiro", "cidade": "São Paulo", "email": "ana@exemplo.dev",
             "idiomas": ["Português (nativo)", "Inglês (avançado)"],
             "formacao": [{"curso": "Análise e Desenvolvimento de Sistemas", "instituicao": "Fatec Norte", "periodo": "2022–2024"}]}
RECORTES_YAML = """# recortes fictícios para os prints da V3
perfis:
  - slug: front-end-react
    cargo: {pt: "Desenvolvedora Front-end", en: "Front-end Developer"}
    competencias: {react: 3, typescript: 3, acessibilidade: 2}
  - slug: backend-apis
    cargo: {pt: "Desenvolvedora Backend", en: "Backend Developer"}
    competencias: {rest: 3, sql: 3}
  - slug: estagio-dados
    cargo: {pt: "Estagiária de Dados", en: "Data Intern"}
    competencias: {sql: 3, python: 3}
"""


def semear_curriculos(conn, caminho_yaml: str, saida: str) -> None:
    import json
    from pathlib import Path

    from hermes.domain import curriculo, perfis_cv

    agora = store.utcnow()
    with conn:
        for (nota, bloco), texto in FATOS.items():
            tipo, entidade = NOTAS[nota]
            conn.execute("INSERT OR REPLACE INTO facts (nota, block_id, tipo, entidade, texto, indexado_em)"
                         " VALUES (?, ?, ?, ?, ?, ?)", (nota, bloco, tipo, entidade, texto, agora))
    Path(caminho_yaml).write_text(RECORTES_YAML, encoding="utf-8")
    recortes = {p.slug: p for p in perfis_cv.carregar(caminho_yaml)}
    vagas = {r["empresa"]: r["id"] for r in conn.execute("SELECT id, empresa FROM jobs")}
    # (recorte, empresa da vaga ou None, idiomas, dias atrás)
    # a última é antiga, de antes da 008 (sem `estrutura`): a tela mostra o Markdown no papel
    geracoes = [("front-end-react", "Orla Tech", ("pt", "en"), 6), ("front-end-react", None, ("pt", "en"), 13),
                ("backend-apis", "Lumina Saúde", ("pt",), 14), ("front-end-react", "Maré Digital", ("pt",), 0),
                ("backend-apis", None, ("pt",), 40)]
    for slug, empresa, idiomas, dias in geracoes:
        antiga = dias >= 40
        perfil = recortes[slug]
        job_id = vagas.get(empresa) if empresa else None
        selecao = curriculo.selecionar(conn, perfil.limite_fatos, job_id, perfil)
        quando = (AGORA - timedelta(days=dias)).isoformat(timespec="seconds")
        for idioma in idiomas:
            cab = {**CABECALHO, "cargo_alvo": perfil.cargo[idioma]}
            redacao = {"resumo": ("Interfaces React e TypeScript em produção, com foco em acessibilidade e testes."
                                  if idioma == "pt" else "Production React and TypeScript interfaces, focused on accessibility and tests."),
                       "bullets": {f["referencia"]: (f["texto"] if idioma == "pt" else EN.get(f["block_id"], f["texto"]))
                                   for f in selecao}}
            estrutura = curriculo.estruturar(cab, selecao, redacao, idioma, [], ENTIDADES, perfil, {})
            markdown = curriculo.para_markdown(estrutura)
            base = f"cv-{idioma}" if job_id is None else f"cv-{idioma}-vaga-{job_id}"
            with conn:
                conn.execute(
                    "INSERT INTO cv_versions (job_id, idioma, caminho, fatos, model, cost_usd, criado_em, perfil,"
                    " selecao_hash, palavras, conteudo, redacao, estrutura) VALUES (?, ?, ?, ?, 'semente', 0, ?, ?, ?, ?, ?, ?, ?)",
                    (job_id, idioma, str(Path(saida) / slug / f"{base}.md"),
                     json.dumps([f["referencia"] for f in selecao], ensure_ascii=False), quando, slug,
                     f"semente-{slug}-{empresa}-{idioma}", curriculo.contar_palavras(markdown), markdown,
                     json.dumps(redacao, ensure_ascii=False), None if antiga else json.dumps(estrutura, ensure_ascii=False)))
    with conn:
        # a candidatura nasce do currículo gerado: liga cada uma à versão mais recente da vaga
        conn.execute("UPDATE candidaturas SET cv_version_id = (SELECT MAX(v.id) FROM cv_versions v"
                     " WHERE v.job_id = candidaturas.job_id) WHERE job_id IS NOT NULL")
        # um fato que saiu do vault depois da geração: o balão avisa
        conn.execute("DELETE FROM facts WHERE nota = ? AND block_id = 'typescript-1'", (AGENDA,))


def _dia(dias: int) -> str:
    return (AGORA - timedelta(days=dias)).date().isoformat()


def semear_candidaturas(conn, ids: dict) -> None:
    """As etapas do quadro "Candidaturas": entrevista amanhã, duas em análise, duas aguardando resposta, uma
    pingada, uma a enviar, duas encerradas, 3 e-mails a triar e 4 que não são de processo."""
    from hermes.domain import candidaturas as cand

    local = datetime.now().astimezone()
    amanha_14h = (local + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    hoje_0842 = local.replace(hour=8, minute=42, second=0, microsecond=0)
    if hoje_0842 > local:
        hoje_0842 = local - timedelta(minutes=5)

    def mail(gid, quando, de, assunto, final, empresa=None, corpo=None):
        return cand.inserir_email(conn, {"gmail_id": gid, "recebido_em": quando, "de": de, "assunto": assunto,
                                         "corpo": corpo, "final": final, "empresa_extraida": empresa})

    orla = cand.registrar_do_cv(conn, ids["Orla Tech"], "front-end-react", None)
    cand.marcar_enviada(conn, orla, _dia(13))
    cand.ligar_manual(conn, mail("orla-1", f"{_dia(10)}T13:10:00+00:00", "talentos@orla.example",
                                 "Recebemos sua candidatura", "inscricao_confirmada", "Orla Tech",
                                 "Oi, Ana! Recebemos sua candidatura para Desenvolvedor React. Vamos analisar o seu "
                                 "perfil e voltamos a falar em breve."), orla)
    cand.ligar_manual(conn, mail("orla-2", hoje_0842.isoformat(timespec="seconds"), "talentos@orla.example",
                                 "Convite para entrevista técnica", "avanco", "Orla Tech",
                                 "Olá, Ana! Gostaríamos de seguir com uma entrevista técnica amanhã às 14h, por "
                                 "videochamada. A conversa leva cerca de uma hora, com um exercício prático em React.\n\n"
                                 "O link da chamada chega por aqui na manhã da entrevista. Se o horário não funcionar, "
                                 "responda este e-mail com duas opções.\n\nAbraço,\nTime de Talentos da Orla Tech"), orla)
    cand.marcar_entrevista(conn, orla, amanha_14h.isoformat(timespec="seconds"))
    with conn:
        conn.execute("UPDATE candidaturas SET entrevista_titulo = 'Entrevista técnica' WHERE id = ?", (orla,))

    lumina = cand.registrar_manual(conn, "Lumina Saúde", "backend-apis", titulo="Engenheiro de Software",
                                   enviada_em=_dia(19))
    cand.ligar_manual(conn, mail("sem-avanco", (AGORA - timedelta(days=11)).isoformat(timespec="seconds"),
                                 "rh@lumina.example", "Próxima etapa: conversa com o time", "avanco", "Lumina Saúde",
                                 "Olá, Ana. Gostamos do seu perfil e queremos marcar uma conversa com o time de "
                                 "engenharia. Mandamos os horários nos próximos dias."), lumina)
    vertice = cand.registrar_manual(conn, "Vértice Pay", "front-end-react", titulo="Desenvolvedor Front-end",
                                    enviada_em=_dia(6))
    cand.ligar_manual(conn, mail("vertice-1", (AGORA - timedelta(days=2)).isoformat(timespec="seconds"),
                                 "pessoas@verticepay.example", "Desafio técnico", "avanco", "Vértice Pay",
                                 "Oi, Ana! Você passou para a etapa do desafio técnico. As instruções estão no link "
                                 "abaixo; o prazo é de 5 dias."), vertice)
    for empresa, titulo, dias in (("Nimbo Logística", "Desenvolvedor Full Stack", 15),
                                  ("Grupo Tavares", "Estágio Corporativo", 18)):
        cand.registrar_manual(conn, empresa, "geral", titulo=titulo, enviada_em=_dia(dias))

    # pingada: e-mail do Grupo Tavares que não era da candidatura de estágio
    with conn:
        pingada = cand._inserir(conn, empresa="Grupo Tavares", titulo=None, perfil=None, origem="email",
                                enviada_em=(AGORA - timedelta(days=3)).isoformat(timespec="seconds"))
    cand.ligar_manual(conn, mail("tavares-1", (AGORA - timedelta(days=3)).isoformat(timespec="seconds"),
                                 '"Grupo Tavares" <no-reply@gupy.com.br>', "[Grupo Tavares] Inscrição confirmada",
                                 "inscricao_confirmada", "Grupo Tavares",
                                 "Olá! Sua inscrição no processo seletivo do Grupo Tavares foi confirmada."), pingada)

    mare = conn.execute(
        "INSERT INTO jobs (empresa, titulo, url, fonte, senioridade, local, texto_bruto, hash_texto, coletado_em, status)"
        " VALUES ('Maré Digital', 'Desenvolvedora Front-end Pleno', 'https://vagas.example/mare', 'colado', 'pleno',"
        " 'remoto', 'Produto de agendamento para clínicas. Interfaces em React e TypeScript, testes end-to-end e acessibilidade.', 'semente-mare', ?, 'analisado')",
        (store.utcnow(),)).lastrowid
    conn.commit()
    cand.registrar_do_cv(conn, mare, "front-end-react", None)

    aurora = cand.registrar_manual(conn, "Cooperativa Aurora", "geral", titulo="Analista Jr", enviada_em=_dia(30))
    cand.ligar_manual(conn, mail("aurora-1", (AGORA - timedelta(days=8)).isoformat(timespec="seconds"),
                                 "rh@aurora.example", "Retorno do processo seletivo", "reprovado", "Cooperativa Aurora",
                                 "Agradecemos o seu interesse. Neste momento seguimos com outros perfis."), aurora)
    cand.cancelar(conn, cand.registrar_manual(conn, "Banco Meridiano", "geral", titulo="Analista de Dados Jr",
                                              enviada_em=_dia(25)))

    for i, (assunto, final, de) in enumerate((
            ("Teste técnico: prazo de entrega", "revisar", "talentos@nimbo.example"),
            ("Atualização do seu processo", "pendencia", "no-reply@gupy.com.br"),
            ("Próximos passos da sua candidatura", "avanco", "recrutamento@mail.example"))):
        mail(f"sem-triar-{i}", (AGORA - timedelta(hours=20 + i)).isoformat(timespec="seconds"), de, assunto, final,
             corpo="Olá, Ana! Queremos atualizar você sobre o processo. Responda este e-mail até sexta para seguir.")
    for i, (assunto, de) in enumerate((("Sua fatura chegou", "contas@energia.example"),
                                       ("Novidades da semana", "news@blog.example"),
                                       ("Confirme seu e-mail", "conta@app.example"))):
        mail(f"outro-{i}", (AGORA - timedelta(days=i + 1)).isoformat(timespec="seconds"), de, assunto, "outro")
    # alerta do LinkedIn: vira o grupo "Dos alertas de e-mail" em Vagas
    mail("outro-alerta", (AGORA - timedelta(days=1, hours=3)).isoformat(timespec="seconds"),
         "LinkedIn <jobalerts-noreply@linkedin.com>", "Desenvolvedor Front-end: 2 vagas novas", "outro",
         corpo="Seu alerta de vaga para Desenvolvedor Front-end em: Brasil foi criado.\n\n"
               "Desenvolvedora Front-end Sênior\nPrisma Saúde\nSão Paulo (remoto)\n"
               "Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4100000001/?trk=alerta\n\n"
               "Engenheiro de Interfaces\nRota Azul\nCuritiba (híbrido)\n"
               "Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4100000002/?trk=alerta\n")


def semear_inicio(conn) -> None:
    """O que a Início mostra: entrevista amanhã, avanço ontem, e-mails a triar, vaga nova forte e uma
    competência que subiu hoje; a última visita foi há dois dias."""
    agora = store.utcnow()
    ids = {r["empresa"]: r["id"] for r in conn.execute("SELECT id, empresa FROM jobs")}
    with conn:
        forte = conn.execute(
            "INSERT INTO jobs (empresa, titulo, url, fonte, senioridade, local, texto_bruto, hash_texto, coletado_em, status)"
            " VALUES ('Atlas Digital', 'Desenvolvedor Front-end', 'https://vagas.example/atlas', 'colado', 'pleno', 'remoto',"
            " 'Plataforma de logística para lojas online. Você vai cuidar do painel do lojista em React e TypeScript,"
            " consumindo APIs REST, junto de design e backend.', 'semente-atlas', ?, 'novo')", (agora,)).lastrowid
        for slug in ("react", "typescript", "rest"):
            conn.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES (?, ?, 'obrigatorio',"
                         " (SELECT id FROM competencies WHERE slug = ?))", (forte, slug.upper(), slug))
    semear_candidaturas(conn, ids)
    with conn:
        conn.execute("INSERT INTO competency_state (competency_id, nivel, justificativa, origem, criado_em) VALUES"
                     " ((SELECT id FROM competencies WHERE slug = 'playwright'), 2, 'semente', 'declarado', ?)", (agora,))
        conn.execute("INSERT INTO estado_app (chave, valor) VALUES ('ultima_visita', ?) ON CONFLICT(chave) DO UPDATE"
                     " SET valor = excluded.valor", ((AGORA - timedelta(days=2)).isoformat(timespec="seconds"),))


def semear_conversas(conn) -> None:
    """Duas conversas da V3: uma com cartão de vaga, confirmação gravada e custo; outra parada no meio."""
    from hermes.agent import session as agent_session

    orla = conn.execute("SELECT id, titulo, empresa, senioridade, local FROM jobs WHERE empresa = 'Orla Tech'").fetchone()
    s1 = agent_session.abrir(conn, "gpt-4o-mini")
    s1.gravar({"role": "user", "content": "Me fala sobre a vaga da Orla Tech"})
    s1.gravar({"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_orla", "type": "function", "function": {"name": "match_job", "arguments": f'{{"job_id": {orla["id"]}}}'}}]})
    s1.gravar({"role": "tool", "tool_call_id": "call_orla", "content": '{"ok": true, "data": {"score": 79}}'})
    s1.gravar({"role": "assistant", "content": (
        "A vaga de **Desenvolvedor React** da Orla Tech combina bem com você: o score é 79/100. "
        "Seus projetos em React e TypeScript cobrem a maior parte dos requisitos.\n\n"
        "O que falta é evidência de testes end-to-end e de GraphQL. Vale registrar o que você já estudou.")},
        meta={"custo_usd": 0.004, "parado": False, "confirmacoes": [],
              "ferramentas": [{"nome": "match_job", "ok": True}],
              "cartoes": [{"tipo": "vaga", "job_id": orla["id"], "titulo": orla["titulo"], "empresa": orla["empresa"],
                           "senioridade": orla["senioridade"], "local": orla["local"], "score": 79, "cobertos": 7,
                           "total": 9, "lacunas": ["Testes end-to-end", "GraphQL"]}]})
    s1.gravar({"role": "user", "content": "Registra 30 min estudando Playwright"})
    s1.gravar({"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_estudo", "type": "function", "function": {"name": "log_study",
         "arguments": '{"minutos": 30, "o_que_fez": "Playwright", "slug": "playwright"}'}}]})
    s1.gravar({"role": "tool", "tool_call_id": "call_estudo", "content": '{"ok": true, "data": {"id": 1}}'})
    s1.gravar({"role": "assistant", "content": "Pronto, gravei 30 min de Playwright em Testes end-to-end."},
              meta={"custo_usd": 0.002, "parado": False, "cartoes": [],
                    "ferramentas": [{"nome": "log_study", "ok": True}],
                    "confirmacoes": [{"objeto": "Estudo", "resumo": "30 min em Testes end-to-end",
                                      "resultado": "gravado", "ferramenta": "log_study",
                                      "linha": "Estudo gravado · 30 min em Testes end-to-end"}]})
    s1.fechar("gpt-4o-mini", 0.006)

    s2 = agent_session.abrir(conn, "gpt-4o-mini")
    s2.gravar({"role": "user", "content": "Compara as 8 vagas abertas com o meu vault"})
    s2.gravar({"role": "assistant", "content": "Olhando as vagas abertas, a da Orla Tech é a que mais combina, e a"},
              meta={"custo_usd": 0.001, "parado": True, "cartoes": [], "confirmacoes": [], "ferramentas": []})
    s2.fechar("gpt-4o-mini", 0.001)


def semear_competencias(conn) -> None:
    """O que a Competências mostra: estudos ligados a competências nesta semana (~150 min) e na anterior, o plano
    desta semana (300 min), 3 commits sem resposta em agenda-online e um fato com métrica que o vault sugere para
    "Testes end-to-end" (nível 2 com 1 evidência), para a recusa do nível 3 ter o que ligar."""
    import json
    from datetime import date

    agora = store.utcnow()
    hoje = date.today()
    segunda = hoje - timedelta(days=hoje.weekday())

    def comp(slug):
        return conn.execute("SELECT id FROM competencies WHERE slug = ?", (slug,)).fetchone()[0]

    def dia(d: date) -> str:
        return min(d, hoje).isoformat()

    tipo, entidade = NOTAS[AGENDA]
    with conn:
        conn.execute("INSERT OR REPLACE INTO facts (nota, block_id, tipo, entidade, texto, tags, indexado_em)"
                     " VALUES (?, 'e2e-metrica', ?, ?, ?, ?, ?)",
                     (AGENDA, tipo, entidade, "Reduzi o tempo da suíte end-to-end de 11 para 4 minutos em 12/09/2026.",
                      json.dumps(["playwright"]), agora))
        estudos = [(segunda, "playwright", 30, "mocks de rede no Playwright"),
                   (segunda + timedelta(days=1), "graphql", 45, "schema e resolvers"),
                   (segunda + timedelta(days=2), "playwright", 40, "fixtures e page objects"),
                   (hoje - timedelta(days=1) if hoje > segunda else hoje, "python", 35, "tipagem com mypy"),
                   (segunda - timedelta(days=3), "playwright", 25, "seletores por papel"),
                   (segunda - timedelta(days=5), "graphql", 50, "curso introdutório")]
        for quando, slug, minutos, o_que_fez in estudos:
            conn.execute("INSERT INTO study_sessions (data, competency_id, minutos, o_que_fez, criado_em)"
                         " VALUES (?, ?, ?, ?, ?)", (dia(quando), comp(slug), minutos, o_que_fez, agora))
        ano, num, _ = hoje.isocalendar()
        plano = conn.execute("INSERT INTO study_plan (semana, objetivo, criado_em) VALUES (?, 'Fechar lacunas', ?)",
                             (f"{ano}-W{num:02d}", agora)).lastrowid
        for slug, descricao, minutos in [("playwright", "Testes de rede e fixtures", 120),
                                         ("graphql", "Schema, resolvers e um cliente", 120),
                                         ("python", "Tipagem estática", 60)]:
            conn.execute("INSERT INTO plan_items (plan_id, competency_id, descricao, minutos_alvo) VALUES (?, ?, ?, ?)",
                         (plano, comp(slug), descricao, minutos))
        for i, (dias, resumo) in enumerate([(0, "test: cobre o fluxo de reagendamento com Playwright"),
                                             (1, "feat: consulta de horários via GraphQL"),
                                             (3, "refactor: page objects da agenda")]):
            conn.execute("INSERT INTO activity_signals (data, repo, ref, resumo, estado, criado_em)"
                         " VALUES (?, 'agenda-online', ?, ?, 'novo', ?)",
                         (dia(hoje - timedelta(days=dias)), f"semente{i:034d}", resumo, agora))


def main(caminho: str, caminho_yaml: str | None = None) -> None:
    conn = store.connect(caminho)
    agora = store.utcnow()
    with conn:
        for slug, nome, categoria, nivel, notas in COMPETENCIAS:
            cid = conn.execute("INSERT OR IGNORE INTO competencies (slug, nome, categoria, criado_em) VALUES (?, ?, ?, ?)",
                               (slug, nome, categoria, agora)).lastrowid or conn.execute(
                "SELECT id FROM competencies WHERE slug = ?", (slug,)).fetchone()[0]
            for i, nota in enumerate(notas):
                conn.execute("INSERT OR IGNORE INTO evidence (competency_id, nota, block_id, forca, criado_em)"
                             " VALUES (?, ?, ?, 3, ?)", (cid, nota, f"{slug}-{i}", agora))
            if nivel is not None:
                conn.execute("INSERT INTO competency_state (competency_id, nivel, justificativa, origem, criado_em)"
                             " VALUES (?, ?, 'Uso no dia a dia nos projetos do vault, com resultado medido.', 'declarado', ?)",
                             (cid, nivel, (AGORA - timedelta(days=30)).isoformat(timespec="seconds")))
        for empresa, titulo, local, senioridade, dias, status, reqs in VAGAS:
            quando = (AGORA - timedelta(days=dias)).isoformat(timespec="seconds")
            texto = SOBRE.get(empresa, f"{titulo} na {empresa}. Time pequeno, produto próprio e trabalho junto de design e backend.")
            job = conn.execute(
                "INSERT INTO jobs (empresa, titulo, url, fonte, senioridade, local, texto_bruto, hash_texto, coletado_em, status)"
                " VALUES (?, ?, ?, 'colado', ?, ?, ?, ?, ?, ?)",
                (empresa, titulo, f"https://vagas.example/{empresa.lower().replace(' ', '-')}/{dias}", senioridade, local,
                 texto, f"semente-{empresa}-{titulo}", quando, status)).lastrowid
            for texto_req, tipo, slug in reqs:
                conn.execute("INSERT INTO job_requirements (job_id, texto, tipo, competency_id) VALUES"
                             " (?, ?, ?, (SELECT id FROM competencies WHERE slug = ?))", (job, texto_req, tipo, slug))
    semear_inicio(conn)
    semear_conversas(conn)
    semear_competencias(conn)
    if caminho_yaml:
        from pathlib import Path

        semear_curriculos(conn, caminho_yaml, str(Path(caminho).parent / "saida-cv"))
    print(f"semente gravada em {caminho}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
