# Ponto de situação — Campanha experimental `doe_campaign_01`

**Documento preparado para reunião de orientação — 2026-07-06**

**Nota de leitura:** este documento evita, tanto quanto possível, nomes e símbolos internos do código. Onde um termo técnico é inevitável, é explicado na primeira vez que aparece. Todos os valores de imposto de carbono são apresentados diretamente em **USD por tonelada de CO2 equivalente (USD/tCO2e)** — a variável interna do modelo (adimensional) foi convertida para esta unidade (1 unidade interna = USD 10/tCO2e).

---

## 1. Contexto e objetivo deste documento

O modelo em estudo representa uma **cadeia de abastecimento de ciclo fechado (Closed-Loop Supply Chain, CLSC)** — uma cadeia que, além de produzir e distribuir produtos novos, também recolhe produtos em fim de vida e os reintroduz no sistema (remanufactura). O modelo é **bilevel**, ou seja, tem duas camadas de decisão aninhadas:

- **Camada superior (o "regulador"):** escolhe um **imposto de carbono** (um valor em USD por tonelada de CO2 equivalente emitida) com o objetivo de minimizar as emissões totais da cadeia de abastecimento.
- **Camada inferior (a "indústria"):** ao observar esse imposto, decide como organizar a cadeia — que instalações abrir, que tecnologias de produção/remanufactura usar, que modos de transporte escolher — para minimizar o seu próprio custo total, tendo o imposto de carbono em conta.

A decisão da indústria é, ela própria, um problema de otimização com muitas variáveis (algumas contínuas — quantidades a produzir/transportar — outras binárias — abrir ou não uma instalação, usar ou não uma tecnologia). Resolver *só* a camada da indústria já pode demorar minutos a horas; resolver o problema completo (regulador + indústria, iterativamente, até convergirem) é ainda mais caro. Por isso, toda a campanha experimental foi desenhada para obter o máximo de informação científica com o mínimo de resoluções completas.

Este documento resume o **estado de execução e os primeiros resultados** da campanha `doe_campaign_01`, para apoiar a discussão de work-in-progress com os orientadores. O desenho experimental completo está em `results/runs/doe_campaign_01/EXPERIMENTAL_PLAN.md`.

---

## 2. Resumo executivo

- **219 das 249 resoluções planeadas já estão concluídas** (88%). As 6 experiências principais estão 100% completas; falta apenas uma experiência (a "E", secção 3 e 5.7), que está **corretamente em pausa** à espera do resultado de outra.
- **Nenhuma resolução falhou ou ficou sem solução viável.** 17 das 219 (7.8%) não conseguiram fechar o gap de otimalidade dentro do tempo/orçamento definido (chamamos a isto "censura" — não é um erro, é um limite computacional conhecido, explicado na secção 4). Isto aconteceu apenas nas instâncias com o catálogo de materiais/produtos mais amplo (as instâncias "M8" — ver legenda na secção 3).
- **Achado principal (experiência de rastreio de fatores):** a **procura de mercado**, as **emissões incorporadas nas matérias-primas** e a **intensidade de emissões da produção/remanufactura** são os três fatores com maior impacto nas emissões totais (efeitos de +43% a +59% acima da média); a **capacidade das linhas de produção/remanufactura** é o fator com maior impacto no custo (−35%).
- **Achado principal (experiência de interações entre alavancas de política):** o efeito combinado mais forte não é o que estava previsto no plano original (menu tecnológico × disponibilidade de retornos), mas sim **menu tecnológico × procura de mercado**: alargar o leque de tecnologias disponíveis reduz as emissões muito mais quando a procura é alta do que quando é baixa.
- **Achado principal (experiência da fronteira custo-emissões):** em 2 das 3 instâncias sondadas, o custo e as emissões da indústria ficam **praticamente idênticos para qualquer imposto de carbono entre USD 20/t e USD 200/t** — só o salto inicial de USD 0/t para USD 20/t muda alguma coisa. Isto confirma, com dados novos desta campanha, um problema já identificado antes: o modelo não consegue apontar um único "preço de carbono ótimo" nestes casos — muitos preços diferentes produzem exatamente o mesmo resultado para a indústria.
- **Duas questões precisam de decisão dos orientadores** (detalhe na secção 6): (i) 2 dos 9 casos-base pararam sem fechar o gap-alvo de 1%, mesmo sem esgotar o tempo disponível — algo na forma como o algoritmo bilevel converge parece estar a bloquear antes do tempo; (ii) o imposto de carbono "ótimo" reportado pode mudar drasticamente (ex. de USD 150/t para USD 60/t) só por afinar a precisão exigida ao motor de otimização, mesmo que o custo/emissões praticamente não mudem.

