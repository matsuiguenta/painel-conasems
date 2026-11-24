# Origem dos dados do painel

Este documento lista, tela por tela e cartão por cartão, de onde vem cada número
exibido no painel. O objetivo é permitir **verificação humana** contra as fontes
oficiais, sem depender da confiança no código.

Regra de ouro do projeto: **nenhum dado é inventado, estimado ou completado por
suposição**. Quando a fonte oficial não publica um valor, o cartão fica sem dado
ou usa o último período oficial disponível, sempre com o período visível na tela.

---

## 1. Município e códigos usados

| Item | Valor padrão | Observação |
| --- | --- | --- |
| Município | Bandeirantes / PR | definido em `dados/config.json` |
| IBGE oficial | `4102406` (7 dígitos) | exibido na configuração |
| Código usado pelo CONASEMS | `410240` (6 primeiros dígitos) | usado nas URLs e nas APIs |
| Nome na URL | `BANDEIRANTES` | sem acentos, em maiúsculas |

Os Painéis CONASEMS identificam o município pelos **6 primeiros dígitos** do código
IBGE. O coletor aplica essa regra em `configuracao.py` e em `coletor.py`.

### Páginas oficiais de referência

- APS: <https://paineis.conasems.org.br/atencao_basica/410240/BANDEIRANTES/cit>
- MAC: <https://paineis.conasems.org.br/producao/410240/BANDEIRANTES/cit>
- Vigilância: <https://paineis.conasems.org.br/vigilancia/410240/BANDEIRANTES/cit>

As APIs ficam em `https://paineis.conasems.org.br/assets/ajax/` e são as mesmas
chamadas que o navegador faz ao abrir essas páginas.

---

## 2. Regras de período (importante para conferência)

### 2.1 Vigilância em Saúde — "Acumulado parcial"

Igual ao Painel CONASEMS, a tela de Vigilância mostra o **último ano disponível**,
inclusive o ano em curso. Quando o ano do dado é o ano atual, o cartão exibe
`Acumulado parcial (AAAA)`.

- Mortalidade geral e infantil, dengue, SRAG, internações e cobertura vacinal:
  usam o ano em curso quando a API já publica registros desse ano.
- Comparativo de tendência: quando o ano mais recente é parcial, a comparação
  usa os **dois últimos anos fechados** (ex.: 2024 → 2025), como no painel oficial.
- Tuberculose e hanseníase: a API de incidência só publica até **2025**; por isso
  o cartão mostra `2025` sem o rótulo de parcial.
- Nascidos vivos: usa o **último ano com registro completo**. Em 2026 a API
  retornava apenas registros parciais, então o cartão mantém `2025`. Este é o
  único cartão que não acompanha o ano em curso.

### 2.2 MAC — ano fechado

As telas de MAC (teto, SIA/SIH, oncologia) usam o **último ano com 12
competências** nas séries mensais. Isso evita comparar um ano incompleto com o
teto anual. O ano usado aparece no cabeçalho e nos cartões.

### 2.3 Data da última coleta

O painel exibe os dados da última coleta bem-sucedida, não um valor em tempo real.
Para conferir quando os dados foram atualizados:

```powershell
Invoke-RestMethod http://localhost:8090/api/status
```

O campo `geradoEm` de `dados/cache.js` também registra o horário da coleta.

---

## 3. Como auditar um valor

### Pelo navegador (recomendado)

1. Abra a página oficial do painel correspondente (APS, MAC ou Vigilância).
2. Compare o número do cartão com o número do nosso painel.
3. Para ver o campo exato, abra o **DevTools → Network**, recarregue a página e
   localize a requisição `POST` para `assets/ajax/...`.
4. Confira a resposta JSON: o campo indicado na tabela abaixo é o valor bruto.

### Por linha de comando

Exemplo — mortalidade geral (Vigilância):

