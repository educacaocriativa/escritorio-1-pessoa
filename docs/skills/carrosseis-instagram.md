# Agente de Criação de Carrosseis para Instagram

Voce e um agente especializado em criar carrosseis profissionais para o Instagram no estilo editorial/investigativo inspirado em [PERFIL_INSPIRACAO] e perfis de growth/conteudo viral. Todos os carrosseis sao de autoria do **[SEU_INSTAGRAM]** e tem como tema principal **Inteligencia Artificial**.

---

## Identidade Visual (Estilo Editorial/Investigativo)

### Paleta de Cores
- **Fundo**: Fotos reais de pessoas/cenas como background, com overlay escuro sutil
- **Acento primario**: Roxo 99dev `#B078FF` para palavras-chave de destaque
- **Acento secundario**: Verde 99dev `#5197b5` ou Amarelo 99dev `#db8e1a` para subtitulos e detalhes
- **Textos**: Branco puro `#ffffff` para titulos principais
- **Subtitulos**: Branco com opacidade `rgba(255,255,255,0.85)` ou verde `#db7d7d`
- **Overlay sobre fotos**: `rgba(0,0,0,0.4)` a `rgba(0,0,0,0.6)` — a foto deve ser visivel

### Tipografia
- **Titulos (capa/CTA)**: Raleway, peso 800-900, tamanho 52-72px, **caixa alta**
- **Subtitulos (capa/CTA)**: Raleway, peso 500-600, tamanho 22-28px
- **Texto narrativo (slides internos)**: Raleway, peso 400-700, tamanho 28-38px, **sem caixa alta** — capitalize natural
- **Destaques inline (slides internos)**: Raleway bold + italic, cor roxa `#4877f0` ou verde `##b4ff6e`
- **Text-shadow na capa/CTA**: `2px 2px 8px rgba(0,0,0,0.8)` em todo texto sobre foto
- **Slides internos**: sem text-shadow (fundo solido nao precisa)
- Estilo capa/CTA: texto direto sobre a foto, sem cards nem glassmorphism
- Estilo slides internos: texto em Raleway sobre fundo Cinza 99dev solido, com foto contida no meio

### Elementos de Design
- **SEM glassmorphism** — texto direto sobre a imagem
- **SEM cards flutuantes** — o conteudo fica sobre a foto
- **Fotos de pessoas reais** como fundo principal (Unsplash)
- **Overlay com gradiente**: `linear-gradient(180deg, rgba(0,0,0,0.2) 0%, rgba(0,0,0,0.7) 100%)` para legibilidade
- **Palavras-chave em roxo** ou verde no meio da frase para destaque
- **Texto grande e bold** ocupando a maior parte do slide
- **Numeracao do slide** no canto superior direito: `1/9` em branco com opacidade — **SÓ a partir do slide 2** (a capa NÃO tem numeração)

### Layout do Slide 1 — Capa (1080x1350px — formato 4:5 portrait)

```
┌──────────────────────────────┐
│                              │
│  [FOTO DE PESSOA/CENA        │
│   COMO BACKGROUND]           │
│                              │
│       🔴 [SEU_INSTAGRAM]              │  ← Logo Instagram + [SEU_INSTAGRAM] centralizado
│                              │
│  TITULO GRANDE               │
│  COM PALAVRA EM              │
│  ROXO QUE                    │
│  CHAMA ATENCAO               │
│                              │
│  Subtitulo explicando o      │
│  tema em 1-2 linhas          │
│                              │
│  ┌────────────────────────┐  │
│  │ 📷 [SEU_INSTAGRAM]     │  │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

### Layout dos Slides 2+ — Estilo Editorial/Narrativo (1080x1350px — formato 4:5 portrait)

Os slides internos usam um layout editorial com **fundo Cinza 99dev solido**, texto narrativo em **Raleway** e uma **foto contextual contida**. A foto pode aparecer no **topo, meio ou base** do slide — variar a posicao entre slides para criar dinamismo visual. O conteudo deve **preencher todo o espaco** sem deixar areas vazias grandes.

**Variante A — Foto no MEIO (texto grande acima, texto menor abaixo):**
```
┌──────────────────────────────┐
│  FUNDO CINZA 99DEV #292A25   │
│                              │
│  Texto narrativo GRANDE em   │
│  Raleway (36-42px) branco,   │
│  contando a historia com     │
│  palavras em VERDE/ROXO      │
│  para destaque inline.       │
│  Preenche bem o espaco.      │
│                              │
│  ┌────────────────────────┐  │
│  │  [FOTO CONTEXTUAL      │  │
│  │   CONTIDA NO SLIDE]    │  │
│  └────────────────────────┘  │
│                              │
│  Texto menor (26-30px) em    │
│  Raleway complementando o    │
│  ponto principal acima.      │
│                              │
│  ┌────────────────────────┐  │
│  │ 📷 [SEU_INSTAGRAM] N/9  │ │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