---

## 3. Desenho experimental (o que foi testado e porquê)

### 3.1 Instâncias-base: 9 "tamanhos" de problema diferentes

Foram definidas 9 versões do problema, de complexidade crescente, combinando três dimensões:

- **Tamanho da rede física** ("I17" ou "I25"): número total de instalações no problema (fornecedores + fábricas + armazéns + retalhistas + aeroportos + portos marítimos). I17 = rede mais pequena (17 instalações); I25 = rede maior (25 instalações, com mais armazéns e mais aeroportos).
- **Amplitude do catálogo de materiais e produtos** ("M4" ou "M8"): quantos tipos de matéria-prima e produto acabado existem no problema. M4 = catálogo simples (2 matérias-primas + 1 produto); M8 = catálogo mais rico (4 matérias-primas + 2 produtos) — mais combinações possíveis de produzir e transportar.
- **Horizonte temporal** ("T3", "T6" ou "T12"): quantos períodos de planeamento o modelo cobre (3, 6 ou 12).

| Instância | Rede | Catálogo | Períodos | Papel na campanha |
|---|---|---|---|---|
| I17_M4_T3 | pequena | simples | 3 | instância rápida de referência |
| I17_M4_T6 | pequena | simples | 6 | |
| I17_M4_T12 | pequena | simples | 12 | sonda de tratabilidade apenas |
| I17_M8_T3 | pequena | rico | 3 | |
| I17_M8_T6 | pequena | rico | 6 | |
| I25_M4_T3 | grande | simples | 3 | |
| I25_M4_T6 | grande | simples | 6 | |
| I25_M8_T3 | grande | rico | 3 | instância confirmatória |
| I25_M8_T6 | grande | rico | 6 | instância grande de referência |

### 3.2 Os 7 fatores testados (o que cada um representa na cadeia de abastecimento)

Estes fatores foram variados, um de cada vez ou em combinação, à volta do valor "normal" (baseline) de cada instância, para perceber o que mais influencia o custo e as emissões:

| Fator | O que representa | Intervalo testado |
|---|---|---|
| **Procura de mercado** | Quanto produto acabado os clientes pedem, em cada período | 70% a 130% do valor normal |
| **Disponibilidade de retornos** | Quanto produto em fim de vida está realisticamente disponível para ser recolhido e reintroduzido no ciclo de remanufactura | 50% a 150% do valor normal |
| **Intensidade de emissões da produção/remanufactura** | Quão "suja" ou "limpa" é cada unidade produzida ou remanufacturada (emissões por unidade do próprio processo fabril) | 50% a 150% do valor normal |
| **Emissões incorporadas nas matérias-primas** (também chamadas emissões "scope 3" ou a montante) | A pegada de carbono já embutida nas matérias-primas compradas, antes de sequer chegarem à fábrica | 50% a 150% do valor normal |
| **Capacidade das linhas** | O limite máximo de produção/remanufactura que cada linha pode processar por período | 70% a 130% do valor normal |
| **Menu tecnológico** | Se a indústria só tem acesso às tecnologias de produção/remanufactura "de base", ou a um leque alargado que inclui alternativas mais recentes e tipicamente mais limpas | "base" vs. "alargado" |
| **Menu de transporte** | Se a indústria só tem acesso aos modos de transporte "de base" (ex. camião), ou a um leque alargado que inclui alternativas de menor emissão (ex. comboio, marítimo) | "base" vs. "alargado" |