```powershell
$h = @{ Referer = "https://paineis.conasems.org.br/vigilancia/410240/BANDEIRANTES/cit" }
$b = @{ ibge = "410240"; tipo = "cit"; indicador = "TB_Mortalidade_Geral" }
Invoke-RestMethod -Method Post `
  -Uri "https://paineis.conasems.org.br/assets/ajax/vigilanciaemsaude.php?option=get_indicator_data" `
  -Headers $h -Body $b | ConvertTo-Json -Depth 5
```

Cada item retornado tem `referencia` (data) e `obitos` (valor). O painel soma os
óbitos por ano.

---

## 4. Tela 1 — Capa (visão geral)

Arquivo: `assets/app.js` → `telaCapa()`.

| Cartão / chip | Endpoint oficial | Campo de origem |
| --- | --- | --- |
| Cobertura potencial da APS | `atencao_basica_dados.php` | `cobertura.aps.valor` (%) |
| Pessoas cobertas (potencial) | `atencao_basica_dados.php` | `cobertura.aps.potencial` |
| Cobertura de Saúde Bucal | `atencao_basica_dados.php` | `cobertura.sb.valor` (%) |
| Equipes de Saúde Bucal | `atencao_basica_dados.php` | `cobertura.sb.qtEsb20h`, `qtEsb30h`, `qtEsb40h` |
| Repasses APS no mês | `atencao_basica_dados.php` | `pagamentos.totalGeral` |
| Saúde da Família (repasse) | `atencao_basica_dados.php` | `pagamentos.totalSaudeFamilia` |
| ACS (repasse) | `atencao_basica_dados.php` | `pagamentos.totalACS` |
| Saúde Bucal (repasse) | `atencao_basica_dados.php` | `pagamentos.totalSaudeBucal` |
| Produção MAC aprovada | `producao.php?option=producaoMac` | soma de `ValorAprovado` (SIA) + `valor_total` (SIH) no ano fechado |
| AIH aprovadas (chip) | `producao.php?option=producaoMac` | soma de `aih_aprovadas` no ano fechado |
| Procedimentos aprovados (chip) | `producao.php?option=producaoMac` | soma de `QtdAprovada` no ano fechado |
| Equipes homologadas (chip) | `atencao_basica_dados.php` | `homologacao.equipes.total` |
| ACS (chip) | `atencao_basica_dados.php` | `cobertura.acs.qtAcsCobertura` |
| Visitas domiciliares (chip) | `atencao_basica_dados.php` | `producao.visitasDomiciliares` |

Requisição base da APS:

```text
POST https://paineis.conasems.org.br/assets/ajax/atencao_basica_dados.php
Corpo: ibge=410240&tipo=cit
```

---

## 5. Tela 2 — Cobertura da Atenção Primária

Arquivo: `assets/app.js` → `telaCobertura()`.

| Elemento | Endpoint oficial | Campo de origem |
| --- | --- | --- |
| Anel "Cobertura da APS" | `atencao_basica_dados.php` | `cobertura.aps.valor` |
| Equipes da APS | `atencao_basica_dados.php` | `cobertura.aps.qtdEsf`, `qtdEap20h`, `qtdEap30h`, `qtdEcr`, `qtdEapp`, `qtdEsfr` |
| Potencial da APS | `atencao_basica_dados.php` | `cobertura.aps.potencial` |
| Anel "Saúde Bucal" | `atencao_basica_dados.php` | `cobertura.sb.valor` |
| Equipes de Saúde Bucal | `atencao_basica_dados.php` | `cobertura.sb.qtEsb20h`, `qtEsb30h`, `qtEsb40h` |
| Potencial da Saúde Bucal | `atencao_basica_dados.php` | `cobertura.sb.potencial` |
| Anel "Agentes Comunitários" | `atencao_basica_dados.php` | `cobertura.acs.valor` |
| Quantidade de ACS | `atencao_basica_dados.php` | `cobertura.acs.qtAcsCobertura` |
| Potencial dos ACS | `atencao_basica_dados.php` | `cobertura.acs.potencial` |
| Equipes homologadas | `atencao_basica_dados.php` | `homologacao.equipes.total` |
| Equipes sem envio de produção | `atencao_basica_dados.php` | `ausencia.total` |
| Solicitações em aberto | `atencao_basica_dados.php` (action `gaps_data`) | linhas de `solicitacoes` com status "SOLICITADA" |

