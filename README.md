# Painel CONASEMS — APS, MAC & Vigilância em Saúde

Painel animado para TV com os principais indicadores da **Atenção Primária (APS)**, da
**Média e Alta Complexidade (MAC)** e da **Vigilância em Saúde** do município monitorado,
coletados dos Painéis CONASEMS.

O painel foi pensado para ficar exposto na sala da Secretaria de Saúde: alterna as telas
automaticamente, atualiza os dados periodicamente e continua mostrando a última coleta
mesmo sem internet. O município e o logo da Secretaria são escolhidos em uma página de
configuração, sem editar código.

- Fontes: [Painéis CONASEMS](https://paineis.conasems.org.br) (SIAPS, SISMAC, Vigilância
  em Saúde e DATASUS/MS), endpoints públicos.
- Sem dependências externas: apenas **Python 3.10+** (biblioteca padrão) e um navegador.
- Roda no **Windows** com os iniciadores `.bat` ou em **Linux/Docker**, inclusive em um
  servidor interno com **Coolify**.
- 10 telas: capa, cobertura APS, produção APS, financiamento APS, visitas dos ACS,
  credenciamento/cofinanciamento, teto MAC, produção SIA/SIH, oncologia/saúde mental e
  vigilância em saúde.

---

## Índice

- [Início rápido (Windows)](#início-rápido-windows)
- [Configuração do município e do logo](#configuração-do-município-e-do-logo)
- [Docker](#docker)
- [Produção com Coolify](#produção-com-coolify)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Volume, backup e restauração](#volume-backup-e-restauração)
- [Como os dados são atualizados](#como-os-dados-são-atualizados)
- [API](#api)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Segurança](#segurança)
- [Solução de problemas](#solução-de-problemas)

---

## Início rápido (Windows)

| Arquivo | O que faz |
| --- | --- |
| `iniciar.bat` | Sobe o servidor local e abre o painel na janela normal do navegador. |
| `iniciar-tv.bat` | Sobe o servidor e abre o painel em **tela cheia (kiosk)**, ideal para a TV. |

Dê um duplo clique em `iniciar-tv.bat` na máquina ligada à TV. O painel abre em
`http://localhost:8090/` e a configuração em `http://localhost:8090/config`.

Uso manual:

```bat
cd painel-conasems
python servidor.py                 :: abre o navegador automaticamente
python servidor.py --tv            :: modo TV (nao abre o navegador)
python servidor.py --porta 8090 --intervalo 20 --host 127.0.0.1
python coletor.py                  :: apenas coleta e grava os dados
```

### Teclas e controles

| Tecla / ação | Efeito |
| --- | --- |
| `→` / `←` | próxima / tela anterior |
| `Espaço` | pausa / retoma a rotação automática |
| `F` | entra / sai da tela cheia |
| ícone de engrenagem no rodapé | abre a configuração de município e logo |
| passar o mouse sobre o painel | pausa enquanto o mouse estiver sobre a tela |
| bolinhas no rodapé | ir direto para uma tela |

---

## Configuração do município e do logo

Acesse `http://localhost:8090/config` (ou clique na engrenagem no rodapé do painel).

1. **Município**: digite o nome, a UF ou o código IBGE. A lista usa a base completa do
   IBGE (5.571 municípios). Selecione a sugestão para confirmar UF e código.
2. **Logo**: envie uma imagem **PNG, JPG, WEBP ou SVG** de até **2,5 MB**. O logo aparece
   no cabeçalho do painel, na página de configuração e na pré-visualização.
3. Clique em **Salvar e atualizar dados**.

Ao trocar o município, os dados do município anterior são apagados do banco e do cache, e
uma nova coleta é disparada na hora (pode levar até um minuto). Depois de salvar, recarregue
a TV (`F5`) para aplicar o novo logo e município.

A configuração fica em:

| Arquivo | Conteúdo |
| --- | --- |
| `dados/config.json` | município, caminho do logo e datas de atualização |
| `dados/config.js` | mesma configuração em JavaScript, carregada pelo painel |
| `dados/logo.png` (ou `.jpg`, `.webp`, `.svg`) | logo enviado |

> O código IBGE oficial tem 7 dígitos (ex.: `4102406`). Os Painéis CONASEMS usam o código
> de 6 dígitos, sem o dígito verificador (ex.: `410240`). O projeto converte
> automaticamente — não é necessário ajustar nada no painel.

---

## Docker

O projeto inclui `Dockerfile`, `docker-entrypoint.sh` e `docker-compose.yml`, sem dados de
execução na imagem. O diretório `/app/dados` é um volume persistente.

### Build e execução com Compose

```bash
docker compose up -d --build
```

Painel: <http://localhost:8090/> · Configuração: <http://localhost:8090/config>

```bash
docker compose logs -f        # acompanhar a coleta
docker compose ps             # ver o healthcheck
docker compose down           # parar (o volume de dados permanece)
```

### Build e execução manual

```bash
docker build -t painel-conasems .
docker run -d --name painel-conasems \
  -p 8090:8090 \
  -e PAINEL_INTERVALO_MINUTOS=20 \
  -v painel-dados:/app/dados \
  --restart unless-stopped \
  painel-conasems
```

A imagem usa `python:3.13-slim`, instala `gosu` e roda o servidor com o usuário `painel`
(UID/GID `10001`). O entrypoint ajusta o dono do volume e então baixa privilégios. O
healthcheck chama `GET /api/status` a cada 30 segundos.

---

## Produção com Coolify

1. Envie o projeto para um repositório Git (GitHub/GitLab) e, no Coolify, crie um novo
   recurso apontando para ele.
2. Escolha o build pack **Dockerfile** (ou use o `docker-compose.yml`).
3. Exponha a porta **8090** e configure o domínio interno, por exemplo
   `http://painel.saude.local:8090` ou um domínio com HTTPS pelo proxy do Coolify.
4. Crie um **volume persistente** mapeado para **`/app/dados`**. Sem ele, a configuração,
   o logo e o histórico são perdidos a cada deploy.
5. Defina as variáveis de ambiente desejadas (veja a tabela abaixo). O healthcheck pode
   usar o caminho **`/api/status`**.
6. Faça o deploy e acompanhe os logs. Na primeira execução o banco é criado e a primeira
   coleta é feita automaticamente; depois, o município pode ser alterado em `/config`.

Observações para o Coolify:

- Use **apenas uma réplica**. O coletor grava em SQLite e não há coordenação entre
  instâncias; duas réplicas atualizando o mesmo volume podem gerar conflitos.
- O volume precisa permitir escrita pelo UID `10001`. O entrypoint tenta corrigir o dono
  ao iniciar; se o armazenamento não permitir `chown`, ajuste as permissões no host.
- A troca de município faz uma coleta síncrona (até ~1 minuto). Se o proxy do Coolify
  tiver timeout muito baixo, aumente-o ou faça a troca pela rede interna.
- O fuso é definido por `TZ=America/Sao_Paulo` (padrão da imagem).

---

## Variáveis de ambiente

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `PORT` | `8090` | Porta HTTP (também pode usar `--porta`). |
| `HOST` | `127.0.0.1` no Windows; `0.0.0.0` na imagem | Interface de escuta. |
| `PAINEL_INTERVALO_MINUTOS` | `20` | Intervalo da atualização automática em segundo plano. |
| `PAINEL_DADOS` | `./dados` (ou `/app/dados` na imagem) | Pasta do banco, cache, configuração e logo. |
| `PAINEL_IBGE` | `4102406` | IBGE inicial, usado só quando ainda não existe `config.json`. |
| `PAINEL_MUNICIPIO` | `Bandeirantes` | Nome inicial do município. |
| `PAINEL_UF` | `PR` | UF inicial. |
| `TZ` | `America/Sao_Paulo` na imagem | Fuso horário exibido no painel e nos horários da coleta. |

> As variáveis `PAINEL_IBGE`, `PAINEL_MUNICIPIO` e `PAINEL_UF` definem apenas o ponto de
> partida. Depois que `dados/config.json` existe, o que vale é a configuração salva em
> `/config`.

---

## Volume, backup e restauração

Guarde a pasta de dados inteira (no Docker, o volume montado em `/app/dados`):

| Arquivo | Necessário no backup? | Observação |
| --- | --- | --- |
| `config.json` | **Sim** | município e referência do logo |
| `logo.*` | **Sim** | imagem enviada |
| `conasems.db` | Recomendado | histórico de coletas |
| `cache.js` | Não | gerado novamente na próxima coleta |
| `config.js` | Não | gerado a partir de `config.json` |

Backup de um volume Docker:

```bash
docker run --rm -v painel-dados:/dados -v "$PWD:/backup" alpine \
  tar czf /backup/painel-dados-$(date +%F).tar.gz -C /dados .
```

Restauração:

```bash
docker run --rm -v painel-dados:/dados -v "$PWD:/backup" alpine \
  sh -c "rm -rf /dados/* && tar xzf /backup/painel-dados-AAAA-MM-DD.tar.gz -C /dados"
docker compose restart
```

No Windows, basta copiar a pasta `dados/` com o servidor parado.

---

## Como os dados são atualizados

1. Ao abrir/carregar a página, o navegador chama `GET /api/dados?refresh=1`.
2. O servidor só dispara uma nova coleta se a última tiver mais de ~5 minutos; entre duas
   coletas existe um intervalo mínimo de **180 segundos** para não sobrecarregar o CONASEMS.
3. Com a página aberta, ela consulta o servidor a cada **3 minutos**.
4. Em paralelo, o servidor atualiza sozinho a cada **20 minutos** (configurável).
5. Toda coleta é gravada no SQLite **e** regravada em `dados/cache.js`.

### Funcionamento offline

- O último resultado fica em `dados/conasems.db` e em `dados/cache.js`.
- Se o servidor não responder ou a internet cair, a página usa o cache e mostra o selo
  **MODO CACHE**, com aviso e hora da última coleta.
- Mesmo abrindo `index.html` diretamente pelo `file://` (sem servidor) o painel funciona,
  desde que `dados/cache.js` exista. O logo também é carregado via `dados/config.js`.
- Quando a conexão volta, o painel se atualiza sozinho na próxima consulta.

---

## API

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/` | Painel para TV. |
| `GET` | `/config` | Página de configuração (município e logo). |
| `GET` | `/api/dados` | Último resumo salvo; `?refresh=1` atualiza se estiver velho; `?force=1` força a coleta. |
| `GET` | `/api/status` | Situação do servidor, coleta, município e intervalo. Usado no healthcheck. |
| `GET` | `/api/config` | Configuração atual e situação da última coleta. |
| `GET` | `/api/municipios` | Lista `[IBGE, nome, UF]` dos municípios do IBGE. |
| `POST` | `/api/config` | Salva município e/ou logo e, se o município mudar, coleta novamente. |
| `GET` | `/api/atualizar` | Força uma coleta agora. |

Exemplo de `POST /api/config`:

```json
{
  "ibge": "4102406",
  "logoDataUrl": "data:image/png;base64,...",
  "removerLogo": false
}
```

Use `"removerLogo": true` (sem `logoDataUrl`) para apagar o logo.

---

## Estrutura do projeto

```
painel-conasems/
├─ index.html            Painel + sprite de ícones SVG
├─ config.html           Página de configuração (município e logo)
├─ assets/
│  ├─ estilo.css         Tokens visuais, cartões, gráficos, animações, responsivo
│  ├─ app.js             Montagem das 10 telas, gráficos SVG, navegação e cache
│  └─ municipios.json    Base do IBGE (5.571 municípios)
├─ dados/                Runtime: SQLite, cache, config e logo (volume Docker)
├─ configuracao.py       Configuração, lista IBGE, URLs, logo e config.js
├─ coletor.py            Coleta os endpoints públicos e grava banco/cache
├─ servidor.py           Servidor HTTP, API e atualização em segundo plano
├─ Dockerfile            Imagem Linux com usuário sem privilégios e healthcheck
├─ docker-entrypoint.sh  Ajuste do volume e execução via gosu
├─ docker-compose.yml    Exemplo de execução local/produção
├─ iniciar.bat           Windows: inicia e abre o painel
├─ iniciar-tv.bat        Windows: inicia em modo kiosk para a TV
└─ README.md
```

### Banco de dados (SQLite)

| Tabela | Conteúdo |
| --- | --- |
| `coletas` | cada execução do coletor (data/hora, status, avisos) |
| `painel` | último payload completo (JSON) usado pela API |
| `indicadores` | valor mais recente de cada indicador |
| `historico` | série histórica dos indicadores a cada coleta |
| `series` | séries históricas (repasses, visitas, vacinação, internações etc.) |

### Endpoints do CONASEMS usados (públicos)

- APS: `atencao_basica_dados.php` (cobertura, homologação, pagamentos, ausência, produção,
  solicitações GAPS), `epidemiologia.php?option=visitaacs`, `producao.php?option=cofinanciamento`.
- MAC: `producao.php?option=producaoMac` (SIA/SIH), `producaoComplexidade`,
  `producaoFinanciamentoSia`, `oncologiaTempoTratamento`, `oncologiaCasos`, `saudeMental`.
- Vigilância: `vigilanciaemsaude.php` (`get_indicator_data`, `morbidadeHospitalar`,
  `get_srag_table_data`, `vigenciaCoberturaVacinal`, `nascidosVivosPaginado`) e
  `epidemiologia.php?option=Dengue`.
- Teto MAC: extraído dos cartões `saas-value` da página do painel MAC.

> A produção MAC considera todos os estabelecimentos do território, inclusive os de gestão
> estadual. Por isso o valor produzido pode ser maior que o teto municipal — o painel
> explica essa diferença na tela 7.

---

## Segurança

- O servidor expõe apenas o painel, a configuração, `assets/`, `dados/cache.js`,
  `dados/config.js` e o logo configurado. Banco, código Python e logs não são servidos.
- **A página `/config` e o `POST /api/config` não têm autenticação.** Use o painel em rede
  interna ou coloque-o atrás de um proxy com autenticação (Coolify/Traefik, VPN etc.) antes
  de expor na internet.
- No Windows, o servidor escuta apenas em `127.0.0.1` por padrão. No Docker, escuta em
  `0.0.0.0` para receber o tráfego do proxy/porta publicada.
- O logo aceito é limitado a 2,5 MB e a tipos de imagem conhecidos (PNG, JPG, WEBP, SVG).

---

## Solução de problemas

| Sintoma | O que verificar |
| --- | --- |
| “Nenhum dado disponível” | Rode `python coletor.py` ou `iniciar.bat`; confira se `dados/cache.js` existe. |
| Porta 8090 ocupada | Outro servidor já está rodando; abra `http://localhost:8090/` ou use `--porta 8091`. |
| `python` não encontrado | Instale o Python 3.10+ marcando “Add to PATH”, ou use `py -3`. |
| Selo “MODO CACHE” | Sem internet ou servidor parado. Os dados continuam visíveis; atualiza sozinho quando voltar. |
| Aviso “Coleta parcial” | Algum endpoint do CONASEMS não respondeu; os demais dados continuam válidos. Tente atualizar em alguns minutos. |
| Container reinicia ou fica `unhealthy` | Veja `docker logs painel-conasems`; confirme que o volume `/app/dados` é gravável pelo UID `10001`. |
| Configuração não persiste no deploy | O volume `/app/dados` não está mapeado. |
| TV apaga a tela | Ajuste as configurações de energia do Windows (ou do dispositivo) para “nunca suspender”. |

---

## Créditos

Dados públicos dos Painéis CONASEMS / Ministério da Saúde. Layout e ícones inspirados na
identidade visual dos painéis, para uso interno das Secretarias de Saúde.