Duas experiências (secção 3.3, famílias F e G) usam ainda dois **parâmetros de configuração do motor de otimização** (não são decisões de negócio, são afinações técnicas de como o software procura a solução):

| Parâmetro técnico | O que controla |
|---|---|
| **Nº de processadores em paralelo (threads)** | Quantos núcleos do computador trabalham em simultâneo a resolver o mesmo problema |
| **Estratégia de procura do solver (MIPFocus)** | Se o motor de otimização prioriza encontrar rapidamente *uma* solução boa ("viabilidade primeiro"), prioriza *provar* que já tem a melhor solução possível ("otimalidade primeiro"), ou usa uma estratégia equilibrada (o default) |
| **Gap de otimalidade** | Quão perto da solução matematicamente ótima o motor tem de chegar antes de parar e declarar "resolvido" (quanto menor o gap exigido, mais tempo pode demorar, mas mais garantida é a qualidade da resposta) |

### 3.3 As 7 experiências (famílias A–G)

| # | Nome informal | O que faz, em termos simples |
|---|---|---|
| **A** | Referência (baseline) | Resolve o problema completo (regulador + indústria) exatamente uma vez em cada uma das 9 instâncias-base, sem alterar nenhum fator. Serve de ponto de comparação para todas as outras experiências. |
| **B** | Fronteira custo-emissões | Em vez de deixar o regulador escolher o imposto, fixa-se manualmente 11 valores de imposto diferentes (de USD 0/t a USD 200/t, em saltos de USD 20/t) e resolve-se só a decisão da indústria em cada um, para 3 das 9 instâncias. Isto traça o "mapa" completo de como o custo e as emissões da indústria respondem a um imposto de carbono cada vez mais alto. |
| **C** | Rastreio de fatores (screening) | Testa os 7 fatores da secção 3.2 em simultâneo, cada um em nível "baixo" ou "alto", usando um desenho eficiente (16 combinações escolhidas cuidadosamente, em vez das 128 que testar tudo exaustivamente exigiria) para descobrir rapidamente quais têm mais impacto. Repetida com 3 desenhos de rede aleatórios adicionais (para confirmar que não é coincidência de um único desenho) e também testada numa instância maior (para confirmar que a conclusão não depende do tamanho do problema). |
| **D** | Interações entre alavancas de política | Foca-se só nos 4 fatores que são decisões de política/design reais (menu tecnológico, menu de transporte, disponibilidade de retornos, procura) e testa **todas** as 16 combinações possíveis, para detetar não só o efeito de cada fator isolado mas como se combinam (ex.: será que um menu tecnológico mais amplo só ajuda a reduzir emissões quando há muitos retornos disponíveis?). |
| **E** | Curvas de resposta detalhadas | Para os 2–3 fatores que a experiência C identificar como mais importantes, testa 9 valores intermédios diferentes (não só baixo/alto) para perceber a **forma** da resposta — linear, curva, com um ponto de viragem? **Ainda não foi executada** — precisa primeiro do resultado da experiência C. |
| **F** | Robustez | Verifica se as conclusões dependem de coincidências: (i) resolve a mesma instância com 3 desenhos de rede aleatórios diferentes, para ver se os números mudam muito consoante o "sorteio" aleatório do gerador; (ii) resolve a mesma instância com o motor de otimização configurado para ser mais rigoroso ou mais permissivo sobre o gap de otimalidade, para ver se isso muda a resposta. |
| **G** | Desempenho computacional | Não testa nada sobre a cadeia de abastecimento em si — testa como configurar o motor de otimização (nº de processadores, estratégia de procura) para resolver a instância mais difícil o mais depressa possível. |