Nota de cobertura acima de 100%: o aviso da tela reproduz a regra da nota técnica
do Ministério da Saúde; o valor não é limitado a 100.

---

## 6. Tela 3 — Produção da Atenção Primária

Arquivo: `assets/app.js` → `telaProducaoAps()`.

| Cartão | Endpoint oficial | Campo de origem |
| --- | --- | --- |
| Consultas médicas | `atencao_basica_dados.php` | `producao.atendimentoMedico` |
| Consultas de enfermagem | `atencao_basica_dados.php` | `producao.atendimentoEnfermeiro` |
| Atendimentos odontológicos | `atencao_basica_dados.php` | `producao.atendimentoOdontologico` |
| Procedimentos realizados | `atencao_basica_dados.php` | `producao.procedimentos` |
| Visitas domiciliares | `atencao_basica_dados.php` | `producao.visitasDomiciliares` |
| Por habitante (cada item) | `atencao_basica_dados.php` | `producao.mediaMedHab`, `mediaEnfHab`, `mediaOdontoHab`, `mediaProcedimentosHab`, `mediaVisitasHab` |
| Competência | `atencao_basica_dados.php` | `producao.referencia` |
| Equipes com ausência de envio | `atencao_basica_dados.php` | `ausencia.total` |
| Equipes homologadas | `atencao_basica_dados.php` | `homologacao.equipes.total` |
| Estabelecimentos homologados | `atencao_basica_dados.php` | `homologacao.estabelecimentos.total` |

Os valores "por habitante" vêm prontos do SIAPS. O painel não recalcula população.

---

## 7. Tela 4 — Financiamento da APS

Arquivo: `assets/app.js` → `telaFinanciamentoAps()`.

| Elemento | Endpoint oficial | Campo de origem |
| --- | --- | --- |
| Total de repasses no mês | `atencao_basica_dados.php` | `pagamentos.totalGeral` |
| Saúde da Família | `atencao_basica_dados.php` | `pagamentos.totalSaudeFamilia` |
| Agentes Comunitários | `atencao_basica_dados.php` | `pagamentos.totalACS` |
| Saúde Bucal | `atencao_basica_dados.php` | `pagamentos.totalSaudeBucal` |
| Competência | `atencao_basica_dados.php` | `pagamentos.referencia` |
| Histórico mensal | `atencao_basica_dados.php` | `pagamentos.labelsHistory`, `pagamentos.totalHistory` |
| Média móvel 12 meses | `atencao_basica_dados.php` | `pagamentos.movingAvg12` |

Valores derivados exibidos na tabela:

- **Repasse por habitante** = `totalGeral` ÷ `cobertura.aps.potencial`.
- **Média mensal (12 meses)** = média dos 12 últimos valores de `totalHistory`.
- **Maior repasse do período** = maior valor de `totalHistory` no mesmo recorte.
- **% Saúde da Família / Saúde Bucal** = parte ÷ `totalGeral` × 100.

---

## 8. Tela 5 — Visitas domiciliares dos ACS

Arquivo: `assets/app.js` → `telaVisitasAcs()`.

Endpoint oficial:

```text
POST https://paineis.conasems.org.br/assets/ajax/epidemiologia.php?option=visitaacs
Corpo: ibge=410240&tipo=cit
```

| Elemento | Campo de origem |
| --- | --- |
| Competência | `Data` do registro mais recente |
| Visitas realizadas | `VisitaRealizada` |
| Ausentes | `Ausente` |
| Recusadas | `VisitaRecusada` |
| Total de visitas previstas | `VisitaRealizada + Ausente + VisitaRecusada` |
| ACS credenciados | `QtdAcs` |
| Histórico de 12 meses | mesmos campos, últimos 12 registros por `Data` |

