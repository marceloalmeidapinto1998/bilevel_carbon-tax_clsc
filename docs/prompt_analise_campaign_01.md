# Prompt: análise completa da campaign_01

Analisa todos os resultados da campanha computacional `campaign_01` (modelo bilevel CLSC sob
imposto de carbono). A campanha está **completa** (381 corridas, 119,6h de Gurobi) — este é um
pedido de análise, não de mais computação. Não relances nenhuma corrida sem pedir autorização
primeiro.

## Antes de analisar

1. Lê `docs/Experimental_Plan.md` (v3) na íntegra — é a fonte de verdade sobre o que já está
   confirmado, por hipótese (H1.1–H8.2), com números reais medidos, não projeções.
2. Corre `python -m clsc.analysis.campaign_01.aggregate` para atualizar
   `results/analysis/campaign_01/tables/master_runs_campaign_01.csv`, e trabalha a partir daí.
3. Cruza os dois — não cites o plano às cegas nem reconstruas tudo do zero a partir do CSV; usa
   um para verificar o outro.

## Armadilhas específicas desta campanha (já aconteceram, não repetir)

- **Nunca recalcules USD/tonelada a partir de `SCALE_FACTOR`.** Há duas grelhas de imposto no
  sistema (fina, 1e-4; grossa, 1e-2, nativa das instâncias) — usa sempre a coluna
  `leader_tax_usd_per_tonne` já calculada pelo agregador.
- **`solve_status="censored"` não significa "sem valor válido".** Desde a correção do cap de
  tempo, uma censura por `termination_reason="wall_clock_cap"` carrega um incumbente real e um gap
  certificado; só `wall_clock_cap_killed` não tem nada aproveitável. Distingue sempre pelo
  `termination_reason`, nunca só pelo `solve_status`.
- **Um manifesto pode ter sido corrigido pós-hoc.** O resultado da exp8 em `STD_I17_M4_T6` foi
  corrigido via `scripts/recompute_enumeration_incumbent.py` (bug de tolerância na seleção de
  incumbente da enumeração) e tem um campo `_correction` no JSON — não é uma anomalia a investigar,
  é uma correção documentada.
- **Variância de seed é estrutural, não ruído.** CV até 40-50% entre seeds na mesma célula
  estrutural. Nenhuma comparação pode assentar num único seed numa célula standard/rápida; usa
  sempre comparações emparelhadas dentro do mesmo seed.

## O que já está confirmado (não redescobrir, verificar e sintetizar)

- **exp5 (planalto, headline):** H5.1/H5.2 confirmadas em 12/12 células; largura do planalto
  medida diretamente via refinamento local (120/120 corridas).
- **exp3 (ablação):** A1 e A4 falham 6/6 nas células representativas; A2/A3/A5 não mudam o ótimo.
- **exp4 (escalabilidade):** sonda M12 censurada mas ancorada (gap 0,96%).
- **exp7 (calibração):** H7.1 não suportada (τ*(ρ) não-monótona, mas certificada — é um achado
  real, não um erro); H7.2 resolvida por transição de regime, ρ*=1; âncora AUGMECON revela uma
  lacuna do instrumento fiscal de ~0,5% face ao mínimo físico de emissões.
- **exp8 (benchmark de enumeração):** H8.1/H8.2 confirmadas (2 células exatas-vs-exatas, redução
  de ~130-180× em resoluções de seguidor); bug de tolerância numérica encontrado e corrigido no
  processo.

## O que falta mesmo (o único item genuinamente em aberto)

- **exp6 (sensibilidade):** as 144 corridas terminaram, mas a análise formal (ANOVA em blocos,
  método de Lenth, correção Benjamini-Hochberg, teste de estabilidade top-3 entre seeds) **nunca
  foi feita**. É o item prioritário desta análise.

## Entregável esperado

Uma síntese por pergunta de investigação (RQ1–RQ7, mapeadas na §1 do plano), com:
- o que está estatisticamente sólido e pronto para o artigo,
- o que precisa do passo analítico da exp6 antes de poder ser afirmado,
- quaisquer inconsistências entre o plano e os dados atuais que valha a pena assinalar.