Gap-alvo de otimalidade em toda a campanha: **1%**, alinhada com o critério usado por Tautenhain et al. (2021) na literatura de referência.

---

## 4. Estado de execução da campanha

| Experiência | Planeado | Concluído | Convergiu | Não fechou o gap ("censurado") | Nota |
|---|---|---|---|---|---|
| A — Referência | 9 | 9 | 9 | 0 | 2 casos pararam sem fechar o gap-alvo (ver §5.1) |
| B — Fronteira | 33 | 33 | 33 | 0 | Todas terminaram de forma limpa ("ótimo" confirmado) |
| C — Rastreio de fatores | 72 | 72 | 64 | 8 | Censuras concentradas em combinações de fatores de emissão/custo elevados no catálogo mais rico (M8) |
| D — Interações | 80 | 80 | 73 | 7 | 3 censuras na instância pequena, 4 na instância grande |
| E — Curvas detalhadas | ~30 | 0 | — | — | Em pausa — falta o ranking de fatores da experiência C |
| F — Robustez | 20 | 20 | 20 | 0 | Sem censuras |
| G — Desempenho | 5 | 5 | 3 | 2 | Ambas as censuras com apenas 1 processador ativo |
| **Total** | **249** | **219** | **202** | **17** | 0 casos sem solução viável em toda a campanha |

Dois problemas técnicos no software que gere a campanha foram corrigidos recentemente: (i) um erro na geração aleatória das instâncias de catálogo rico (M8) que causava ~50% de casos sem solução viável — já corrigido; (ii) um erro que impedia retomar a campanha depois de uma interrupção (o software tentava reescrever um ficheiro já existente e falhava) — corrigido e testado. Os limites de tempo por resolução em várias experiências foram também aumentados recentemente, depois de se notar que algumas classes de instância estavam a demorar 2–3× mais do que numa campanha-piloto anterior.

---

## 5. Resultados preliminares por experiência

### 5.1 A — Referência por classe de instância

| Instância | Custo (USD) | Emissões (tCO2e) | Imposto de carbono ótimo (USD/tCO2e) | Tempo de resolução (s) | Gap final | Terminou por |
|---|---|---|---|---|---|---|
| I17_M4_T3 | 1 598 025 | 32 727 | 40 | 13.2 | 0.03% | gap-alvo atingido |
| I17_M4_T6 | 1 675 409 | 90 350 | 20 | 42.4 | 0.14% | gap-alvo atingido |
| I17_M4_T12 | 1 727 835 | 41 964 | 10 | 603.6 | **4.7%** | **estagnação** |
| I17_M8_T3 | 1 228 035 | 135 198 | 50 | 18.3 | ~0% | gap-alvo atingido |
| I17_M8_T6 | 2 000 511 | 161 710 | 100 | 151.1 | 0.12% | gap-alvo atingido |
| I25_M4_T3 | 969 846 | 12 730 | 10 | 8.1 | ~0% | gap-alvo atingido |
| I25_M4_T6 | 1 362 097 | 48 023 | 10 | 63.9 | 0.02% | gap-alvo atingido |
| I25_M8_T3 | 1 832 181 | 152 966 | 70 | 634.2 | **7.0%** | **estagnação** |
| I25_M8_T6 | 2 161 759 | 210 398 | 20 | 1955.5 | 0.19% | gap-alvo atingido |

**"Estagnação"** significa que o algoritmo que resolve o problema bilevel (que alterna entre a proposta de imposto do regulador e a resposta da indústria) parou de melhorar antes de conseguir fechar o gap de 1% pedido — e não porque esgotou o tempo disponível: em ambos os casos, parou em poucos minutos, muito antes do limite de horas disponível. Isto sugere que o problema não é falta de tempo de computação, mas sim algo na forma como o algoritmo converge — vale a pena investigar antes de reportar estes dois casos apenas como "difíceis de resolver".

### 5.2 B — Fronteira custo-emissões (resposta a diferentes impostos de carbono)