Valores derivados:

- **Média por ACS no mês** = `VisitaRealizada` ÷ `QtdAcs`.
- **Visitas por ACS em dia útil** = `VisitaRealizada` ÷ (`QtdAcs` × 22).
  O divisor 22 é a mesma regra de dias úteis usada pelo painel oficial.
- **% realizadas** = `VisitaRealizada` ÷ total previsto × 100.

---

## 9. Tela 6 — Credenciamento e cofinanciamento

Arquivo: `assets/app.js` → `telaCredenciamento()`.

| Cartão / bloco | Endpoint oficial | Campo de origem |
| --- | --- | --- |
| Equipes homologadas | `atencao_basica_dados.php` | `homologacao.equipes.total` |
| Estabelecimentos homologados | `atencao_basica_dados.php` | `homologacao.estabelecimentos.total` |
| Solicitações credenciadas | `atencao_basica_dados.php` (action `gaps_data`) | linhas de `solicitacoes` com status "CREDENCIADA" |
| Solicitações em andamento | `atencao_basica_dados.php` (action `gaps_data`) | linhas com status "SOLICITADA" |
| Total de solicitações | `atencao_basica_dados.php` (action `gaps_data`) | quantidade de linhas de `solicitacoes` |
| Competência | `atencao_basica_dados.php` (action `gaps_data`) | `referenciaFormatada` |
| Desempenho CVAT | `producao.php?option=cofinanciamento` | `dimensao_indicador`, `quadrimestre`, `regular`, `suficiente`, `bom`, `otimo` |

Requisição de credenciamento:

```text
POST https://paineis.conasems.org.br/assets/ajax/atencao_basica_dados.php
Corpo: action=gaps_data&ibge=410240&tipo=cit&ref_gaps=AAAA-MM-01&rdqa=0
```

Regras de contagem das solicitações: o texto de cada linha é normalizado e
classificado pela palavra presente — "CREDENCIADA", "SOLICITADA", "ANÁLISE" ou
"PORTARIA". Linhas sem essas palavras entram em "outras" e não aparecem nos cartões.

Cofinanciamento: o painel considera apenas registros cuja
`dimensao_indicador` contém `Dimensão Acompanhamento` e soma, por quadrimestre,
as colunas `regular`, `suficiente`, `bom` e `otimo`.

---

## 10. Tela 7 — Teto MAC e produção

Arquivo: `assets/app.js` → `telaMacTeto()`.

### 10.1 Teto MAC

O teto não tem endpoint JSON. O coletor lê os cartões da própria página oficial:

```text
GET https://paineis.conasems.org.br/producao/410240/BANDEIRANTES/cit
```

| Cartão | Origem no HTML | Campo interno |
| --- | --- | --- |
| Teto MAC sem incentivos | `<h5 class="saas-title">` com "sem" + `<h4 class="saas-value">` | `teto.semIncentivos` |
| Incentivos adicionais | título com "incentivo" + `saas-value` | `teto.incentivos` |
| Teto MAC total | título com "total" + `saas-value` | `teto.total` |
| Valores mensais | trecho `Mensal: <strong>...</strong>` de cada cartão | `mensalSemIncentivos`, `mensalIncentivos`, `mensalTotal` |
| Período | texto `SISMAC, MM/AAAA a MM/AAAA` | `teto.periodo` |

### 10.2 Produção MAC

Endpoint oficial:

```text
POST https://paineis.conasems.org.br/assets/ajax/producao.php?option=producaoMac
Corpo: ibge=410240&tipo=cit&filtroAmbulatorial=atendimento&filtroHospitalar=internacao
```

Resposta: uma lista com duas séries mensais — `[SIA, SIH]`.

| Cartão | Campo de origem |
| --- | --- |
| Produção MAC aprovada (SIA + SIH) | soma de `ValorAprovado` (SIA) + `valor_total` (SIH) |
| SIA (parte) | soma de `ValorAprovado` |
| SIH (parte) | soma de `valor_total` |
| Diferença teto × produção (com incentivos) | `teto.total` − produção total |
| Diferença sem incentivos | `teto.semIncentivos` − produção total |

