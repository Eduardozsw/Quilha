"""Candidaturas: o que foi enviado, para quem, com qual perfil — e a nota de cada perfil.

Aqui só há regra e SQL. Quem fala com o Gmail é `hermes.integracoes.gmail`; quem classifica é
`triagem_email` (Jev). A ligação e-mail ↔ candidatura é determinística: ambiguidade vira pendência
para você resolver, nunca palpite.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone
from email.utils import parseaddr

from hermes.db import store

MATURACAO_DIAS = 21  # antes disso, sem resposta, o envio ainda não diz nada
MIN_ENVIOS = 10  # abaixo disso a taxa é ruído
MIN_ENVIOS_ZERO = 100  # zero avanços só vira nota 0 com esse volume
GERAL = "geral"  # currículo gerado sem --perfil
PROCESSO = ("avanco", "pendencia", "inscricao_confirmada", "reprovado")
STATUS = ("a_enviar", "enviada", "em_processo", "entrevista", "reprovada", "cancelada")
CORTES = ((0.20, 5), (0.10, 4), (0.05, 3), (0.02, 2))


class CandidaturaRecusada(Exception):
    pass


def nota(maturados: int, avancos: int) -> int | None:
    """0–5 pela taxa de avanço; None quando ainda não há dados para julgar."""
    if avancos == 0:
        return 0 if maturados >= MIN_ENVIOS_ZERO else None
    if maturados < MIN_ENVIOS:
        return None
    taxa = avancos / maturados
    for corte, valor in CORTES:
        if taxa >= corte:
            return valor
    return 1


def maturada(enviada_em: str, respondida_em: str | None, hoje: date) -> bool:
    if respondida_em:
        return True
    return (hoje - date.fromisoformat(enviada_em[:10])).days >= MATURACAO_DIAS


_SUFIXOS = re.compile(
    r"\b(?:s a|sa|ltda|ltd|inc|llc|group|global|brasil|unibanco|an indra company)\b"
)


def normalizar_empresa(texto: str | None) -> str:
    """Chave de comparação: sem acento, sem pontuação, sem sufixo societário."""
    if not texto:
        return ""
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = _SUFIXOS.sub(" ", s)
    return " ".join(s.split())


# ATS, redes e provedores pessoais: o domínio nunca é a empresa
_DOMINIOS_ATS = ("gupy.com.br", "recrut.ai", "inhire.app", "greenhouse-mail.io", "greenhouse.io",
                 "myworkday.com", "workday.com", "ashbyhq.com", "lever.co", "linkedin.com",
                 "eureca.me", "universia.net", "kenoby.com", "solides.com.br", "smartrecruiters.com",
                 "teamtailor.com", "teamtailor-mail.com", "vagas.com.br", "workable.com", "jobvite.com",
                 "icims.com", "taleo.net", "successfactors.com", "bamboohr.com", "recruitee.com",
                 "breezy.hr", "infojobs.com.br", "catho.com.br", "indeed.com", "glassdoor.com",
                 "sesametime.com")
_PROVEDORES = ("gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
               "yahoo.com.br", "icloud.com", "me.com", "uol.com.br", "bol.com.br", "terra.com.br",
               "proton.me", "protonmail.com")
# ATS que põem o nome da empresa no remetente ("AUREO S.A." <no-reply@gupy.com.br>)
_ATS_COM_NOME = ("gupy.com.br", "recrut.ai", "ashbyhq.com", "sesametime.com")
# ATS que põem a empresa no usuário do endereço (quartzo@ses-mail.inhire.app)
_ATS_NO_USUARIO = ("inhire.app",)
# nome que começa com uma dessas palavras é assunto, cargo ou equipe, não empresa
_GENERICAS = {
    "processo", "etapa", "proxima", "proximos", "interview", "entrevista", "feedback", "vaga", "vagas",
    "programa", "candidatura", "application", "inscricao", "confirmacao", "ola", "oi", "hello", "hi",
    "convite", "invitation", "atualizacao", "update", "onboarding", "teste", "test", "desafio", "welcome",
    "bem", "equipe", "time", "team", "recrutamento", "recruiting", "recruitment", "talent", "people", "rh",
    "seu", "sua", "your", "voce", "obrigado", "thank", "thanks", "parabens", "congratulations",
    "encerramento", "urgente", "importante", "lembrete", "reminder", "status", "aviso", "resultado",
    "next", "estagio", "trainee", "internship", "summer", "software", "engineer", "developer",
    "desenvolvedor", "analista", "engenheiro", "engenharia", "noreply", "no", "careers", "gupy",
    "linkedin", "assets", "dev",
}
# rótulos de domínio que não identificam ninguém (TLD, país, subdomínio de envio)
_GENERICOS_DOMINIO = {
    "mail", "email", "e", "em", "em1", "em2", "send", "mailer", "bounce", "noreply", "no-reply",
    "notifications", "notification", "news", "jobs", "careers", "com", "br", "net", "org", "co", "io",
    "us", "uk", "eu", "ai", "app", "dev", "tech", "me", "info", "biz", "gov", "edu", "pt", "de", "fr",
    "es", "it", "mx", "ar", "cl", "in", "ca", "au", "online", "site",
}
_COLCHETE = re.compile(r"^\s*\[([^\]]{2,40})\]")
_PREFIXO_BARRA = re.compile(r"^\s*([^|]{2,30}?)\s*\|")
_PREPOSICAO = re.compile(
    r"(?:\b(?:na|no|pela|pelo|at|to|em|by)|(?<!\w)à)\s+([A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*){0,3})"
)


def _vale(nome: str | None) -> str | None:
    nome = (nome or "").strip(" .:!,")
    norm = normalizar_empresa(nome)
    return nome if norm and norm.split()[0] not in _GENERICAS else None


def _termina_em(dominio: str, lista) -> bool:
    return any(dominio == d or dominio.endswith("." + d) for d in lista)


def _do_dominio(dominio: str) -> str | None:
    partes = [p for p in dominio.split(".") if p not in _GENERICOS_DOMINIO]
    return partes[-1] if partes else None


def _do_assunto(assunto: str) -> str | None:
    """Colchete no início, "Empresa | ..." curto, ou "na/à/at/to Empresa"."""
    achado = _COLCHETE.match(assunto)
    if achado and _vale(achado.group(1)):
        return _vale(achado.group(1))
    achado = _PREFIXO_BARRA.match(assunto)
    if achado and len(achado.group(1).split()) <= 3 and _vale(achado.group(1)):
        return _vale(achado.group(1))
    for achado in _PREPOSICAO.finditer(assunto):
        if _vale(achado.group(1)):
            return _vale(achado.group(1))
    return None


def _concordam(assunto: str, dominio: str) -> bool:
    return normalizar_empresa(assunto).split()[0] in normalizar_empresa(dominio).split()


def empresa_do_email(de: str, assunto: str) -> str | None:
    """Empresa do processo, pela ordem de confiança. None = não dá para saber só por aqui.

    Domínio próprio da empresa vence o assunto (assunto é texto livre: "Invitation to Interview");
    o assunto só vale sozinho quando o remetente é um ATS ou um provedor pessoal.
    """
    nome, endereco = parseaddr(de)
    usuario, _, dominio = endereco.lower().rpartition("@")

    if _termina_em(dominio, _DOMINIOS_ATS):
        if nome and _termina_em(dominio, _ATS_COM_NOME) and _vale(nome.split("|")[0]):
            if not _COLCHETE.match(assunto) or not _vale(_COLCHETE.match(assunto).group(1)):
                return _vale(nome.split("|")[0])
        if _termina_em(dominio, _ATS_NO_USUARIO) and _vale(usuario):
            return _vale(usuario)
        return _do_assunto(assunto)
    if _termina_em(dominio, _PROVEDORES):
        return _do_assunto(assunto)
    proprio = _vale(_do_dominio(dominio))
    do_assunto = _do_assunto(assunto)
    if proprio and do_assunto and not _concordam(do_assunto, proprio):
        return proprio
    return do_assunto or proprio

def _existe(conn: sqlite3.Connection, candidatura_id: int) -> sqlite3.Row:
    linha = conn.execute("SELECT * FROM candidaturas WHERE id = ?", (candidatura_id,)).fetchone()
    if linha is None:
        raise CandidaturaRecusada(f"candidatura {candidatura_id} não existe")
    return linha


def _inserir(conn, *, empresa, titulo, perfil, origem, enviada_em, job_id=None, cv_version_id=None,
             status="enviada") -> int:
    agora = store.utcnow()
    cur = conn.execute(
        "INSERT INTO candidaturas (job_id, empresa, empresa_norm, titulo, perfil, cv_version_id,"
        " origem, enviada_em, status, atualizada_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, empresa, normalizar_empresa(empresa) or None, titulo, perfil, cv_version_id,
         origem, enviada_em or agora, status, agora),
    )
    return int(cur.lastrowid)


def registrar_do_cv(conn: sqlite3.Connection, job_id: int, perfil: str | None,
                    cv_version_id: int | None, trocar_versao: bool = True) -> int:
    """Currículo gerado para a vaga vira candidatura `a_enviar`: só conta como envio quando a pessoa
    marca (`marcar_enviada`) ou quando chega e-mail do processo. Gerar de novo só atualiza perfil e versão.
    Com `trocar_versao=False` (gerou só o inglês), a candidatura que já existe fica com a versão que tinha."""
    vaga = conn.execute("SELECT empresa, titulo FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if vaga is None:
        raise CandidaturaRecusada(f"vaga {job_id} não existe")
    perfil = perfil or GERAL
    with conn:
        linha = conn.execute("SELECT id FROM candidaturas WHERE job_id = ?", (job_id,)).fetchone()
        if linha is None:
            cid = _inserir(conn, empresa=vaga["empresa"], titulo=vaga["titulo"], perfil=perfil,
                           origem="cv", enviada_em=None, job_id=job_id, cv_version_id=cv_version_id,
                           status="a_enviar")
        else:
            cid = linha["id"]
            versao = "COALESCE(?, cv_version_id)" if trocar_versao else "COALESCE(cv_version_id, ?)"
            conn.execute(
                f"UPDATE candidaturas SET perfil = ?, cv_version_id = {versao},"
                " atualizada_em = ? WHERE id = ?", (perfil, cv_version_id, store.utcnow(), cid))
    return cid


def _data_de_envio(quando: str) -> str:
    """AAAA-MM-DD (ou ISO com hora) que não esteja no futuro: envio é o que já aconteceu."""
    try:
        dia = date.fromisoformat(quando[:10])
    except ValueError:
        raise CandidaturaRecusada(f"data `{quando}` inválida; use AAAA-MM-DD") from None
    if dia > date.today():
        raise CandidaturaRecusada("a data de envio não pode ser no futuro")
    return quando


def marcar_enviada(conn: sqlite3.Connection, candidatura_id: int, quando: str | None = None) -> dict:
    """"Marquei como enviada": a candidatura `a_enviar` passa a contar, com a data do envio."""
    atual = _existe(conn, candidatura_id)
    if atual["status"] != "a_enviar":
        raise CandidaturaRecusada("já está marcada como enviada")
    quando = _data_de_envio(quando or date.today().isoformat())
    with conn:
        conn.execute("UPDATE candidaturas SET status = 'enviada', enviada_em = ?, atualizada_em = ? WHERE id = ?",
                     (quando, store.utcnow(), candidatura_id))
        if atual["job_id"]:
            conn.execute("UPDATE jobs SET status = 'aplicado' WHERE id = ?", (atual["job_id"],))
    recalcular(conn, candidatura_id)
    return detalhe(conn, candidatura_id)


def registrar_manual(conn: sqlite3.Connection, empresa: str, perfil: str, titulo: str | None = None,
                     enviada_em: str | None = None) -> int:
    if not normalizar_empresa(empresa):
        raise CandidaturaRecusada("empresa vazia")
    if enviada_em is not None:
        if len(enviada_em) != 10:  # só o dia, como sempre foi aqui
            raise CandidaturaRecusada(f"data `{enviada_em}` inválida; use AAAA-MM-DD")
        _data_de_envio(enviada_em)
    with conn:
        return _inserir(conn, empresa=empresa, titulo=titulo, perfil=perfil, origem="manual",
                        enviada_em=enviada_em)


def ligar_vaga(conn: sqlite3.Connection, candidatura_id: int, job_id: int) -> dict:
    """Liga uma vaga gravada à candidatura feita à mão (ou que nasceu de e-mail): com ela, dá para preparar a
    entrevista pelas lacunas. Uma vaga é de uma candidatura só."""
    atual = _existe(conn, candidatura_id)
    if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is None:
        raise CandidaturaRecusada(f"vaga {job_id} não existe")
    with conn:  # a checagem e a troca na mesma transação: duas janelas não ligam a mesma vaga a duas candidaturas
        if not conn.in_transaction:  # trava de escrita já na leitura (quem chama pode ter transação aberta)
            conn.execute("BEGIN IMMEDIATE")
        outra = conn.execute("SELECT id, empresa FROM candidaturas WHERE job_id = ? AND id != ?",
                             (job_id, candidatura_id)).fetchone()
        if outra:
            raise CandidaturaRecusada(f"essa vaga já está na candidatura de {outra['empresa'] or '#' + str(outra['id'])}")
        conn.execute("UPDATE candidaturas SET job_id = ?, atualizada_em = ? WHERE id = ?",
                     (job_id, store.utcnow(), candidatura_id))
        if atual["status"] != "a_enviar":
            conn.execute("UPDATE jobs SET status = 'aplicado' WHERE id = ?", (job_id,))
        # trocou de vaga: a anterior, sem outra candidatura, volta para as abertas
        anterior = atual["job_id"]
        if anterior and anterior != job_id and not conn.execute(
                "SELECT 1 FROM candidaturas WHERE job_id = ?", (anterior,)).fetchone():
            conn.execute("UPDATE jobs SET status = 'analisado' WHERE id = ? AND status = 'aplicado'", (anterior,))
    return detalhe(conn, candidatura_id)


def definir_perfil(conn: sqlite3.Connection, candidatura_id: int, perfil: str) -> None:
    _existe(conn, candidatura_id)
    with conn:
        conn.execute("UPDATE candidaturas SET perfil = ?, atualizada_em = ? WHERE id = ?",
                     (perfil, store.utcnow(), candidatura_id))


def cancelar(conn: sqlite3.Connection, candidatura_id: int) -> None:
    _existe(conn, candidatura_id)
    with conn:
        conn.execute("UPDATE candidaturas SET status = 'cancelada', atualizada_em = ? WHERE id = ?",
                     (store.utcnow(), candidatura_id))


def descartar_rascunho(conn: sqlite3.Connection, candidatura_id: int) -> dict:
    """"Não vou enviar" (PM, 10/10): o currículo gerado não vira candidatura. Devolve a linha para o desfazer."""
    c = _existe(conn, candidatura_id)
    if c["status"] != "a_enviar":
        raise CandidaturaRecusada("só a candidatura a enviar pode ser descartada")
    if conn.execute("SELECT 1 FROM emails WHERE candidatura_id = ?", (candidatura_id,)).fetchone():
        raise CandidaturaRecusada("a candidatura já tem e-mails ligados")
    with conn:
        conn.execute("DELETE FROM candidaturas WHERE id = ?", (candidatura_id,))
    return dict(c)


_RASCUNHO = ("id", "job_id", "empresa", "empresa_norm", "titulo", "perfil", "cv_version_id", "origem",
             "enviada_em", "entrevista_titulo", "roteiro", "roteiro_em", "atualizada_em")


def restaurar_rascunho(conn: sqlite3.Connection, linha: dict) -> dict:
    """O "Desfazer" do "Não vou enviar": a mesma candidatura volta, com o mesmo id, em `a_enviar`."""
    if conn.execute("SELECT 1 FROM candidaturas WHERE id = ? OR (job_id IS NOT NULL AND job_id = ?)",
                    (linha.get("id"), linha.get("job_id"))).fetchone():
        raise CandidaturaRecusada("essa candidatura já voltou ou a vaga já tem outra")
    if linha.get("origem") not in ("cv", "email", "manual") or not linha.get("enviada_em"):
        raise CandidaturaRecusada("rascunho inválido")
    with conn:
        conn.execute(f"INSERT INTO candidaturas ({', '.join(_RASCUNHO)}, status) VALUES"
                     f" ({', '.join('?' * len(_RASCUNHO))}, 'a_enviar')",
                     (*(linha.get(k) for k in _RASCUNHO[:-1]), linha.get("atualizada_em") or store.utcnow()))
    return detalhe(conn, linha["id"])


def reabrir(conn: sqlite3.Connection, candidatura_id: int, anterior: str | None = None) -> dict:
    """Desfaz o cancelamento: volta a `a_enviar` se era essa a etapa, senão a etapa sai dos e-mails.
    Sem `anterior` (Reabrir pelo menu), currículo gerado cuja vaga não ficou `aplicado` era rascunho."""
    c = _existe(conn, candidatura_id)
    if c["status"] != "cancelada":
        raise CandidaturaRecusada("a candidatura não está cancelada")
    if anterior is None and c["origem"] == "cv" and c["job_id"] and not c["entrevista_em"]:
        vaga = conn.execute("SELECT status FROM jobs WHERE id = ?", (c["job_id"],)).fetchone()
        sem_emails = not conn.execute("SELECT 1 FROM emails WHERE candidatura_id = ?", (candidatura_id,)).fetchone()
        if vaga and vaga["status"] != "aplicado" and sem_emails:
            anterior = "a_enviar"
    with conn:
        conn.execute("UPDATE candidaturas SET status = ? WHERE id = ?",
                     ("a_enviar" if anterior == "a_enviar" else "enviada", candidatura_id))
    recalcular(conn, candidatura_id)
    return detalhe(conn, candidatura_id)


COLUNAS_EMAIL = ("gmail_id", "recebido_em", "de", "assunto", "corpo", "categoria_jev", "prob_categoria",
                 "prob_processo", "prob_prazo", "final", "empresa_extraida", "latencia_ms", "entrevista_em")


def inserir_email(conn: sqlite3.Connection, dados: dict) -> int:
    with conn:
        cur = conn.execute(
            f"INSERT INTO emails ({', '.join(COLUNAS_EMAIL)}, processado_em)"
            f" VALUES ({', '.join('?' * len(COLUNAS_EMAIL))}, ?)",
            (*(dados.get(c) for c in COLUNAS_EMAIL), store.utcnow()),
        )
    return int(cur.lastrowid)


def _categoria(email: sqlite3.Row) -> str:
    return email["rotulo_manual"] or email["final"]


def _palavras(texto: str | None) -> set[str]:
    return {p for p in normalizar_empresa(texto).split() if len(p) >= 3}


def _escolher(candidatas: list[sqlite3.Row], email: sqlite3.Row) -> int | None:
    """Uma candidatura da empresa: ela. Várias: a de mais palavras do título no assunto; empate = None."""
    if len(candidatas) == 1:
        return candidatas[0]["id"]
    assunto = _palavras(email["assunto"])
    pontos = sorted(((len(_palavras(c["titulo"]) & assunto), c["id"]) for c in candidatas), reverse=True)
    if pontos[0][0] > 0 and pontos[0][0] > pontos[1][0]:
        return pontos[0][1]
    return None


def ligar(conn: sqlite3.Connection, email_id: int) -> int | None:
    """Liga o e-mail à candidatura da empresa, criando a pingada se não houver. None = pendente.

    Candidatura reprovada antes deste e-mail está encerrada: e-mail novo da mesma empresa (que não
    seja outra reprovação) é de outro processo. Pingada, ligação e status entram juntos ou não entram.
    """
    email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    categoria = _categoria(email)
    norm = normalizar_empresa(email["empresa_extraida"])
    if categoria not in PROCESSO or not norm:
        return None
    candidatas = conn.execute(
        "SELECT c.id, c.titulo, c.status, (SELECT MAX(e.recebido_em) FROM emails e"
        "  WHERE e.candidatura_id = c.id AND COALESCE(e.rotulo_manual, e.final) = 'reprovado')"
        " AS reprovada_em FROM candidaturas c WHERE c.empresa_norm = ? AND c.status != 'cancelada'",
        (norm,)).fetchall()
    abertas = [c for c in candidatas if not (
        c["status"] == "reprovada" and (c["reprovada_em"] or "") < email["recebido_em"])]
    if categoria != "reprovado" or abertas:
        candidatas = abertas
    cid = _escolher(candidatas, email) if candidatas else None
    if candidatas and cid is None:
        return None
    with conn:
        if cid is None:
            cid = _inserir(conn, empresa=email["empresa_extraida"], titulo=None, perfil=None,
                           origem="email", enviada_em=email["recebido_em"])
        conn.execute("UPDATE emails SET candidatura_id = ? WHERE id = ?", (cid, email_id))
        _entrevista_dos_emails(conn, cid)
        recalcular(conn, cid)
    return cid


def _data_do_email(conn: sqlite3.Connection, email_id: int) -> str | None:
    return conn.execute("SELECT entrevista_em FROM emails WHERE id = ?", (email_id,)).fetchone()[0]


def _entrevista_dos_emails(conn: sqlite3.Connection, candidatura_id: int, saindo: str | None = None) -> None:
    """A data da entrevista acompanha o e-mail ligado mais recente que marca uma (remarcação vence).

    Data digitada à mão (diferente de toda data vinda de e-mail) fica: o lembrete que chega depois não a desfaz.
    `saindo` é a data do e-mail que acabou de ser desligado: se a candidatura estava com ela, ela sai junto.
    """
    atual = conn.execute("SELECT entrevista_em FROM candidaturas WHERE id = ?", (candidatura_id,)).fetchone()[0]
    datas = [r[0] for r in conn.execute(
        "SELECT entrevista_em FROM emails WHERE candidatura_id = ? AND entrevista_em IS NOT NULL"
        " ORDER BY recebido_em, id", (candidatura_id,))]
    if atual is not None and atual not in datas and atual != saindo:
        return
    conn.execute("UPDATE candidaturas SET entrevista_em = ? WHERE id = ?", (datas[-1] if datas else None, candidatura_id))


def ligar_manual(conn: sqlite3.Connection, email_id: int, candidatura_id: int) -> None:
    _existe(conn, candidatura_id)
    antiga = conn.execute("SELECT candidatura_id FROM emails WHERE id = ?", (email_id,)).fetchone()
    if antiga is None:
        raise CandidaturaRecusada(f"e-mail {email_id} não existe")
    with conn:
        conn.execute("UPDATE emails SET candidatura_id = ? WHERE id = ?", (candidatura_id, email_id))
        _entrevista_dos_emails(conn, candidatura_id)
        if antiga[0] and antiga[0] != candidatura_id:
            _entrevista_dos_emails(conn, antiga[0], saindo=_data_do_email(conn, email_id))
    if antiga[0] and antiga[0] != candidatura_id:
        recalcular(conn, antiga[0])
    recalcular(conn, candidatura_id)


def desligar(conn: sqlite3.Connection, email_id: int) -> None:
    """Desfaz uma ligação errada: o e-mail volta a pendente e a candidatura recalcula sem ele."""
    linha = conn.execute("SELECT candidatura_id FROM emails WHERE id = ?", (email_id,)).fetchone()
    if linha is None:
        raise CandidaturaRecusada(f"e-mail {email_id} não existe")
    if linha[0] is None:
        return
    with conn:
        conn.execute("UPDATE emails SET candidatura_id = NULL WHERE id = ?", (email_id,))
        _entrevista_dos_emails(conn, linha[0], saindo=_data_do_email(conn, email_id))
    recalcular(conn, linha[0])


CORRIGIVEIS = (*PROCESSO, "outro")


def corrigir(conn: sqlite3.Connection, email_id: int, categoria: str) -> int | None:
    """Rótulo manual vence o do Jev e alimenta `email avaliar`. Devolve a candidatura ligada."""
    if categoria not in CORRIGIVEIS:
        raise CandidaturaRecusada(f"categoria `{categoria}` inválida; use {', '.join(CORRIGIVEIS)}")
    email = conn.execute("SELECT candidatura_id FROM emails WHERE id = ?", (email_id,)).fetchone()
    if email is None:
        raise CandidaturaRecusada(f"e-mail {email_id} não existe")
    cid = email["candidatura_id"]
    with conn:
        conn.execute("UPDATE emails SET rotulo_manual = ? WHERE id = ?", (categoria, email_id))
        if categoria == "outro":
            conn.execute("UPDATE emails SET candidatura_id = NULL WHERE id = ?", (email_id,))
            if cid is not None:
                _entrevista_dos_emails(conn, cid, saindo=_data_do_email(conn, email_id))
    if cid is not None:
        recalcular(conn, cid)
        return None if categoria == "outro" else cid
    return ligar(conn, email_id)


def triar(conn: sqlite3.Connection, email_id: int, categoria: str, *, candidatura_id: int | None = None,
          nova: bool = False, empresa: str | None = None) -> dict:
    """Um passo da triagem, na ordem certa: empresa, categoria e a ligação escolhida (uma candidatura, uma
    nova ou a automática pela empresa). `criada` é a pingada que este passo criou, para o desfazer apagar."""
    if categoria not in CORRIGIVEIS:
        raise CandidaturaRecusada(f"categoria `{categoria}` inválida; use {', '.join(CORRIGIVEIS)}")
    email(conn, email_id)
    if candidatura_id is not None:
        _existe(conn, candidatura_id)
    antes = conn.execute("SELECT COALESCE(MAX(id), 0) FROM candidaturas").fetchone()[0]
    empresa = (empresa or "").strip() or None
    estado = _estado_antes(conn, email_id, categoria, candidatura_id, nova, empresa)
    if empresa:
        with conn:
            conn.execute("UPDATE emails SET empresa_extraida = ? WHERE id = ?", (empresa, email_id))
    if categoria == "outro":
        corrigir(conn, email_id, categoria)
        return {"candidatura_id": None, "criada": None}
    if candidatura_id is not None or nova:
        with conn:
            conn.execute("UPDATE emails SET rotulo_manual = ? WHERE id = ?", (categoria, email_id))
        if nova:
            cid = nova_do_email(conn, email_id)
        else:
            ligar_manual(conn, email_id, candidatura_id)
            cid = candidatura_id
    else:
        cid = corrigir(conn, email_id, categoria)
    return {"candidatura_id": cid, "criada": cid if cid is not None and cid > antes else None,
            "candidatura_antes": (estado if cid is not None and cid == (estado or {}).get("id") else None)}


def _estado_antes(conn, email_id, categoria, candidatura_id, nova, empresa) -> dict | None:
    """Status, data de envio e status da vaga da candidatura que este passo vai tocar, para o desfazer
    devolver (uma `a_enviar` sai dessa etapa ao receber o e-mail)."""
    if categoria == "outro" or nova:
        return None
    cid = candidatura_id
    if cid is None:
        norm = normalizar_empresa(empresa or email(conn, email_id)["empresa_extraida"])
        linhas = conn.execute("SELECT id FROM candidaturas WHERE empresa_norm = ? AND status != 'cancelada'",
                              (norm,)).fetchall() if norm else []
        cid = linhas[0]["id"] if len(linhas) == 1 else None
    if cid is None:
        return None
    c = conn.execute("SELECT c.id, c.status, c.enviada_em, j.status AS vaga_status FROM candidaturas c"
                     " LEFT JOIN jobs j ON j.id = c.job_id WHERE c.id = ?", (cid,)).fetchone()
    return dict(c) if c else None


def restaurar_email(conn: sqlite3.Connection, email_id: int, *, rotulo_manual: str | None,
                    candidatura_id: int | None, empresa: str | None, apagar: int | None = None,
                    candidatura_antes: dict | None = None) -> None:
    """O "Desfazer" da triagem: rótulo (None = volta ao do classificador), empresa e ligação de antes.
    `apagar` é a pingada que a triagem criou; só sai se nasceu de e-mail e ficou sem nenhum."""
    if rotulo_manual is not None and rotulo_manual not in CORRIGIVEIS:
        raise CandidaturaRecusada(f"categoria `{rotulo_manual}` inválida")
    linha = conn.execute("SELECT candidatura_id FROM emails WHERE id = ?", (email_id,)).fetchone()
    if linha is None:
        raise CandidaturaRecusada(f"e-mail {email_id} não existe")
    with conn:
        conn.execute("UPDATE emails SET rotulo_manual = ?, empresa_extraida = ? WHERE id = ?",
                     (rotulo_manual, empresa, email_id))
    if candidatura_id is not None:
        ligar_manual(conn, email_id, candidatura_id)
    elif linha[0] is not None:
        desligar(conn, email_id)
    if apagar is not None:
        with conn:
            conn.execute("DELETE FROM candidaturas WHERE id = ? AND origem = 'email'"
                         " AND NOT EXISTS (SELECT 1 FROM emails WHERE candidatura_id = ?)", (apagar, apagar))
    antes = candidatura_antes or {}
    if antes.get("status") == "a_enviar" and conn.execute(
            "SELECT 1 FROM candidaturas WHERE id = ? AND entrevista_em IS NULL AND NOT EXISTS"
            " (SELECT 1 FROM emails WHERE candidatura_id = ?)", (antes["id"], antes["id"])).fetchone():
        with conn:
            conn.execute("UPDATE candidaturas SET status = 'a_enviar', enviada_em = ? WHERE id = ?",
                         (antes["enviada_em"], antes["id"]))
            if antes.get("vaga_status"):
                conn.execute("UPDATE jobs SET status = ? WHERE id = (SELECT job_id FROM candidaturas WHERE id = ?)",
                             (antes["vaga_status"], antes["id"]))
        recalcular(conn, antes["id"])


def recalcular(conn: sqlite3.Connection, candidatura_id: int) -> None:
    """Status sai dos e-mails ligados, não de eventos acumulados: corrigir nunca deixa estado velho."""
    atual = _existe(conn, candidatura_id)
    eventos = conn.execute(
        "SELECT COALESCE(rotulo_manual, final) AS cat, recebido_em FROM emails"
        " WHERE candidatura_id = ? ORDER BY recebido_em, id", (candidatura_id,)).fetchall()
    respostas = [e for e in eventos if e["cat"] in ("avanco", "reprovado")]
    # entrevista marcada é avanço, venha de e-mail ou da mão do usuário
    teve_avanco = any(e["cat"] == "avanco" for e in eventos) or bool(atual["entrevista_em"])
    saindo_de_a_enviar = atual["status"] == "a_enviar" and bool(eventos or atual["entrevista_em"])
    if atual["status"] == "a_enviar" and not saindo_de_a_enviar:
        status = "a_enviar"
    elif atual["status"] == "cancelada":
        status = "cancelada"
    elif respostas and respostas[-1]["cat"] == "reprovado":
        status = "reprovada"
    elif atual["entrevista_em"]:
        status = "entrevista"
    elif teve_avanco:
        status = "em_processo"
    else:
        status = "enviada"
    with conn:
        if saindo_de_a_enviar:
            # mandou e esqueceu de marcar: o primeiro e-mail do processo (ou a entrevista) prova o envio
            if eventos:
                conn.execute("UPDATE candidaturas SET enviada_em = MIN(enviada_em, ?) WHERE id = ?",
                             (eventos[0]["recebido_em"], candidatura_id))
            if atual["job_id"]:
                conn.execute("UPDATE jobs SET status = 'aplicado' WHERE id = ?", (atual["job_id"],))
        # sem e-mail de resposta, a entrevista marcada à mão é a resposta: vale a hora em que foi marcada
        if respostas:
            respondida = respostas[0]["recebido_em"]
        elif atual["entrevista_em"]:
            respondida = atual["respondida_em"] or store.utcnow()
        else:
            respondida = None
        conn.execute(
            "UPDATE candidaturas SET status = ?, teve_avanco = ?, respondida_em = ?, atualizada_em = ?"
            " WHERE id = ?",
            (status, int(teve_avanco), respondida, store.utcnow(), candidatura_id))


def marcar_entrevista(conn: sqlite3.Connection, candidatura_id: int, quando: str | None,
                      titulo: str | None = None) -> dict:
    """Marca (ou desmarca, com None) a data da entrevista e o "O quê" dela (padrão "Entrevista").
    O status sai de `recalcular`."""
    if quando is not None:
        try:
            t = datetime.fromisoformat(quando)
        except ValueError:
            raise CandidaturaRecusada("data da entrevista em ISO, ex.: 2026-10-10T14:00:00-03:00") from None
        if t.tzinfo is None:  # sem fuso é a hora de quem usa, não UTC
            quando = t.astimezone().isoformat(timespec="seconds")
    _existe(conn, candidatura_id)
    with conn:
        conn.execute("UPDATE candidaturas SET entrevista_em = ?, entrevista_titulo = ? WHERE id = ?",
                     (quando, ((titulo or "").strip() or "Entrevista") if quando else None, candidatura_id))
    recalcular(conn, candidatura_id)
    return detalhe(conn, candidatura_id)


ENCERRADAS = ("reprovada", "cancelada")
ATIVAS_OU_A_ENVIAR = ("a_enviar", "enviada", "em_processo", "entrevista")


def _e_pingada(c: sqlite3.Row | dict) -> bool:
    return c["origem"] == "email" and c["titulo"] is None


def parecidas(conn: sqlite3.Connection, candidatura_id: int) -> list[dict]:
    """Para a pingada: as candidaturas ativas (ou a enviar) da mesma empresa com que ela pode ser juntada."""
    c = _existe(conn, candidatura_id)
    if not _e_pingada(c) or not c["empresa_norm"]:
        return []
    marcas = ", ".join("?" * len(ATIVAS_OU_A_ENVIAR))
    return [dict(r) for r in conn.execute(
        f"SELECT id, titulo, empresa, status FROM candidaturas WHERE empresa_norm = ? AND id != ?"
        f" AND status IN ({marcas}) ORDER BY enviada_em DESC, id DESC",
        (c["empresa_norm"], candidatura_id, *ATIVAS_OU_A_ENVIAR))]


def juntar(conn: sqlite3.Connection, origem_id: int, destino_id: int) -> dict:
    """A pingada era a mesma candidatura: os e-mails dela passam para o destino e ela some."""
    origem, destino = _existe(conn, origem_id), _existe(conn, destino_id)
    if origem_id == destino_id:
        raise CandidaturaRecusada("não dá para juntar uma candidatura com ela mesma")
    if origem["origem"] != "email":
        raise CandidaturaRecusada("só a candidatura que nasceu de um e-mail pode ser juntada a outra")
    if destino["status"] in ENCERRADAS:
        raise CandidaturaRecusada("a candidatura de destino está encerrada")
    with conn:
        conn.execute("UPDATE emails SET candidatura_id = ? WHERE candidatura_id = ?", (destino_id, origem_id))
        # a entrevista marcada à mão e o roteiro (que custou LLM) da pingada não se perdem
        if origem["entrevista_em"] and not destino["entrevista_em"]:
            conn.execute("UPDATE candidaturas SET entrevista_em = ?, entrevista_titulo = ? WHERE id = ?",
                         (origem["entrevista_em"], origem["entrevista_titulo"], destino_id))
        if origem["roteiro"] and not destino["roteiro"]:
            conn.execute("UPDATE candidaturas SET roteiro = ?, roteiro_em = ? WHERE id = ?",
                         (origem["roteiro"], origem["roteiro_em"], destino_id))
        _entrevista_dos_emails(conn, destino_id)
        conn.execute("DELETE FROM candidaturas WHERE id = ?", (origem_id,))
    recalcular(conn, destino_id)
    return detalhe(conn, destino_id)


def nova_do_email(conn: sqlite3.Connection, email_id: int) -> int:
    """"Nova candidatura (Empresa)" na triagem: cria a pingada com a empresa do e-mail e liga a ele,
    mesmo que já exista outra candidatura da empresa (a escolha é do usuário)."""
    atual = email(conn, email_id)
    if atual["categoria"] not in PROCESSO:
        raise CandidaturaRecusada("só e-mail de processo vira candidatura: escolha a categoria antes")
    empresa = (atual["empresa_extraida"] or "").strip()
    if not normalizar_empresa(empresa):
        raise CandidaturaRecusada("informe a empresa antes")
    antiga = atual["candidatura_id"]
    with conn:
        cid = _inserir(conn, empresa=empresa, titulo=None, perfil=None, origem="email",
                       enviada_em=atual["recebido_em"])
        conn.execute("UPDATE emails SET candidatura_id = ? WHERE id = ?", (cid, email_id))
        _entrevista_dos_emails(conn, cid)
        if antiga:
            _entrevista_dos_emails(conn, antiga, saindo=_data_do_email(conn, email_id))
    if antiga:
        recalcular(conn, antiga)
    recalcular(conn, cid)
    return cid


def salvar_roteiro(conn: sqlite3.Connection, candidatura_id: int, itens: list[dict]) -> dict:
    """O roteiro da entrevista fica na candidatura: gerar de novo substitui."""
    _existe(conn, candidatura_id)
    gerado_em = store.utcnow()
    with conn:
        conn.execute("UPDATE candidaturas SET roteiro = ?, roteiro_em = ? WHERE id = ?",
                     (json.dumps(itens, ensure_ascii=False), gerado_em, candidatura_id))
    return {"itens": itens, "gerado_em": gerado_em}


def _roteiro_salvo(c: dict) -> dict | None:
    if not c.get("roteiro"):
        return None
    try:
        itens = json.loads(c["roteiro"])
    except ValueError:
        return None
    return {"itens": itens if isinstance(itens, list) else [], "gerado_em": c["roteiro_em"]}


def listar(conn: sqlite3.Connection, status: str | None = None, pingadas: bool = False) -> list[dict]:
    sql = ("SELECT c.*, (SELECT COUNT(*) FROM emails e WHERE e.candidatura_id = c.id) AS n_emails,"
           " (SELECT MAX(e.recebido_em) FROM emails e WHERE e.candidatura_id = c.id) AS ultimo_email_em,"
           " (SELECT m.score FROM job_matches m WHERE m.job_id = c.job_id"
           "  ORDER BY m.criado_em DESC, m.id DESC LIMIT 1) AS score"
           " FROM candidaturas c")
    filtros, args = [], []
    if status:
        filtros.append("c.status = ?")
        args.append(status)
    if pingadas:
        filtros.append("(c.perfil IS NULL OR c.empresa IS NULL)")
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    return [dict(r) for r in conn.execute(sql + " ORDER BY c.enviada_em DESC, c.id DESC", args)]


def detalhe(conn: sqlite3.Connection, candidatura_id: int) -> dict:
    """A candidatura, a vaga e o currículo de onde ela veio, e os e-mails do processo em ordem."""
    c = dict(_existe(conn, candidatura_id))
    roteiro = _roteiro_salvo(c)
    c.pop("roteiro", None)
    vaga = conn.execute(
        "SELECT j.id, j.titulo, j.empresa, j.url, (SELECT m.score FROM job_matches m WHERE m.job_id = j.id"
        " ORDER BY m.criado_em DESC, m.id DESC LIMIT 1) AS score FROM jobs j WHERE j.id = ?",
        (c["job_id"],)).fetchone() if c["job_id"] else None
    cv = conn.execute("SELECT id, perfil, idioma, criado_em, palavras, json_array_length(fatos) AS n_fatos"
                      " FROM cv_versions WHERE id = ?",
                      (c["cv_version_id"],)).fetchone() if c["cv_version_id"] else None
    emails = [dict(r) for r in conn.execute(
        "SELECT id, recebido_em, de, assunto, corpo, COALESCE(rotulo_manual, final) AS categoria,"
        " rotulo_manual IS NOT NULL AS manual FROM emails WHERE candidatura_id = ?"
        " ORDER BY recebido_em, id", (candidatura_id,))]
    for e in emails:
        e["manual"] = bool(e["manual"])
    return {"candidatura": c, "vaga": dict(vaga) if vaga else None, "cv": dict(cv) if cv else None,
            "emails": emails, "parecidas": parecidas(conn, candidatura_id), "roteiro": roteiro}


def definir_titulo(conn: sqlite3.Connection, candidatura_id: int, titulo: str | None) -> None:
    """Título da vaga à mão: a pingada nasce só com a empresa do e-mail."""
    _existe(conn, candidatura_id)
    with conn:
        conn.execute("UPDATE candidaturas SET titulo = ?, atualizada_em = ? WHERE id = ?",
                     ((titulo or "").strip() or None, store.utcnow(), candidatura_id))


def emails_pendentes(conn: sqlite3.Connection) -> list[dict]:
    """`revisar` e e-mails de processo que não acharam candidatura (sem empresa ou ambíguos)."""
    marcas = ", ".join("?" * (len(PROCESSO) + 1))
    linhas = [dict(r) for r in conn.execute(
        "SELECT id, recebido_em, de, assunto, COALESCE(rotulo_manual, final) AS categoria,"
        " empresa_extraida FROM emails WHERE candidatura_id IS NULL"
        f" AND COALESCE(rotulo_manual, final) IN ({marcas})", (*PROCESSO, "revisar"))]
    # do mais antigo para o mais novo pelo instante: como texto, fusos diferentes saem fora de ordem
    return sorted(linhas, key=lambda e: (_instante(e["recebido_em"]), e["id"]))


def _instante(iso: str) -> datetime:
    """ISO com ou sem fuso (sem fuso = UTC, como o banco grava) para comparar no relógio."""
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


VISOES_EMAIL = ("pendentes", "processo", "outros")
_CAMPOS_EMAIL = (
    "SELECT e.id, e.recebido_em, e.de, e.assunto, COALESCE(e.rotulo_manual, e.final) AS categoria,"
    " e.categoria_jev, e.prob_categoria, e.rotulo_manual IS NOT NULL AS manual, e.empresa_extraida,"
    " e.candidatura_id, c.empresa AS cand_empresa, c.titulo AS cand_titulo"
    " FROM emails e LEFT JOIN candidaturas c ON c.id = e.candidatura_id"
)


def listar_emails(conn: sqlite3.Connection, visao: str = "pendentes", limite: int = 300) -> list[dict]:
    """`pendentes` = o que `emails_pendentes` devolve; `processo` = ligados a uma candidatura;
    `outros` = o que o Jev (ou você) disse não ser de processo. Sem o corpo: ele vem no detalhe."""
    if visao not in VISOES_EMAIL:
        raise CandidaturaRecusada(f"visão `{visao}` inválida; use {', '.join(VISOES_EMAIL)}")
    if visao == "pendentes":
        ids = [e["id"] for e in emails_pendentes(conn)]
        filtro, args = f"e.id IN ({', '.join('?' * len(ids))})" if ids else "0", ids
    elif visao == "processo":
        filtro, args = "e.candidatura_id IS NOT NULL", []
    else:
        filtro, args = "COALESCE(e.rotulo_manual, e.final) = 'outro'", []
    linhas = conn.execute(f"{_CAMPOS_EMAIL} WHERE {filtro} ORDER BY e.recebido_em DESC, e.id DESC LIMIT ?",
                          (*args, limite)).fetchall()
    return [{**dict(l), "manual": bool(l["manual"])} for l in linhas]


def contar_emails(conn: sqlite3.Connection) -> dict:
    linha = conn.execute(
        "SELECT COALESCE(SUM(candidatura_id IS NOT NULL), 0) AS processo,"
        " COALESCE(SUM(COALESCE(rotulo_manual, final) = 'outro'), 0) AS outros FROM emails").fetchone()
    return {"pendentes": len(emails_pendentes(conn)), "processo": linha["processo"], "outros": linha["outros"]}


def email(conn: sqlite3.Connection, email_id: int) -> dict:
    linha = conn.execute(f"{_CAMPOS_EMAIL.replace('e.empresa_extraida,', 'e.empresa_extraida, e.corpo,')}"
                         " WHERE e.id = ?", (email_id,)).fetchone()
    if linha is None:
        raise CandidaturaRecusada(f"e-mail {email_id} não existe")
    return {**dict(linha), "manual": bool(linha["manual"])}


def definir_empresa(conn: sqlite3.Connection, email_id: int, empresa: str) -> int | None:
    """A empresa que o e-mail não dizia. Liga à candidatura dela, ou cria a pingada se não houver."""
    if not normalizar_empresa(empresa):
        raise CandidaturaRecusada("empresa vazia")
    atual = email(conn, email_id)
    if atual["categoria"] not in PROCESSO:
        raise CandidaturaRecusada("só e-mail de processo vira candidatura: corrija a categoria antes")
    with conn:
        conn.execute("UPDATE emails SET empresa_extraida = ? WHERE id = ?", (empresa.strip(), email_id))
    cid = ligar(conn, email_id)
    if cid is None:
        raise CandidaturaRecusada(
            f"há mais de uma candidatura aberta em {empresa.strip()}: escolha qual na lista de candidaturas")
    return cid


def _falta(maturados: int, avancos: int) -> str:
    if maturados < MIN_ENVIOS and avancos:
        return f"faltam {MIN_ENVIOS - maturados} envios maturados"
    if avancos == 0 and maturados < MIN_ENVIOS_ZERO:
        base = f"faltam {MIN_ENVIOS - maturados} envios maturados" if maturados < MIN_ENVIOS else "sem avanço"
        return f"{base}; nota 0 só com {MIN_ENVIOS_ZERO} maturados sem avanço"
    return ""


def notas_por_perfil(conn: sqlite3.Connection, hoje: date) -> dict:
    linhas = conn.execute(
        "SELECT perfil, enviada_em, respondida_em, teve_avanco FROM candidaturas"
        " WHERE status NOT IN ('cancelada', 'a_enviar') AND perfil IS NOT NULL").fetchall()
    grupos: dict[str, dict] = {}
    for l in linhas:
        g = grupos.setdefault(l["perfil"], {"perfil": l["perfil"], "enviados": 0, "maturados": 0, "avancos": 0})
        g["enviados"] += 1
        if maturada(l["enviada_em"], l["respondida_em"], hoje):
            g["maturados"] += 1
            g["avancos"] += l["teve_avanco"]
    perfis = []
    for g in sorted(grupos.values(), key=lambda g: g["perfil"]):
        g["taxa"] = g["avancos"] / g["maturados"] if g["maturados"] else None
        g["nota"] = nota(g["maturados"], g["avancos"])
        g["falta"] = _falta(g["maturados"], g["avancos"]) if g["nota"] is None else ""
        perfis.append(g)
    pingadas = conn.execute(
        "SELECT COUNT(*) FROM candidaturas WHERE status NOT IN ('cancelada', 'a_enviar') AND perfil IS NULL"
    ).fetchone()[0]
    return {"perfis": perfis, "pingadas": pingadas}