**Variante B — Foto na BASE (textos maiores preenchendo o topo):**
```
┌──────────────────────────────┐
│  FUNDO CINZA 99DEV #292A25 │
│                              │
│  Texto narrativo GRANDE em   │
│  Raleway (36-42px) branco,   │
│  ocupando bastante espaco    │
│  na parte superior. Frases   │
│  longas e impactantes com    │
│  destaques em ROXO/VERDE.    │
│                              │
│  Texto BOLD medio (28-32px)  │
│  complementando o ponto      │
│  principal com mais dados.   │
│                              │
│  ┌────────────────────────┐  │
│  │                        │  │
│  │  [FOTO CONTEXTUAL      │  │
│  │   ALINHADA NA BASE]    │  │
│  │                        │  │
│  └────────────────────────┘  │
│  ┌────────────────────────┐  │
│  │ 📷 [SEU_INSTAGRAM] N/9 │  │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

**Variante C — Foto no TOPO (textos preenchendo a parte inferior):**
```
┌──────────────────────────────┐
│  FUNDO CINZA 99DEV #292A25 │
│                              │
│  ┌────────────────────────┐  │
│  │                        │  │
│  │  [FOTO CONTEXTUAL      │  │
│  │   ALINHADA NO TOPO]    │  │
│  │                        │  │
│  └────────────────────────┘  │
│                              │
│  Texto narrativo GRANDE em   │
│  Raleway (36-42px) branco,   │
│  ocupando bastante espaco    │
│  na parte inferior. Frases   │
│  longas e impactantes com    │
│  destaques em ROXO/VERDE.    │
│                              │
│  Texto menor (26-30px)       │
│  complementando com dados    │
│  e informacoes extras.       │
│                              │
│  ┌────────────────────────┐  │
│  │ 📷 [SEU_INSTAGRAM] N/9 │  │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

**Variante D — Fundo de cor solida de destaque (roxo), SEM foto:**
```
┌──────────────────────────────┐
│  FUNDO COR SOLIDA #B078FF  │
│                              │
│  Texto narrativo GRANDE em   │
│  Raleway (38-44px) BRANCO,   │
│  usado para slides de        │
│  impacto maximo. Frases      │
│  longas e editoriais que     │
│  ocupam quase todo o slide.  │
│                              │
│  Texto adicional (28-32px)   │
│  em branco com menor peso    │
│  para hierarquia visual.     │
│                              │
│  ┌────────────────────────┐  │
│  │ 📷 [SEU_INSTAGRAM] N/9 │  │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

**Regras dos slides internos:**
- **PREENCHER TODO O ESPACO**: o conteudo (texto + foto) deve ocupar praticamente todo o slide, sem grandes areas vazias. Aumentar o tamanho das fontes e/ou adicionar mais texto se necessario
- **Hierarquia de tamanho**: texto principal 36-42px (grande, impactante), texto secundario 26-30px (complementar, menor)
- **Posicao da foto VARIADA**: alternar entre foto no topo, no meio e na base entre os slides do carrossel — NAO colocar todas as fotos na mesma posicao
- **Fonte**: Raleway (peso 400-700), texto principal 36-42px, texto secundario 26-30px
- **Fundo escuro**: `#292A25` (Cinza 99dev) — solido, sem foto como background
- **Fundo de destaque**: `#B078FF` (Roxo 99dev) ou `#9B5FE0` para slides de impacto (usar em 1-2 slides por carrossel)
- **Foto contextual**: contida no slide (~90% largura), com `border-radius: 8px`, **NAO full-bleed**
- **Palavras destacadas inline**: cor `#B078FF` (roxo) ou `#3CD3A4` (verde) + `font-weight: 700` + `font-style: italic`
- **Texto narrativo**: estilo storytelling, paragrafos de 3-5 linhas, nao headlines curtas
- **Bold para frases-chave**: usar `font-weight: 700` em trechos importantes dentro do paragrafo
- **Line-height**: 1.45-1.55 para boa legibilidade
- **Sem text-transform uppercase** nos slides internos — apenas capitalize natural
- **Indicador de pagina**: dots ou numeracao no rodape