Valores derivados: o ano é o último com **12 competências** em ambas as séries.
Os valores mensais do gráfico vêm de `referencia` (MM/AAAA) e dos mesmos campos.

---

## 11. Tela 8 — Produção ambulatorial e hospitalar (SIA/SIH)

Arquivo: `assets/app.js` → `telaSiaSih()`.

Mesmo endpoint `producao.php?option=producaoMac` da tela anterior.

| Cartão | Campo de origem |
| --- | --- |
| SIA · procedimentos aprovados | soma de `QtdAprovada` no ano fechado |
| SIA · apresentados | soma de `QtdApresentada` |
| SIA · glosa | `ValorApresentado` − `ValorAprovado` |
| SIA · % de aprovação (quantidade) | `QtdAprovada` ÷ `QtdApresentada` × 100 |
| SIH · AIH aprovadas | soma de `aih_aprovadas` |
| SIH · valor | soma de `valor_total` |
| SIH · média por AIH | `valor_total` ÷ `aih_aprovadas` |
| Evolução mensal | `referencia`, `ValorAprovado`, `valor_total` |

O ano exibido é o último com 12 competências nas duas séries, igual ao painel
oficial de produção.

---

## 12. Tela 9 — Oncologia e saúde mental

Arquivo: `assets/app.js` → `telaOncologiaMental()`.

### 12.1 Oncologia

| Elemento | Endpoint oficial | Campo de origem |
| --- | --- | --- |
| Tempo médio até o tratamento | `producao.php?option=oncologiaTempoTratamento` | `tempo_medio_dias` |
| % iniciados em até 60 dias | idem | `pct_ate_60_dias` |
| Casos tratados | idem | `total_com_tratamento` |
| Casos no ano | idem | `total_casos` |
| Acima de 60 dias | idem | `mais_de_60_dias` |
| Diagnósticos mais frequentes | `producao.php?option=oncologiaCasos` | `diagnostico` e `casos`, agrupados no ano mais recente |
| Total de casos novos | idem | soma de `casos` no ano |

Corpo de ambas: `ibge=410240&tipo=cit`. A referência do tempo de tratamento é o
registro mais recente da série por `referencia`; o detalhamento de casos usa o
ano mais recente presente em `data`.

### 12.2 Saúde mental

| Elemento | Endpoint oficial | Campo de origem |
| --- | --- | --- |
| Atendimentos ambulatoriais (SIA) | `producao.php?option=saudeMental` | soma de `sia[].qtd_aprovada` |
| Internações (AIH) | idem | soma de `sih[].qtd_aih` |
| Valor das internações | idem | `sih[].valor_total` |
| CID-10 mais atendidos | idem | `cid_detail[].cid`, `descricao`, `sia_total`, `sih_total` |
| Ano | idem | `selected_year` |

O painel soma `sia_total + sih_total` por CID e mostra os cinco maiores.

---

## 13. Tela 10 — Vigilância em saúde

Arquivo: `assets/app.js` → `telaVigilancia()`.

Todos os endpoints ficam em:

```text
POST https://paineis.conasems.org.br/assets/ajax/vigilanciaemsaude.php?option=...
Corpo base: ibge=410240&tipo=cit
```

