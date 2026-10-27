# Plano experimental

As experiências estão declaradas em [`src/clsc/experiments/plan.py`](../src/clsc/experiments/plan.py) e correm com `python -m clsc.experiments run <chave>`; um trabalho interrompido retoma onde parou. Os resultados ficam em `results/experiments/<chave>/seed<s>/<instância>/`, as tabelas de resumo em `results/experiments/tables/` (`python -m clsc.experiments report`) e as linhas das tabelas do manuscrito saem de `python paper/tools/make_tables.py`.

Uma execução de cada vez, 4 threads, seed 0 (excepto R3). Cada trabalho do DBP corre `clsc-solve` num processo próprio; as enumerações e as avaliações do seguidor correm no processo da campanha.

## Perguntas

| | Pergunta | Experiências |
|---|---|---|
| Q1 | Como se comparam os dois métodos exactos? | P1, E1, E2, C1, C2, C5, A1, A2 |
| Q2 | Onde está o imposto óptimo e o que consegue um imposto fixo? | C2, C3, C4 (e P3, P3b nas instâncias originais) |
| Q3 | Como actua o imposto numa rede real? | P1, P2b, R2 (caso de estudo) |

## Experiências

### Primeira versão: instâncias originais e caso de estudo (20–21 de Outubro)

| Chave | O quê | Instâncias | Execuções | Limite |
|---|---|---|---|---|
| P1 | DBP em todas as instâncias (é também a base da P2) | 15 geradas + Mota | 16 | 1 h |
| P2a | Sensibilidade: 6 parâmetros × 2 níveis, um de cada vez | 4 pequenas | 48 | 30 min |
| P2b | A mesma sensibilidade | Mota | 12 | 1 h |
| P3 | O seguidor sem imposto e ao imposto fixo de referência (74 EUR/t, preço médio das licenças da UE em 2025, ESMA 2026) | 4 pequenas + Mota | 5 | 600 s por fase |
| P3b | A P3 nas outras 7 instâncias que a P1 fecha | 7 fechadas | 7 | 600 s por fase |
| R1 | Robustez: P2a e as bases das 4 pequenas com `--mip-gap 1e-6` (em vez de 1e-4) | 4 pequenas | 52 | 30 min |
| R2 | Mota, base, com 3 h | Mota | 1 | 3 h |
| R3 | Robustez: as 4 pequenas com as seeds 1–4 (com a seed 0 da P1, cinco seeds) | 4 pequenas | 16 | 1 h |

As 4 pequenas são STD_I17_M4_T3, STD_I17_M8_T3, STD_I25_M4_T3 e STD_I17_M4_T6.

### Segunda versão: os dois métodos e as instâncias calibradas (desde 26 de Outubro)

| Chave | O quê | Instâncias | Limite |
|---|---|---|---|
| E1 | Enumeração dos switching prices (esquema dicotómico de Aneja e Nair) | 15 geradas + Mota | 1 h |
| E2 | Grelha de impostos de 1 EUR/t em 1 EUR/t | 4 pequenas | 1 h |
| C1 | DBP | 39 calibradas | 1 h |
| C2 | Enumeração dos switching prices | 39 calibradas | 1 h |
| C3 | O seguidor sem imposto e a 74 EUR/t | 39 calibradas | 600 s por fase |
| C4 | Sensibilidade (os 6 parâmetros) por enumeração | 4 calibradas pequenas (réplica 0) | 1 h |
| C5 | Grelha de impostos | 4 calibradas pequenas (réplica 0) | 1 h |
| A1 | Ablação: DBP sem os limites do produto bilinear (`CLSC_PRODUCT_BOUNDS=off`) | 4 calibradas pequenas | 1 h |
| A2 | Ablação: DBP sem as desigualdades válidas (`CLSC_STRENGTHENING=`) | 4 calibradas pequenas | 1 h |