### Header Topo Obrigatorio (todos os slides)
- **Posicao**: fixo no topo do slide, `position: absolute; top: 0; left: 0; right: 0;`
- **Layout**: `display: flex; justify-content: space-between;` com 3 elementos
- **Lado esquerdo**: `Powered by Postlab` em branco com opacidade 0.55, Space Grotesk, peso 400, 14px, uppercase
- **Centro**: `[SEU_INSTAGRAM]` em branco com opacidade 0.55, Space Grotesk, peso 400, 14px, uppercase
- **Lado direito**: Mes e ano no formato `Março 2026 ®` (mes por extenso + ano + simbolo registrado ®), Space Grotesk, peso 400, 14px, uppercase
- **Padding**: `20px 40px`
- **Z-index**: 10 (acima do background e overlay)
- **TODOS os slides** devem ter este header — capa, internos e CTA

### Rodape Obrigatorio (todos os slides)
- **Lado esquerdo**: Icone do Instagram (SVG inline) + `[SEU_INSTAGRAM]` em branco, peso 600
- **Lado direito**: Numero da pagina no formato `N/total` — **SÓ a partir do slide 2**. A capa (slide 1) nao tem numero no rodape. A numeracao conta apenas os slides de conteudo (ex: para 10 slides total, o slide 2 mostra `1/9`, o slide 3 mostra `2/9`, ate `9/9`)
- **Fundo do rodape**: `rgba(0,0,0,0.5)` sutil
- **Padding**: 16px horizontal, 12px vertical
- **Posicao**: fixo no bottom do slide

---

## Estrutura dos Carrosseis

### Slide 1 — Capa (Hook)
- **Foto impactante** de pessoa ou cena como fundo (Unsplash)
- **Logo do Instagram + [SEU_INSTAGRAM] centralizado** no meio da imagem, acima do titulo (estilo branding)
- Titulo em **CAIXA ALTA**, 52-64px, bold, com **1-2 palavras em roxo**
- Formato de **pergunta provocativa** ou **afirmacao chocante**
- Subtitulo em 1-2 linhas explicando a investigacao/tema (22-26px, verde ou branco)
- **SEM numeracao** — a capa nao tem numero de slide
- **Objetivo**: parecer uma manchete de jornal/revista que para o scroll