Testou-se a resposta da indústria (sem o regulador otimizar) a uma grelha de 11 valores de imposto de carbono, de USD 0/t a USD 200/t, em 3 das 9 instâncias:

| Instância | USD 0/t (custo / emissões) | USD 20/t (custo / emissões) | USD 200/t (custo / emissões) | Forma da resposta |
|---|---|---|---|---|
| I17_M4_T3 | 1 494 533 / 77 783 | 1 598 025 / 32 727 | 1 598 025 / 32 727 | **degrau único**: tudo muda entre 0 e 20, depois fica igual até 200 |
| I25_M4_T6 | 1 304 699 / 64 548 | 1 362 097 / 48 023 | 1 362 314 / 48 022 | **degrau único**: mesmo padrão |
| I25_M8_T6 | 1 936 362 / 312 544 | 2 114 341 / 210 505 | 2 201 527 / 209 937 | **gradual**: as emissões continuam a descer até cerca de USD 100–120/t, depois ficam quase estáveis |

Nas duas instâncias com catálogo simples (M4), o custo e as emissões da indústria são **praticamente idênticos para qualquer imposto entre USD 20/t e USD 200/t** — ou seja, do ponto de vista da indústria, um imposto de USD 30/t e um de USD 190/t dão exatamente o mesmo resultado. Só a instância maior e mais rica (I25_M8_T6) mostra uma resposta genuinamente gradual, com um imposto mais alto a produzir mais melhoria (até certo ponto). Isto é evidência direta, dentro desta campanha, de que o modelo, tal como está, **não consegue distinguir entre diferentes impostos de carbono** nas instâncias mais simples — qualquer um dentro de um intervalo largo é igualmente "ótimo".

### 5.3 C — Rastreio de fatores (que fatores importam mais)

Efeito médio de cada fator sobre o custo e as emissões (instância rápida, com 4 desenhos de rede aleatórios diferentes, efeito de cada fator expresso como % de desvio face à média):

| Fator | Efeito nas emissões | Efeito no custo |
|---|---|---|
| **Procura de mercado** | **+59.0%** | +44.5% |
| **Emissões incorporadas nas matérias-primas** | **+47.0%** | +12.4% |
| **Intensidade de emissões da produção/remanufactura** | **+42.9%** | −1.7% |
| Menu tecnológico alargado | −26.2% | −13.1% |
| Capacidade das linhas | −5.1% | **−35.1%** |
| Menu de transporte alargado | +2.3% | −3.9% |
| Disponibilidade de retornos | +1.0% | +0.8% |

A instância confirmatória, maior (I25_M8_T3, com 4 dos 8 pontos testados sem fechar o gap-alvo), reproduz a mesma hierarquia: procura de mercado e emissões das matérias-primas continuam a dominar o efeito nas emissões; o menu tecnológico alargado continua a reduzi-las; a capacidade continua a ser o principal fator de custo. **A ordenação dos fatores parece ser robusta ao tamanho do problema**, embora a confiança nos valores absolutos da instância confirmatória seja limitada pela elevada proporção de casos sem gap fechado (4 de 8).

*Nota metodológica: este ranking foi calculado propositadamente para esta reunião; a ferramenta de análise permanente para este cálculo ainda não foi escrita (secção 8).*

### 5.4 D — Interações entre alavancas de política

Efeito de cada fator isolado, e da combinação mais relevante, na instância pequena e na instância grande:

| Efeito | Instância pequena (emissões) | Instância grande (emissões) |
|---|---|---|
| Menu tecnológico alargado (isolado) | −30.7% | −36.6% |
| Procura de mercado (isolado) | +59.3% | +43.2% |
| Disponibilidade de retornos (isolado) | −0.2% | +4.1% |
| Menu de transporte alargado (isolado) | ~0% | +4.4% |
| **Menu tecnológico × procura de mercado (combinação)** | **−9.2%** | **−27.8%** |
| Menu tecnológico × disponibilidade de retornos (combinação) | +0.1% | +4.3% |
| Menu de transporte × procura de mercado (combinação) | ~0% | −4.3% |

