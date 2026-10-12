// Currículo a partir da estrutura do Hermes (`cv-<idioma>.json`). Nada aqui é editado à mão:
// o conteúdo vem do vault; este arquivo só decide a aparência.
//
// Entrada: `sys.inputs.dados`, o JSON inteiro como texto (`hermes cv pdf` passa).
// Saída auxiliar para a checagem de páginas: metadata <paginas> e <medida> (altura de cada entrada).

#let dados = json(bytes(sys.inputs.dados))

#let tinta = rgb("#1a1a1a")
#let apagado = rgb("#444444")

#set document(title: dados.nome, author: dados.nome)
#set page(paper: "us-letter", margin: (x: 1.3cm, top: 1.1cm, bottom: 1.1cm))
#set text(font: ("XCharter", "Libertinus Serif"), size: 10pt, fill: tinta,
          lang: dados.idioma, hyphenate: false)
#set par(justify: false, leading: 0.5em, spacing: 0.5em)
#set list(indent: 0.35em, body-indent: 0.45em, spacing: 0.3em, marker: [•])
#show link: set text(fill: tinta)

// Mede a entrada antes de desenhar: é o que diz "o que ocupa mais espaço" quando passa da página.
#let medido(secao, titulo, corpo) = layout(tamanho => {
  let altura = measure(block(width: tamanho.width, corpo)).height
  [#metadata((secao: secao, titulo: titulo, altura: altura / 1pt)) <medida>]
  corpo
})

#let secao(titulo) = {
  v(0.55em)
  block(width: 100%, below: 0.5em, inset: (bottom: 2.5pt), stroke: (bottom: 0.6pt + tinta),
        text(size: 11pt, weight: "bold", smallcaps(titulo)))
}

// ------------------------------------------------------------------ cabeçalho

#align(center, {
  text(size: 17pt, weight: "bold", dados.nome)
  if dados.cargo != "" {
    linebreak()
    text(size: 11pt, dados.cargo)
  }
  let contato = dados.contato.map(c => if c.url != none { link(c.url, c.texto) } else { c.texto })
  let idiomas = if dados.idiomas.len() > 0 { (dados.idiomas.join(", "),) } else { () }
  let metade = calc.min(3, contato.len())
  set text(size: 8.5pt)
  v(-0.1em)
  [#contato.slice(0, metade).join([ #h(0.2em)|#h(0.2em) ])]
  let resto = contato.slice(metade) + idiomas
  if resto.len() > 0 {
    linebreak()
    [#resto.join([ #h(0.2em)|#h(0.2em) ])]
  }
})

#if dados.resumo != "" {
  v(0.3em)
  dados.resumo
}

// ------------------------------------------------------------------ entradas

#let bullets(e) = list(..e.bullets.map(b => b.texto))

#if dados.experiencias.len() > 0 {
  secao(dados.rotulos.experience)
  for e in dados.experiencias {
    medido("experiencias", e.titulo, block(breakable: true, below: 0.5em, {
      grid(columns: (1fr, auto), row-gutter: 0.35em,
        text(weight: "bold", if e.cargo != "" { e.cargo } else { e.titulo }),
        e.periodo,
        if e.cargo != "" { emph(e.titulo) } else { [] },
        emph(e.local),
      )
      v(0.1em)
      bullets(e)
    }))
  }
}

#if dados.projetos.len() > 0 {
  secao(dados.rotulos.project)
  for e in dados.projetos {
    medido("projetos", e.titulo, block(breakable: true, below: 0.5em, {
      let nome = if e.link != none { link(e.link, e.titulo) } else { e.titulo }
      text(weight: "bold", {
        nome
        if e.subtitulo != "" [ – #e.subtitulo]
      })
      if e.stack.len() > 0 {
        [ #h(0.1em)|#h(0.1em) ]
        text(size: 8.5pt, emph(e.stack.join(", ")))
      }
      v(0.05em)
      bullets(e)
    }))
  }
}

// ------------------------------------------------------------------ fim da página

#if dados.habilidades.len() > 0 {
  secao(dados.rotulos.competencias)
  let rotulados = dados.habilidades.filter(h => h.rotulo != "")
  if rotulados.len() > 0 {
    grid(columns: (auto, 1fr), column-gutter: 1.2em, row-gutter: 0.42em,
      ..rotulados.map(h => (text(weight: "bold", h.rotulo), h.itens.join(", "))).flatten())
  }
  for h in dados.habilidades.filter(h => h.rotulo == "") {
    h.itens.join(", ")
  }
}

#if dados.formacao.len() > 0 {
  secao(dados.rotulos.formacao)
  for f in dados.formacao {
    grid(columns: (1fr, auto),
      {
        text(weight: "bold", f.curso)
        if f.instituicao != "" [ – #emph(f.instituicao)]
      },
      f.periodo,
    )
  }
}

#context [#metadata(counter(page).final().first()) <paginas>]