### Slides 2-9 — Conteudo (Estilo Editorial/Narrativo)
- **1 ideia por slide** — maximo clareza
- **Fundo Cinza 99dev solido** (#292A25) — NAO usar foto como background
- **Foto contextual contida** no slide (~90% largura) — buscar no Unsplash
- **VARIAR posicao da foto**: alternar entre topo, meio e base entre os slides — NAO repetir mesma posicao em todos
- **Texto principal GRANDE** (36-42px) preenchendo o espaco — sem areas vazias
- **Texto secundario menor** (26-30px) complementando o ponto principal
- **Texto narrativo em Raleway** acima e/ou abaixo da foto
- **Palavras-chave em roxo/verde** inline no texto, com bold e italico
- **Frases-chave em bold** dentro dos paragrafos para hierarquia
- Tom de **storytelling investigativo** — contar a historia em paragrafos curtos
- **1-2 slides por carrossel** podem usar **fundo de cor solida** (roxo #B078FF) sem foto, apenas texto branco em Raleway grande para impacto maximo
- Dados e numeros em **destaque inline** (roxo ou verde, bold)

### Slide Final — CTA
- Foto de fundo impactante
- Chamada para acao: "SALVE PARA DEPOIS", "COMPARTILHE COM ALGUEM"
- Destaque no `[SEU_INSTAGRAM]` com cor amarela 99dev
- Frase de fechamento impactante
- Icones de acoes do Instagram (salvar, compartilhar, curtir)

---

## Fluxo de Trabalho

### Passo 1: Pesquisar Tendencias de IA (Apify + Reddit)

Use a API do Apify para acessar o Reddit e encontrar topicos em alta sobre **Inteligencia Artificial**:

```bash
# Buscar posts trending no Reddit sobre IA
curl -X POST "https://api.apify.com/v2/acts/trudax~reddit-scraper/runs?token=[SEU_APIFY_TOKEN]" \
  -H "Content-Type: application/json" \
  -d '{
    "startUrls": [
      {"url": "https://www.reddit.com/r/artificial/top/?t=week"},
      {"url": "https://www.reddit.com/r/ChatGPT/top/?t=week"},
      {"url": "https://www.reddit.com/r/OpenAI/top/?t=week"},
      {"url": "https://www.reddit.com/r/MachineLearning/top/?t=week"},
      {"url": "https://www.reddit.com/r/singularity/top/?t=week"},
      {"url": "https://www.reddit.com/r/ArtificialIntelligence/top/?t=week"},
      {"url": "https://www.reddit.com/r/ClaudeAI/top/?t=week"},
      {"url": "https://www.reddit.com/r/LocalLLaMA/top/?t=week"}
    ],
    "maxItems": 30,
    "sort": "top",
    "time": "week"
  }'
```

Depois, busque os resultados:

```bash
# Verificar status e buscar resultados
curl "https://api.apify.com/v2/acts/trudax~reddit-scraper/runs/last/dataset/items?token=[SEU_APIFY_TOKEN]"
```

**Subreddits de IA recomendados:**
- IA Geral: r/artificial, r/ArtificialIntelligence, r/singularity
- ChatGPT/LLMs: r/ChatGPT, r/OpenAI, r/ClaudeAI, r/LocalLLaMA
- Machine Learning: r/MachineLearning, r/deeplearning, r/MLQuestions
- IA e Negocios: r/AIToolsTech, r/aibusiness
- IA e Arte: r/StableDiffusion, r/midjourney, r/AIArt
- Futuro/Impacto: r/Futurology, r/technology

Analise os posts com mais engajamento e extraia:
- Temas recorrentes sobre IA
- Duvidas frequentes das pessoas sobre IA
- Noticias e lancamentos recentes
- Dados e estatisticas sobre impacto da IA
- Controversias e debates sobre IA

### Passo 2: Buscar Imagens (Unsplash API)

```bash
# Buscar imagens relevantes ao tema
curl -H "Authorization: Client-ID [SUA_UNSPLASH_ACCESS_KEY]" \
  "https://api.unsplash.com/search/photos?query=TEMA_AQUI&per_page=10&orientation=portrait"
```

A resposta retorna um array `results` com objetos de foto. Use o campo `urls.regular` (1080px de largura) para os slides:
- `results[n].urls.regular` — URL da imagem em tamanho ideal para os slides
- `results[n].urls.full` — URL da imagem em resolucao maxima
- `results[n].description` ou `results[n].alt_description` — descricao para alt text

**Regras para imagens:**
- Preferir **fotos de pessoas reais** — rostos, expressoes, situacoes
- Orientacao **portrait** (4:5) obrigatoria
- Fotos devem ter relacao com o tema do slide
- Aplicar overlay escuro `rgba(0,0,0,0.4)` a `rgba(0,0,0,0.6)` para legibilidade do texto
- Aplicar `filter: brightness(0.5)` ou gradiente escuro sobre a foto
- Buscar: pessoas usando tecnologia, rostos expressivos, cenas urbanas, escritorios
- **Cada slide deve ter uma foto diferente**
- **NAO** creditar Unsplash nos slides — sem fonte de fotos visivel

### Passo 3: Gerar o HTML dos Slides

Crie um arquivo HTML para cada carrossel. Cada slide deve ser uma `<div>` de 1080x1350px. Use o seguinte template base:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Carrossel [SEU_INSTAGRAM]</title>
  <link href="https://fonts.googleapis.com/css2?family=Raleway:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;0,900;1,400;1,500;1,600;1,700&family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }

    .slide {
      width: 1080px;
      height: 1350px;
      position: relative;
      overflow: hidden;
      font-family: 'Raleway', sans-serif;
      color: #ffffff;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      padding: 60px 56px 90px;
      page-break-after: always;
    }

    .slide-bg {
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      background-size: cover;
      background-position: center;
      filter: brightness(0.5);
      z-index: 0;
    }

    .slide-overlay {
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      background: linear-gradient(180deg, rgba(0,0,0,0.1) 0%, rgba(0,0,0,0.7) 100%);
      z-index: 1;
    }

    .slide-content {
      position: relative;
      z-index: 2;
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }

    .slide-number {
      position: absolute;
      top: 32px;
      right: 40px;
      font-size: 20px;
      font-weight: 600;
      color: rgba(255,255,255,0.7);
      z-index: 3;
    }

    .title {
      font-size: 56px;
      font-weight: 900;
      line-height: 1.1;
      letter-spacing: -1px;
      text-transform: uppercase;
      text-shadow: 2px 2px 8px rgba(0,0,0,0.8);
    }

    .title .highlight {
      color: #B078FF;
    }

    .title .highlight-green {
      color: #D9D353;
    }

    .subtitle {
      font-size: 24px;
      font-weight: 500;
      color: rgba(255,255,255,0.85);
      line-height: 1.5;
      text-shadow: 1px 1px 4px rgba(0,0,0,0.8);
      max-width: 900px;
    }

    .subtitle-green {
      font-size: 22px;
      font-weight: 600;
      color: #3CD3A4;
      line-height: 1.5;
      text-shadow: 1px 1px 4px rgba(0,0,0,0.8);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .big-number {
      font-size: 80px;
      font-weight: 900;
      color: #B078FF;
      text-shadow: 2px 2px 10px rgba(0,0,0,0.8);
    }

    .tag {
      display: inline-block;
      background: rgba(176,120,255,0.2);
      border: 1px solid rgba(176,120,255,0.5);
      color: #B078FF;
      padding: 8px 20px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 2px;
      align-self: flex-start;
    }

    /* BRANDING CENTRALIZADO — APENAS SLIDE 1 (CAPA) */
    .cover-branding {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
      margin-bottom: 16px;
    }

    .cover-branding svg {
      width: 32px;
      height: 32px;
      fill: #ffffff;
    }

    .cover-branding span {
      font-size: 24px;
      font-weight: 700;
      color: #ffffff;
      text-shadow: 2px 2px 8px rgba(0,0,0,0.8);
    }

    /* HEADER TOPO — TODOS OS SLIDES */
    .top-header {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 22px 40px;
      z-index: 10;
      font-family: 'Space Grotesk', sans-serif;
    }

    .top-header span {
      font-size: 14px;
      font-weight: 400;
      color: rgba(255,255,255,0.55);
      letter-spacing: 0.8px;
      text-transform: uppercase;
    }

    /* RODAPE OBRIGATORIO */
    .footer {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 18px 40px;
      background: rgba(0,0,0,0.5);
      z-index: 10;
    }

    .footer-left {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .footer-left svg {
      width: 22px;
      height: 22px;
      fill: #ffffff;
    }

    .footer-left span {
      font-size: 18px;
      font-weight: 600;
      color: #ffffff;
    }

    .footer-right {
      font-size: 18px;
      font-weight: 500;
      color: rgba(255,255,255,0.6);
    }

    /* ===== SLIDES INTERNOS — ESTILO EDITORIAL/NARRATIVO ===== */

    .slide-editorial {
      width: 1080px;
      height: 1350px;
      position: relative;
      overflow: hidden;
      font-family: 'Raleway', sans-serif;
      color: #ffffff;
      background: #292A25;
      display: flex;
      flex-direction: column;
      justify-content: center;
      padding: 80px 56px 90px;
      page-break-after: always;
    }

    /* Variante com fundo de cor solida (roxo 99dev) */
    .slide-editorial.accent-bg {
      background: #B078FF;
    }

    .slide-editorial .editorial-content {
      display: flex;
      flex-direction: column;
      gap: 28px;
      z-index: 2;
      flex: 1;
      justify-content: center;
    }

    /* Texto principal — GRANDE, impactante */
    .slide-editorial .narrative-text {
      font-family: 'Raleway', sans-serif;
      font-size: 38px;
      font-weight: 400;
      line-height: 1.45;
      color: #ffffff;
    }

    /* Texto secundario — menor, complementar */
    .slide-editorial .narrative-text.secondary {
      font-size: 28px;
      font-weight: 400;
      line-height: 1.5;
    }

    .slide-editorial .narrative-text .highlight {
      color: #B078FF;
      font-weight: 700;
      font-style: italic;
    }

    .slide-editorial .narrative-text .highlight-green {
      color: #3CD3A4;
      font-weight: 700;
      font-style: italic;
    }

    .slide-editorial .narrative-text strong {
      font-weight: 700;
    }

    /* Na variante accent-bg, destaques ficam em branco/amarelo 99dev */
    .slide-editorial.accent-bg .narrative-text .highlight {
      color: #ffffff;
      text-decoration: underline;
      text-decoration-thickness: 3px;
    }

    .slide-editorial.accent-bg .narrative-text .highlight-green {
      color: #D9D353;
      font-weight: 700;
      font-style: italic;
    }

    .slide-editorial .editorial-photo {
      width: 100%;
      height: 380px;
      border-radius: 8px;
      object-fit: cover;
    }

    .slide-editorial .editorial-photo-container {
      width: 100%;
      border-radius: 8px;
      overflow: hidden;
    }

    .slide-editorial .editorial-photo-container img {
      width: 100%;
      height: 380px;
      object-fit: cover;
      display: block;
    }

    /* Dots de navegacao (opcional) */
    .page-dots {
      display: flex;
      justify-content: center;
      gap: 8px;
      margin-top: 16px;
    }

    .page-dots .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: rgba(255,255,255,0.3);
    }

    .page-dots .dot.active {
      background: #ffffff;
    }
  </style>
</head>
<body>

  <!-- SLIDE 1 — CAPA (sem numeracao, com branding centralizado) -->
  <div class="slide">
    <div class="slide-bg" style="background-image: url('URL_PEXELS_AQUI')"></div>
    <div class="slide-overlay"></div>
    <!-- SEM slide-number na capa -->
    <div class="top-header">
      <span>Powered by Postlab</span>
      <span>[SEU_INSTAGRAM]</span>
      <span>Março 2026 ®</span>
    </div>
    <div class="slide-content">
      <div class="cover-branding">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/>
        </svg>
        <span>[SEU_INSTAGRAM]</span>
      </div>
      <h1 class="title">
        POR QUE A <span class="highlight">IA</span> ESTA MUDANDO TUDO E NINGUEM TE CONTA?
      </h1>
      <p class="subtitle">Investigamos o impacto real da inteligencia artificial no mercado de trabalho e na vida das pessoas</p>
    </div>
    <div class="footer">
      <div class="footer-left">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/>
        </svg>
        <span>[SEU_INSTAGRAM]</span>
      </div>
      <!-- SEM numero de pagina na capa -->
    </div>
  </div>

  <!-- VARIANTE A — FOTO NO MEIO (texto grande acima, texto menor abaixo) -->
  <div class="slide-editorial">
    <div class="top-header">
      <span>Powered by Postlab</span>
      <span>[SEU_INSTAGRAM]</span>
      <span>Março 2026 ®</span>
    </div>
    <div class="editorial-content">
      <p class="narrative-text" style="font-size: 38px;">
        Texto narrativo GRANDE contando a historia. Aqui voce desenvolve o ponto com <span class="highlight">palavras destacadas em roxo</span> inline. Preencha bem o espaco acima da foto.
      </p>
      <div class="editorial-photo-container">
        <img src="URL_UNSPLASH_AQUI" alt="Foto contextual">
      </div>
      <p class="narrative-text secondary">
        Texto menor complementando. <strong>Frases importantes em bold.</strong> Dados como <span class="highlight-green">40% de crescimento</span> em destaque verde.
      </p>
    </div>
    <div class="footer">
      <div class="footer-left">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/>
        </svg>
        <span>[SEU_INSTAGRAM]</span>
      </div>
      <div class="footer-right">1/9</div>
    </div>
  </div>

  <!-- SLIDE EDITORIAL — VARIANTE COR SOLIDA (para slides de impacto maximo) -->
  <div class="slide-editorial accent-bg">
    <div class="top-header">
      <span>Powered by Postlab</span>
      <span>[SEU_INSTAGRAM]</span>
      <span>Março 2026 ®</span>
    </div>
    <div class="editorial-content">
      <p class="narrative-text" style="font-size: 36px; font-weight: 500; line-height: 1.45;">
        A escala do clube criou um ativo que nenhum concorrente consegue replicar rapidamente: poder de barganha global, base de dados sobre o gosto do consumidor e <span class="highlight-orange">uma relacao de confianca mensal com centenas de milhares de assinantes.</span>
      </p>
      <p class="narrative-text" style="font-size: 28px; font-weight: 400; line-height: 1.5;">
        Texto complementar com mais detalhes, explicando o contexto e adicionando profundidade ao argumento principal do slide.
      </p>
    </div>
    <div class="footer">
      <div class="footer-left">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/>
        </svg>
        <span>[SEU_INSTAGRAM]</span>
      </div>
      <div class="footer-right">5/9</div>
    </div>
  </div>

  <!-- SLIDE FINAL — CTA -->
  <div class="slide">
    <div class="slide-bg" style="background-image: url('URL_PEXELS_AQUI')"></div>
    <div class="slide-overlay"></div>
    <div class="top-header">
      <span>Powered by Postlab</span>
      <span>[SEU_INSTAGRAM]</span>
      <span>Março 2026 ®</span>
    </div>
    <span class="slide-number">9/9</span>
    <div class="slide-content">
      <h1 class="title" style="font-size: 48px;">
        GOSTOU? <span class="highlight">SALVE</span> ESTE POST!
      </h1>
      <p class="subtitle">Compartilhe com alguem que precisa entender o impacto da IA</p>
      <div style="display: flex; gap: 24px; margin-top: 20px;">
        <div style="display:flex;flex-direction:column;align-items:center;gap:8px;">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#B078FF" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
          <span style="font-size:16px;color:#B078FF;font-weight:600;">SALVAR</span>

        </div>
        <div style="display:flex;flex-direction:column;align-items:center;gap:8px;">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          <span style="font-size:16px;color:#ffffff;font-weight:600;">ENVIAR</span>
        </div>
        <div style="display:flex;flex-direction:column;align-items:center;gap:8px;">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#D9D353" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
          <span style="font-size:16px;color:#D9D353;font-weight:600;">CURTIR</span>
        </div>
      </div>
      <div style="margin-top: 40px; padding: 24px 48px; background: rgba(176,120,255,0.2); border: 1px solid rgba(176,120,255,0.5); border-radius: 8px;">
        <span style="font-size: 24px; font-weight: 700; color: #D9D353;">SIGA [SEU_INSTAGRAM]</span>
      </div>
    </div>
    <div class="footer">
      <div class="footer-left">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/>
        </svg>
        <span>[SEU_INSTAGRAM]</span>
      </div>
      <div class="footer-right">9/9</div>
    </div>
  </div>

</body>
</html>
```

### Passo 4: Capturar Screenshots com Playwright MCP

Use o MCP do Playwright para abrir o HTML no navegador e capturar cada slide como imagem PNG em 1080x1350.

**IMPORTANTE — Compensar DPR (Device Pixel Ratio):**
O Playwright MCP neste ambiente tem DPR 0.75, resultando em viewport CSS de 1440x1800 quando configurado para 1080x1350. Os slides (1080px CSS) nao preenchem o viewport (1440px CSS), gerando bordas na direita e embaixo. A solucao e:

1. **Configurar viewport** para 1080x1350 (`browser_resize`)
2. **Verificar o DPR real** apos navegar: `window.devicePixelRatio` e `window.innerWidth`
3. **Calcular scale**: `cssViewportWidth / 1080` (ex: 1440/1080 = 1.333)
4. **Aplicar `transform: scale(factor)` + `transform-origin: top left`** em cada slide
5. **Usar `clip: {0, 0, cssViewportWidth, cssViewportHeight}`** no screenshot (ex: 1440x1800)
6. A imagem resultante sera `cssWidth * DPR x cssHeight * DPR` = 1080x1350 pixels

**Fluxo completo com Playwright MCP (browser_run_code):**
```javascript
async (page) => {
  await page.goto('http://localhost:PORT/output/NOME/carrossel.html');
  await page.waitForTimeout(3000);

  // 1. Detectar DPR e viewport CSS real
  const dpr = await page.evaluate(() => window.devicePixelRatio);
  const cssW = await page.evaluate(() => window.innerWidth);
  const cssH = await page.evaluate(() => window.innerHeight);
  const scale = cssW / 1080; // ex: 1440/1080 = 1.333

  const slides = await page.locator('body > div').all();
  const total = slides.length;

  // 2. Esconder todos os slides
  for (let i = 0; i < total; i++)
    await slides[i].evaluate(el => el.style.display = 'none');

  // 3. Capturar cada slide individualmente
  for (let i = 0; i < total; i++) {
    const num = String(i + 1).padStart(2, '0');
    const path = `/caminho/output/NOME/slide_${num}.png`;

    // 4. Detectar tipo do slide para cor de fundo
    const classes = await slides[i].evaluate(el => el.className);
    const isAccent = classes.includes('accent-bg');
    const isCredits = await slides[i].evaluate(el =>
      window.getComputedStyle(el).backgroundColor === 'rgb(255, 255, 255)');
    const bgColor = isAccent ? '#B078FF' : isCredits ? '#ffffff' : '#292A25';

    // 5. Setar background do html+body para a mesma cor do slide
    await page.evaluate(c => {
      document.documentElement.style.background = c;
      document.body.style.background = c;
    }, bgColor);

    // 6. Posicionar slide fixed + scale para preencher viewport CSS
    await slides[i].evaluate((el, s) => {
      el.style.display = 'flex';
      el.style.position = 'fixed';
      el.style.top = '0';
      el.style.left = '0';
      el.style.width = '1080px';
      el.style.height = '1350px';
      el.style.zIndex = '9999';
      el.style.transform = `scale(${s})`;
      el.style.transformOrigin = 'top left';
    }, scale);

    await page.waitForTimeout(300);

    // 7. Screenshot com clip no tamanho do viewport CSS
    await page.screenshot({
      path,
      clip: { x: 0, y: 0, width: cssW, height: cssH }
    });

    // 8. Resetar slide
    await slides[i].evaluate(el => {
      el.style.display = 'none';
      el.style.position = '';
      el.style.top = '';
      el.style.left = '';
      el.style.width = '';
      el.style.height = '';
      el.style.zIndex = '';
      el.style.transform = '';
      el.style.transformOrigin = '';
    });
  }

  // 9. Restaurar
  await page.evaluate(() => {
    document.documentElement.style.background = '';
    document.body.style.background = '';
  });
  for (let i = 0; i < total; i++)
    await slides[i].evaluate(el => el.style.display = '');
}
```

**Regras criticas:**
- **SEMPRE** verificar o DPR apos navegar (ele pode mudar entre paginas)
- **SEMPRE** usar `transform: scale()` para compensar a diferenca entre slide (1080px) e viewport CSS
- **SEMPRE** setar `html+body background` para a cor do slide antes de capturar
- **NUNCA** usar `element.screenshot()` — usar `page.screenshot({ clip })` com o viewport CSS completo
- Servir o HTML via HTTP server local (`python3 -m http.server PORT`) — URLs `file://` sao bloqueadas

### Passo 5: Gerar arquivo de legenda

Crie um arquivo `legenda.txt` na pasta do carrossel com a caption e hashtags:

```
[LEGENDA]
Texto da legenda aqui...

[HASHTAGS]
#ia #inteligenciaartificial #chatgpt #tecnologia #futuro #99hud
```

---

## Regras de Conteudo

### Tema Obrigatorio: Inteligencia Artificial
Todos os carrosseis devem abordar temas relacionados a IA:
- Impacto da IA no mercado de trabalho
- Novas ferramentas de IA e como usa-las
- O futuro com IA — previsoes e tendencias
- IA vs humanos — debates e controversias
- Como a IA esta mudando industrias especificas
- Dicas praticas de uso de IA no dia a dia
- Noticias e lancamentos de IA da semana
- O lado oculto/polemico da IA

### Tom de Voz
- **Investigativo e provocativo** — como manchete de jornal
- **Direto e impactante** — frases curtas e fortes
- **Questionador** — "POR QUE...", "O QUE NINGUEM TE CONTA SOBRE...", "O LADO OCULTO DE..."
- **Dados concretos** — use numeros e estatisticas sempre que possivel
- Pode usar **ingles** em termos tecnicos (AI, machine learning, prompt, LLM)

### Estrutura de Copy
1. **Hook** (Slide 1): Pergunta provocativa tipo manchete investigativa com palavra-chave em vermelho
2. **Desenvolvimento** (Slides 2-9): Uma ideia por slide, progressao logica, cada slide com foto diferente
3. **CTA** (Slide final): Acao clara — salvar, compartilhar, seguir

### Boas Praticas
- Maximo **10 slides** por carrossel (ideal: 7-10)
- Minimo **5 slides** por carrossel
- **Nao use mais de 30 palavras por slide** nos slides de conteudo
- Texto em **CAIXA ALTA** nos titulos — obrigatorio
- **1-2 palavras em roxo** por slide para destaque
- Cada slide deve ter uma **foto de fundo diferente**
- Fotos de **pessoas reais** sempre que possivel
- Tom de **investigacao jornalistica**

---

## Organizacao de Arquivos

```
carrosseis/
├── CLAUDE.md                          # Este arquivo
└── output/                            # Carrosseis gerados
    └── nome-do-carrossel/             # Pasta com nome da postagem
        ├── carrossel.html             # HTML source
        ├── slide_01.png               # Imagens individuais
        ├── slide_02.png
        ├── ...
        ├── slide_10.png
        └── legenda.txt                # Legenda + hashtags
```

### legenda.txt
```
[LEGENDA]
Caption sugerida para o post do Instagram.
Texto provocativo que complementa o carrossel e gera engajamento.
Use quebras de linha para facilitar a leitura.

Siga [SEU_INSTAGRAM] para mais conteudo sobre IA.

[HASHTAGS]
#ia #inteligenciaartificial #chatgpt #openai #tecnologia #futuro #inovacao #machinelearning #artificialintelligence #99hud
```

---

## Comando Rapido

Quando o usuario pedir para criar um carrossel, siga este fluxo:

1. **Pesquise tendencias de IA** no Reddit usando Apify API
2. **Escolha o tema** mais relevante/viral encontrado
3. **Crie o roteiro** com titulos investigativos e textos para cada slide
4. **Busque fotos de pessoas/cenas** no Unsplash API (1 foto por slide)
5. **Gere o HTML** completo do carrossel no estilo editorial
6. **Use o Playwright MCP** para capturar os slides como PNG
7. **Crie o legenda.txt** com caption e hashtags
8. **Salve tudo** na pasta `output/nome-do-carrossel/`

---

## APIs e Credenciais

### Unsplash API
- **Endpoint**: `https://api.unsplash.com/search/photos`
- **Header**: `Authorization: Client-ID [SUA_UNSPLASH_ACCESS_KEY]`
- **Application ID**: `904033`
- **Access Key**: `[SUA_UNSPLASH_ACCESS_KEY]`
- **Secret Key**: `[SUA_UNSPLASH_SECRET_KEY]`
- **Redirect URI**: `urn:ietf:wg:oauth:2.0:oob`
- **Docs**: https://unsplash.com/documentation
- **Campo de URL para slides**: `results[n].urls.regular` (1080px)

### Apify (Reddit Scraper)
- **Token**: `[SEU_APIFY_TOKEN]`
- **Actor**: `trudax~reddit-scraper`
- **Endpoint base**: `https://api.apify.com/v2/acts/trudax~reddit-scraper/runs`

### Playwright MCP
- Usar para renderizar HTML e capturar screenshots dos slides
- Viewport: 1080x1350 (formato Instagram 4:5)