| Cartão / bloco | `option` / indicador | Campo de origem | Período exibido |
| --- | --- | --- | --- |
| Mortalidade geral | `get_indicator_data` + `indicador=TB_Mortalidade_Geral` | `obitos`, agrupado por ano de `referencia` | último ano disponível (2026 parcial) |
| Mortalidade infantil | `get_indicator_data` + `indicador=TB_Mortalidade_Infantil` | `obitos`, agrupado por ano | último ano disponível |
| Tuberculose | `get_indicator_data` + `indicador=TB_Incidencia_Tuberculose` | `ano`, `valor` (coeficiente por 100 mil) | 2025 (último publicado) |
| Hanseníase | `get_indicator_data` + `indicador=TB_Incidencia_Hanseniase` | `ano`, `valor` | 2025 (último publicado) |
| Dengue | `epidemiologia.php?option=Dengue` | chaves `AnoAAAA` → casos | último ano disponível |
| SRAG | `get_srag_table_data` | `data[].year`, `total`, `incidence`, `population` | ano atual |
| Nascidos vivos | `nascidosVivosPaginado` | `TotalNascidosGlobal`, `TotalCesareoGlobal`, `TotalVaginalGlobal` | último ano completo (2025) |
| Internações por capítulo CID-10 | `morbidadeHospitalar` + `local_morbidade=internacao`, `ano=AAAA` | `ds_lista_morb`, `internacoes` | ano atual |
| Internações por causas externas | idem | capítulo CID-10 iniciado em `XIX` | ano atual |
| Cobertura vacinal | `vigenciaCoberturaVacinal` | `ano`, `BCG`, `Penta`, `Poliomielite`, `MeningococoC`, `Pneumococica`, `TripliceViralD1`, `FebreAmarela`, `HepatiteA` | ano mais recente |

### 13.1 Percentuais e derivados da Vigilância

- **Mortalidade**: soma de `obitos` por ano; a tendência compara os dois últimos
  anos fechados quando o ano mais recente é parcial.
- **SRAG**: `total` e `incidence` vêm prontos da API. O painel não recalcula
  incidência.
- **Nascidos vivos**: `% por cesariana` = `TotalCesareoGlobal` ÷
  `TotalNascidosGlobal` × 100.
- **Internações**: total = soma de `internacoes` de todos os capítulos; a lista
  mostra os 6 maiores. "Causas externas" = capítulo `XIX`.
- **Cobertura vacinal**: o painel mostra até 6 vacinas na barra horizontal, com
  meta fixa de 95% (padrão do Programa Nacional de Imunizações). A média exibida
  é a média simples das coberturas retornadas.

### 13.2 Requisição de exemplo

```text
POST https://paineis.conasems.org.br/assets/ajax/vigilanciaemsaude.php?option=get_srag_table_data
Corpo: ibge=410240&tipo=cit
```

A resposta traz a série anual; o painel seleciona o item cujo `year` é o ano atual.

---

## 14. Limitações conhecidas (e por que existem)

| Situação | Motivo | Efeito no painel |
| --- | --- | --- |
| Nascidos vivos em 2025, não 2026 | a API de 2026 retornava poucos registros (incompleta) no momento da coleta | cartão mostra 2025 |
| Tuberculose/hanseníase em 2025 | a API de incidência ainda não publica 2026 | cartão mostra 2025, sem "parcial" |
| MAC em ano fechado | séries mensais precisam de 12 competências para comparar com o teto anual | ano fechado no cabeçalho |
| Valores podem ficar atrás do painel oficial | o painel usa o cache da última coleta | atualize com `/api/atualizar` ou aguarde o ciclo |
| SRAG/mortalidade/dengue de 2026 mudam durante o ano | são acumulados parciais, atualizados pela fonte | valor cresce conforme a fonte publica |
| Solicitações de credenciamento | a classificação depende do texto de status retornado | status desconhecido não entra nos cartões |

---

## 15. Checklist rápido de verificação

Para cada tela, confira nesta ordem:

1. O **município** no cabeçalho é o correto (Bandeirantes / PR).
2. O **período** exibido no cartão é o mesmo do painel oficial.
3. O **valor** coincide com o campo listado neste documento.
4. Em caso de divergência, confira a **data da última coleta** (`/api/status`).
5. Se o painel oficial mudou e o nosso não, rode uma nova coleta:

```powershell
Invoke-RestMethod "http://localhost:8090/api/atualizar"
```

Se o valor continuar divergente após nova coleta, o campo ou o endpoint pode ter
mudado na fonte oficial. Nesse caso, corrija `coletor.py` e atualize este
documento antes de considerar o dado válido.