O plano experimental original previa que as combinações mais interessantes seriam "menu tecnológico × disponibilidade de retornos" e "menu de transporte × procura de mercado". **Os dados mostram outra coisa:** a combinação com efeito real é **menu tecnológico × procura de mercado** — alargar o leque de tecnologias reduz as emissões muito mais quando a procura de mercado é alta do que quando é baixa, e este efeito cresce com o tamanho do problema (de −9.2% para −27.8%). Vale a pena discutir se a narrativa do artigo deve seguir este achado em vez das duas combinações originalmente previstas.

### 5.5 F — Robustez

- **Sensibilidade ao desenho aleatório da rede** (3 desenhos adicionais por classe, mesma precisão): o custo varia entre 19% e 38% e as emissões entre 19% e 49% (medido como coeficiente de variação) consoante a classe de instância. Isto confirma que os **valores absolutos** são sensíveis ao "sorteio" aleatório usado para gerar a rede (uma propriedade conhecida do gerador de instâncias, não um defeito) — mas os **efeitos dos fatores** (secções 5.3 e 5.4, que comparam sempre dentro do mesmo sorteio) não são afetados por isto.
- **Sensibilidade à precisão exigida ao motor de otimização** (comparação entre exigir um gap 10× mais apertado e um gap 10× mais permissivo, mesmo desenho de rede): o custo e as emissões variam **menos de 1%** em 3 das 4 classes testadas (exceção: a instância confirmatória grande, +10.6% no custo). Mas o **imposto de carbono "ótimo" reportado muda bastante** entre a versão apertada e a permissiva (ex.: de USD 30/t para USD 0/t; de USD 150/t para USD 60/t) — outro sintoma do mesmo problema da secção 5.2: o *resultado* para a indústria é estável, mas o *preço* que o produz não é.

### 5.6 G — Configuração do motor de otimização (na instância mais difícil)

| Processadores em paralelo | Estratégia de procura | Tempo de resolução (s) | Resultado |
|---|---|---|---|
| 1 | equilibrada (default) | 11 072 | **não fechou o gap** (esgotou o tempo) |
| 1 | viabilidade primeiro | 1 165 | fechou o gap |
| 1 | otimalidade primeiro | 11 117 | **não fechou o gap** (esgotou o tempo) |
| 6 (default da campanha) | equilibrada (default) | 1 955 | fechou o gap |
| 6 | viabilidade primeiro | **465** | fechou o gap |
| 6 | otimalidade primeiro | 1 414 | fechou o gap |

A estratégia "viabilidade primeiro" é decisiva: com apenas 1 processador, é a única configuração que consegue fechar o gap-alvo (as outras duas ficam presas até ao limite de tempo); com 6 processadores, reduz o tempo em cerca de 4× face à configuração usada até agora nesta campanha (1 955s → 465s). Vale a pena considerar adotar "viabilidade primeiro" como configuração revista para as experiências mais pesadas computacionalmente (D, E e G na instância grande), o que poderia libertar tempo de computação para a experiência E.

### 5.7 E — Estado

Não iniciada — corretamente em pausa. A lista de fatores a testar em detalhe ainda é provisória; precisa de ser substituída pelo ranking real de fatores da experiência C (secção 5.3) antes de correr as ~30 resoluções previstas.

---

## 6. Questões metodológicas em aberto (para discussão)