As 39 calibradas são três réplicas dos doze tamanhos padrão e uma dos três tamanhos de escalada (`data/calibrated/`, ver o README). O manuscrito usa as réplicas 0 e 1 (24 instâncias); a réplica 2, a escalada e as experiências C4, C5, A1 e A2 ficam para uma revisão.

## Os 6 parâmetros da sensibilidade

| Parâmetro | Níveis | Porquê |
|---|---|---|
| Peso do regulador q (w = q·E_ref) | 1e-5, 1e-3 (base 1e-4) | Preferência do regulador entre emissões e nível do imposto |
| Intensidade de emissão da produção (`e_prod_g`, só esta) | ×0,5, ×2 | Peso da produção face às matérias-primas e à remanufactura |
| Intensidade de emissão da remanufactura (`e_rem_l`) | ×0,5, ×2 | Vantagem ambiental de remanufacturar |
| Taxa de retorno (`rho`, retornos mínimo e máximo) | ×0,5, ×2 (tecto 1) | Quanto se pode remanufacturar |
| Custo da tecnologia de produção mais limpa (variável e investimento) | ×0,5, ×2 | Preço de produzir limpo |
| Taxa de juro | 5%, 20% (base 10%) | Desconta o imposto pago mas não as emissões; pesa o capital face à operação |

Não se varia a escala de todas as emissões: multiplicá-las todas por k divide todos os switching prices por k e deixa igual a fracção do custo paga em imposto (Proposição 2 do manuscrito). Ficam de fora o transporte (0,2–0,5% de E) e a procura (pode tornar as instâncias impossíveis por capacidade).

## Respostas medidas

Em cada execução do DBP: τ*, emissões, custo, imposto pago, redução de emissões e aumento de custo face a τ = 0, quota de remanufactura, emissões por fonte, instalações e tecnologias, classe do resultado e gap. Em cada enumeração: todos os impostos avaliados (`evaluations.csv`), os switching prices, o imposto óptimo e se a enumeração ficou completa e certificada (`summary.json`).

## Tabelas

| Tabela (`results/experiments/tables/`) | Conteúdo |
|---|---|
| `main` | P1 por instância: classe, LB, UB, gap, iterações, tempo do HPR e do seguidor |
| `sensitivity` | P2a e P2b: cada instância e cenário, com a base da P1 |
| `policy` | P3 e P3b: sem imposto, imposto de referência, óptimo do regulador e emissões mínimas E_ref, com o perfil da rede |
| `robustness` | R1 contra P2a: τ* e redução com gap 1e-4 e 1e-6 |
| `seeds` | R3 com a P1: τ*, redução, classe e tempo das 4 pequenas com as seeds 0–4 |
| `methods` | DBP contra enumeração e grelha, instância a instância (P1, E1, E2; C1, C2, C5) |
| `staircase` | Os impostos candidatos de cada enumeração, com as emissões e o valor do líder: a escada da Figura 1 |
| `calibrated_policy` | Calibradas: sem imposto, a 74 EUR/t (C3), no óptimo (C2) e E_ref |
| `calibrated_sensitivity` | C4 com as bases da C2 |

As Tabelas 5–7 e S4 do manuscrito saem de `paper/tools/make_tables.py`; a Figura 1, de `paper/tools/make_figure.py`.

## Limitações a declarar

- Uma seed por execução, excepto nas 4 pequenas (cinco seeds, R3).
- As instâncias difíceis e o Mota não fecham o gap em 1 h. No Mota, diferenças entre cenários menores do que o gap não são conclusivas.
- A enumeração só certifica um resultado quando todas as resoluções do seguidor terminam dentro do limite de tempo.

## Orçamento

Primeira versão: ≈ 24–26 h de máquina, a 20 e 21 de Outubro (P2a, P1, P3, P2b; depois R1 e R2; P3b e R3 depois do relatório de referee). Segunda versão: a campanha `C2 C3 C1 C4 C5 A1 A2 E1` lançada a 26 de Outubro, com o registo em `results/experiments/run_campaign.log`.
