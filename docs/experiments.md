# Plano experimental

Aprovado a 2026-10-20. As experiências estão declaradas em [`src/clsc/experiments/plan.py`](../src/clsc/experiments/plan.py) e correm com `python -m clsc.experiments run <chave>`. Os resultados ficam em `results/experiments/` e as tabelas em `results/experiments/tables/` (`python -m clsc.experiments report`).

Método: o DBP básico de Soares et al. (2021), commit `4028eda`: só os cortes de valor no HPR, mais o limite inferior da base tributável. Uma execução de cada vez, 4 threads, seed 0.

## Perguntas

| | Pergunta | Peso |
|---|---|---|
| P1 | O método resolve o problema, e a que custo? | Base, curta |
| **P2** | **Que parâmetros mudam o imposto óptimo e as decisões da rede?** | **Principal** |
| P3 | O que ganha o regulador ao antecipar a reacção do seguidor? | Curta |

## Experiências

| Chave | O quê | Instâncias | Execuções | Limite |
|---|---|---|---|---|
| P1 | DBP em todas as instâncias (é também a base da P2) | 15 geradas + Mota | 16 | 1 h |
| P2a | Sensibilidade: 6 parâmetros × 2 níveis, um de cada vez | 4 pequenas | 48 | 30 min |
| P2b | A mesma sensibilidade | Mota | 12 | 1 h |
| P3 | O seguidor sem imposto e ao imposto fixo de referência (74 EUR/t, preço médio EUA de 2025, ESMA 2026) | 4 pequenas + Mota | 5 | 600 s por fase |
| R1 | Robustez: P2a e as bases das 4 pequenas com `--mip-gap 1e-6` (em vez de 1e-4) | 4 pequenas | 52 | 30 min |
| R2 | Mota, base, com 3 h | Mota | 1 | 3 h |
| P3b | A P3 nas outras 7 instâncias que a P1 fecha | 7 fechadas | 7 | 600 s por fase |
| R3 | Robustez: as 4 pequenas com as seeds 1–4 (com a seed 0 da P1, cinco seeds) | 4 pequenas | 16 | 1 h |

As 4 pequenas são STD_I17_M4_T3, STD_I17_M8_T3, STD_I25_M4_T3 e STD_I17_M4_T6.

## Os 6 parâmetros da sensibilidade

| Parâmetro | Níveis | Porquê |
|---|---|---|
| Peso do regulador q (w = q·E_ref) | 1e-5, 1e-3 (base 1e-4) | Preferência do regulador entre emissões e nível do imposto |
| Intensidade de emissão da produção (`e_prod_g`, só esta) | ×0,5, ×2 | Peso da produção face às matérias-primas e à remanufactura |
| Intensidade de emissão da remanufactura (`e_rem_l`) | ×0,5, ×2 | Vantagem ambiental de remanufacturar |
| Taxa de retorno (`rho`, retornos mínimo e máximo) | ×0,5, ×2 (tecto 1) | Quanto se pode remanufacturar |
| Custo da tecnologia de produção mais limpa (variável e investimento) | ×0,5, ×2 | Preço de produzir limpo |
| Taxa de juro | 5%, 20% (base 10%) | Desconta o imposto pago mas não as emissões; pesa o capital face à operação |

Não se varia a escala de todas as emissões: multiplicá-las todas por k é o mesmo problema do seguidor ao imposto τ·k, logo só reescala o imposto óptimo (τ*/k). Ficam de fora o transporte (0,2–0,5% de E) e a procura (pode tornar as instâncias impossíveis por capacidade).

## Respostas medidas

Em cada execução: τ*, emissões, custo, imposto pago, redução de emissões e aumento de custo face a τ = 0 (a primeira iteração do DBP), quota de remanufactura, emissões por fonte, instalações e tecnologias, classe do resultado e gap.

## Tabelas e figuras

| Tabela | Conteúdo | Figura |
|---|---|---|
| `main` | P1 por instância: classe, LB, UB, gap, iterações, tempo do HPR e do seguidor | Tabela do método |
| `sensitivity` | P2: cada instância e cenário, com a base da P1 | — |
| `tornado` | P2: τ* e redução nos dois níveis de cada parâmetro | Gráfico tornado por instância |
| `policy` | P3 e P3b: sem imposto, imposto de referência, óptimo do regulador e emissões mínimas E_ref, com o perfil da rede (emissões por fonte, tecnologias) | Tabela de política |
| `robustness` | R1 contra P2a: τ* e redução com gap 1e-4 e 1e-6 | — |
| `seeds` | R3 com a P1: τ*, redução, classe e tempo das 4 pequenas com as seeds 0–4 | — |

A figura `figures/tornado.png` (e `.pdf`) sai de `python -m clsc.experiments figures`.

## Limitações a declarar

- Uma seed por execução, excepto nas 4 pequenas (cinco seeds, R3).
- As instâncias difíceis e o Mota não fecham o gap em 1 h. No Mota, diferenças entre cenários menores do que o gap não são conclusivas.

## Orçamento

≈ 24–26 h de máquina, a 20 e 21 de Outubro. Ordem: P2a, P1, P3, P2b; depois R1 e R2, acrescentadas a 21 de Outubro depois de ver que τ* varia com a tolerância do seguidor e que o Mota não fecha em 1 h. P3b e R3 acrescentadas a 21 de Outubro, depois do relatório de referee (questões M4 e M7).