1. **Dois casos-base (I17_M4_T12 e I25_M8_T3) não fecharam o gap-alvo de 1%** (ficaram em 4.7% e 7.0%), apesar de terem parado muito antes do limite de tempo disponível — não é falta de tempo, é o algoritmo a "estagnar". Devem ser re-resolvidos de outra forma, ou aceites como estão e reportados com esta ressalva?
2. **33 resoluções da experiência B (fronteira) não passaram pelo processo de validação de resultados** que as outras experiências passam — foi uma exclusão intencional (por não envolverem otimização do regulador) ou um esquecimento a corrigir?
3. **O modelo não consegue identificar um único "imposto de carbono ótimo"** em vários casos (secções 5.2 e 5.5) — o mesmo resultado para a indústria pode corresponder a uma gama larga de impostos diferentes. O modelo deve passar a reportar um **intervalo de impostos compatíveis** em vez de um valor único, ou deve ser alterada a forma como o algoritmo escolhe entre soluções empatadas (para sempre devolver o mesmo valor de forma consistente)?
4. **Casos sem gap fechado concentram-se nas instâncias de catálogo rico (M8)** (8 em 72 na experiência C, 7 em 80 na D, 2 em 5 na G) — aceitar isto como um limite de tratabilidade documentado, ou vale a pena primeiro experimentar a configuração "viabilidade primeiro" (achado da secção 5.6) para tentar recuperar estes casos antes de fechar a campanha?
5. **A narrativa de interações do artigo deve seguir o achado empírico** (menu tecnológico × procura de mercado, secção 5.4) em vez das duas combinações hipotetizadas no plano original (menu tecnológico × retornos; menu de transporte × procura)?

---

## 7. Limitações computacionais conhecidas

- **Fronteira de tratabilidade:** a única instância com 12 períodos testada (I17_M4_T12) continua a ser a mais difícil de resolver de forma limpa — nem sequer ela fecha o gap-alvo. Não há ainda evidência de que um horizonte de 12 períodos seja viável para o resto da matriz de instâncias.
- **Escalonamento do tempo de resolução:** o catálogo rico (M8) e o horizonte mais longo (T6) continuam a ser os fatores que mais aumentam o tempo de resolução; o tamanho da rede física (I17 vs. I25) não tem efeito mensurável — consistente com o que já tinha sido observado em análises anteriores.
- **Parte da dificuldade é configuração do motor de otimização, não só dificuldade intrínseca do problema** (secção 5.6) — a diferença entre a pior e a melhor configuração testada foi superior a 20× (11 117s vs. 465s).

---

## 8. Próximos passos

1. Investigar a causa da estagnação nos dois casos-base problemáticos antes de decidir se se re-resolvem.
2. Confirmar (ou corrigir) a ausência de validação de resultados na experiência B.
3. Fazer a análise formal do ranking de fatores da experiência C, para poder desbloquear a experiência E.
4. Executar a experiência E com os fatores dominantes reais.
5. Decidir sobre a adoção da estratégia "viabilidade primeiro" como configuração revista para as classes mais pesadas.
6. Construir as ferramentas de análise permanentes que ainda faltam (atualmente só existe uma ferramenta que junta os resultados brutos numa tabela, e uma ferramenta de verificação de integridade dos dados — faltam as que calculam a fronteira custo-emissões, o ranking de fatores e as interações de forma automática e reprodutível).
7. Correr formalmente a verificação de integridade dos dados da campanha e guardar o seu resultado (até agora só foi verificado manualmente).

---

## 9. Perguntas diretas para os orientadores

- A incapacidade do modelo de identificar um único imposto de carbono ótimo (secções 5.2, 5.5, 6.3) deve ser tratada como **um resultado a reportar** (uma limitação genuína e interessante da formulação) ou como **um problema a corrigir** antes de publicar?
- É aceitável reportar a instância de 12 períodos (e possivelmente a confirmatória de catálogo rico) como estando "na fronteira de tratabilidade", dado que o mecanismo de falha é estagnação do algoritmo e não esgotamento de tempo?
- A narrativa de interações do artigo deve seguir o achado empírico (menu tecnológico × procura de mercado) em vez da hipótese original?
- Há orçamento/tempo para re-explorar a configuração do motor de otimização antes de fechar a campanha, dado o ganho de mais de 4× encontrado?
