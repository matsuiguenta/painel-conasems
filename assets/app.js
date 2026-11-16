/* ==========================================================================
   Painel APS, MAC e Vigilância · Bandeirantes/PR
   Lê os dados do servidor local (/api/dados) e, se não houver servidor,
   usa o cache gravado pelo coletor (dados/cache.js). Funciona offline.
   ========================================================================== */

(() => {
  'use strict';

  const DURACAO_SLIDE = 16000;      // ms por tela
  const INTERVALO_RECARGA = 180000; // 3 min

  const $ = (sel, raiz = document) => raiz.querySelector(sel);
  const palco = $('#palco');
  const pontosEl = $('#pontos');
  const barra = $('#barra');

  const nf = new Intl.NumberFormat('pt-BR');
  const nf1 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf2 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const nf0 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });

  let dados = window.__PAINEL_DADOS__ || null;
  let slides = [];
  let indice = 0;
  let pausado = false;
  let temporizador = null;
  let inicioSlide = 0;
  let restante = DURACAO_SLIDE;
  let ultimoGeradoEm = null;
  let usandoCache = false;

  const reduzirMovimento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* --------------------------------------------------------------- utilidades */

  const esc = (texto) =>
    String(texto == null ? '' : texto).replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));

  const ic = (nome, classe = '') => `<svg class="icone ${classe}" aria-hidden="true"><use href="#i-${nome}"></use></svg>`;

  function fmt(valor, tipo = 'int', casas = 0) {
    const v = Number(valor);
    if (!Number.isFinite(v)) return '—';
    switch (tipo) {
      case 'moeda':
        return `${v < 0 ? '-' : ''}R$ ${nf2.format(Math.abs(v))}`;
      case 'moeda0':
        return `${v < 0 ? '-' : ''}R$ ${nf0.format(Math.abs(v))}`;
      case 'pct':
        return `${(casas === 2 ? nf2 : nf1).format(v)}%`;
      case 'dec':
        return (casas === 2 ? nf2 : nf1).format(v);
      default:
        return nf.format(Math.round(v));
    }
  }

  function compacto(valor) {
    const v = Number(valor) || 0;
    if (Math.abs(v) >= 1e6) return `${nf1.format(v / 1e6)} mi`;
    if (Math.abs(v) >= 1e3) return `${nf1.format(v / 1e3)} mil`;
    return nf0.format(v);
  }

  const contador = (valor, tipo = 'int', casas = 0) => {
    if (valor == null || !Number.isFinite(Number(valor))) return '<span class="vazio">—</span>';
    return `<span class="contador" data-contar="${Number(valor)}" data-tipo="${tipo}" data-casas="${casas}">${fmt(valor, tipo, casas)}</span>`;
  };

  const ref = (texto) => (texto ? `<span class="pilula">${ic('relogio')} ${esc(texto)}</span>` : '');

  function cabecalho(titulo, subtitulo, eyebrow = 'Painel CONASEMS', marca = '') {
    return `
      <div class="slide-cabecalho animar" style="--i:0">
        <div>
          <div class="slide-eyebrow">${ic('grafico')} ${esc(eyebrow)}</div>
          <h2 class="slide-titulo">${titulo}</h2>
          ${subtitulo ? `<p class="slide-subtitulo">${subtitulo}</p>` : ''}
        </div>
        ${marca ? `<div class="slide-marca">${ic('relogio')} ${esc(marca)}</div>` : ''}
      </div>`;
  }

  function cartao({ rotulo, valor, unidade = '', meta = '', rodape = '', icone = 'atividade', destaque = 'destaque-azul', indice = 0, barra = '' }) {
    return `
      <article class="cartao ${destaque}${barra ? ' tem-barra' : ''}" style="--i:${indice}">
        <div class="cartao-topo">
          <div class="cartao-icone ${destaque.replace('destaque-', '')}">${ic(icone)}</div>
          <div class="cartao-rotulo">${rotulo}</div>
        </div>
        <div class="cartao-valor">${valor}${unidade ? `<small> ${esc(unidade)}</small>` : ''}</div>
        ${meta ? `<div class="cartao-meta">${meta}</div>` : ''}
        ${barra}
        ${rodape ? `<div class="cartao-rodape">${rodape}</div>` : ''}
        <svg class="cartao-fantasma" aria-hidden="true"><use href="#i-${icone}"></use></svg>
      </article>`;
  }

  function barraComposicao(partes) {
    const total = partes.reduce((soma, parte) => soma + (Number(parte.valor) || 0), 0) || 1;
    return `
      <div class="barra-metrica">
        <div class="trilho-metrica composicao">
          ${partes.map((parte) => `<span style="--cor:${parte.cor};--largura:${(((parte.valor || 0) / total) * 100).toFixed(1)}%"></span>`).join('')}
        </div>
        <div class="legenda-metrica">
          ${partes.map((parte) => `<span><i style="background:${parte.cor}"></i>${esc(parte.nome)} <b>${nf1.format(((parte.valor || 0) / total) * 100)}%</b></span>`).join('')}
        </div>
      </div>`;
  }

  function barraProgresso(pct, cor, rotulo) {
    const seguro = Math.max(0, Math.min(100, Number(pct) || 0));
    return `
      <div class="barra-metrica">
        <div class="trilho-metrica"><span style="--cor:${cor};--largura:${seguro.toFixed(1)}%"></span></div>
        <div class="legenda-metrica">
          <span>${esc(rotulo)}</span><b>${nf2.format(seguro)}%</b>
        </div>
      </div>`;
  }

  const semDados = (oQue) => `
    <div class="cartao cartao-cheio sem-dados">
      ${ic('alerta')}
      <strong>Sem dados de ${esc(oQue)}</strong>
      <span>Os painéis não retornaram esta informação na última coleta.</span>
    </div>`;

  /* --------------------------------------------------------------- gráficos */

  function escalaBonita(maxValor, alvoDivisoes = 4) {
    const bruto = Math.max(maxValor, 1) / alvoDivisoes;
    const expoente = Math.floor(Math.log10(bruto));
    const base = Math.pow(10, expoente);
    const norm = bruto / base;
    let passo = base;
    if (norm > 7) passo = 10 * base;
    else if (norm > 3) passo = 5 * base;
    else if (norm > 1.5) passo = 2 * base;
    const divisoes = Math.max(2, Math.ceil((maxValor * 1.04) / passo));
    return { max: passo * divisoes, passo, divisoes };
  }

  function eixoY(escala, altura, margemTopo, alturaUtil, esquerda, direita) {
    const linhas = [];
    for (let i = 0; i <= escala.divisoes; i += 1) {
      const fracao = i / escala.divisoes;
      const y = margemTopo + alturaUtil - fracao * alturaUtil;
      const valor = escala.max * fracao;
      linhas.push(
        `<line class="grade-linha" x1="${esquerda}" y1="${y.toFixed(1)}" x2="${direita}" y2="${y.toFixed(1)}"></line>` +
        `<text x="${esquerda - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="13">${compacto(valor)}</text>`
      );
    }
    return linhas.join('');
  }

  function graficoColunas({ labels, valores, media = null, cor = '#0559bf', altura = 300, largura = 780, mostrarUltimo = true }) {
    if (!labels || !labels.length) return '<div class="sem-dados">Sem série histórica</div>';
    const L = 68; const R = 14; const T = 26; const B = 40;
    const w = largura - L - R;
    const h = altura - T - B;
    const escala = escalaBonita(Math.max(...valores, 1));
    const max = escala.max;
    const passo = w / valores.length;
    const larguraBarra = Math.min(passo * 0.58, 44);
    const y = (v) => T + h - (v / max) * h;

    const barras = valores.map((v, i) => {
      const alturaBarra = Math.max(2, (v / max) * h);
      const x = L + passo * i + (passo - larguraBarra) / 2;
      const atraso = 0.05 * i;
      let rotulo = '';
      if (mostrarUltimo && i === valores.length - 1) {
        const centro = x + larguraBarra / 2;
        const limite = largura - R - 8;
        const ancora = centro > limite - 34 ? 'end' : 'middle';
        const tx = ancora === 'end' ? limite : centro;
        rotulo = `<text x="${tx.toFixed(1)}" y="${(y(v) - 9).toFixed(1)}" text-anchor="${ancora}" font-size="13" class="valor-rotulo">${compacto(v)}</text>`;
      }
      return `<rect class="barra" x="${x.toFixed(1)}" y="${(T + h - alturaBarra).toFixed(1)}" width="${larguraBarra.toFixed(1)}" height="${alturaBarra.toFixed(1)}" rx="4" fill="${cor}" opacity="${i === valores.length - 1 ? 1 : 0.82}" style="animation-delay:${atraso}s"></rect>${rotulo}`;
    }).join('');

    const rotulos = labels.map((label, i) => {
      const x = L + passo * i + passo / 2;
      return `<text x="${x.toFixed(1)}" y="${altura - 14}" text-anchor="middle" font-size="12">${esc(label)}</text>`;
    }).join('');

    const linhaMedia = Array.isArray(media) && media.length === valores.length
      ? `<polyline class="linha-media" pathLength="1" points="${media.map((v, i) => `${(L + passo * i + passo / 2).toFixed(1)},${y(v).toFixed(1)}`).join(' ')}"></polyline>`
      : '';

    return `
      <svg viewBox="0 0 ${largura} ${altura}" preserveAspectRatio="none" role="img">
        ${eixoY(escala, altura, T, h, L, largura - R)}
        ${barras}
        ${linhaMedia}
        ${rotulos}
        <line x1="${L}" y1="${T + h}" x2="${largura - R}" y2="${T + h}" stroke="#dbe5f3" stroke-width="1"></line>
      </svg>`;
  }

  function graficoEmpilhado({ labels, series, altura = 300, largura = 780 }) {
    if (!labels || !labels.length) return '<div class="sem-dados">Sem série histórica</div>';
    const L = 68; const R = 14; const T = 26; const B = 40;
    const w = largura - L - R;
    const h = altura - T - B;
    const totais = labels.map((_, i) => series.reduce((soma, serie) => soma + (serie.valores[i] || 0), 0));
    const escala = escalaBonita(Math.max(...totais, 1));
    const max = escala.max;
    const passo = w / labels.length;
    const larguraBarra = Math.min(passo * 0.58, 44);

    const barras = labels.map((_, i) => {
      let acumulado = 0;
      const x = L + passo * i + (passo - larguraBarra) / 2;
      return series.map((serie) => {
        const valor = serie.valores[i] || 0;
        const alturaParte = (valor / max) * h;
        const yTopo = T + h - ((acumulado + valor) / max) * h;
        acumulado += valor;
        if (valor <= 0) return '';
        return `<rect class="barra" x="${x.toFixed(1)}" y="${yTopo.toFixed(1)}" width="${larguraBarra.toFixed(1)}" height="${Math.max(1, alturaParte).toFixed(1)}" fill="${serie.cor}" style="animation-delay:${(0.04 * i).toFixed(2)}s"></rect>`;
      }).join('');
    }).join('');

    const rotulos = labels.map((label, i) => {
      const x = L + passo * i + passo / 2;
      return `<text x="${x.toFixed(1)}" y="${altura - 14}" text-anchor="middle" font-size="12">${esc(label)}</text>`;
    }).join('');

    return `
      <svg viewBox="0 0 ${largura} ${altura}" preserveAspectRatio="none" role="img">
        ${eixoY(escala, altura, T, h, L, largura - R)}
        ${barras}
        ${rotulos}
        <line x1="${L}" y1="${T + h}" x2="${largura - R}" y2="${T + h}" stroke="#dbe5f3" stroke-width="1"></line>
      </svg>`;
  }

  function barrasHorizontais(itens, { cor = 'var(--gradiente)', formato = (v) => nf.format(v), maximo = null, classe = '' } = {}) {
    const maior = maximo || Math.max(...itens.map((i) => i.valor), 1);
    return `<div class="barras-horizontais${classe ? ` ${classe}` : ''}">${itens.map((item) => {
      const largura = Math.max(2, Math.min(100, (item.valor / maior) * 100));
      return `
        <div class="barra-horizontal">
          <span class="nome" title="${esc(item.nome)}">${esc(item.nome)}</span>
          <span class="num">${formato(item.valor)}</span>
          <div class="trilho"><div class="preenchimento" style="--cor:${item.cor || cor};--largura:${largura.toFixed(1)}%"></div></div>
        </div>`;
    }).join('')}</div>`;
  }

  function anel({ pct: valor, cor = '#0559bf', titulo, detalhe, equipes = [], destaque = 'destaque-azul', indice = 0 }) {
    const seguro = Math.max(0, Math.min(100, Number(valor) || 0));
    return `
      <article class="anel-cartao ${destaque}" style="--i:${indice};--cor:${cor}">
        <div class="anel-grafico">
          <svg viewBox="0 0 120 120">
            <circle class="trilha" cx="60" cy="60" r="52"></circle>
            <circle class="valor" cx="60" cy="60" r="52" pathLength="100" style="--restante:${(100 - seguro).toFixed(1)}"></circle>
          </svg>
          <div class="centro">
            <strong>${nf2.format(seguro)}%</strong>
            <span>cobertura</span>
          </div>
        </div>
        <div class="anel-titulo">${esc(titulo)}</div>
        ${equipes.length ? `<div class="equipes">${equipes.filter((e) => e.qtd > 0).map((e) => `<span class="equipe">${esc(e.sigla)} <b>${e.qtd}</b></span>`).join('')}</div>` : ''}
        <div class="anel-detalhe">${detalhe}</div>
      </article>`;
  }

  /* --------------------------------------------------------------- telas */

  const aps = () => dados.aps || {};
  const mac = () => dados.mac || {};

  function telaCapa() {
    const a = aps(); const m = mac();
    const c = a.cobertura || {};
    const p = a.producao || {};
    const rep = a.repasses || {};
    const hom = a.homologacao || {};
    const v = a.acsVisitas || {};
    const sia = m.sia || {}; const sih = m.sih || {};

    const chips = [
      { icone: 'escudo', rotulo: 'Equipes homologadas', valor: hom.equipes },
      { icone: 'pessoas', rotulo: 'ACS', valor: c.acsQtd },
      { icone: 'casa', rotulo: 'Visitas domiciliares', valor: p.visitas },
      { icone: 'hospital', rotulo: 'AIH aprovadas', valor: sih.aih },
    ].filter((x) => x.valor != null);

    return `
      <div class="slide-corpo capa">
        <div class="capa-topo animar" style="--i:0">
          <div class="capa-texto">
            <span class="capa-etiqueta">${ic('logo')} Painel de gestão · APS &amp; MAC</span>
            <h2 class="capa-titulo">${esc(dados.municipio?.nome || 'Bandeirantes')}<br><em>saúde em números</em></h2>
          </div>
          <p class="capa-frase">Atenção Primária, Média/Alta Complexidade e Vigilância em Saúde monitoradas a partir dos Painéis CONASEMS, SIAPS, SISMAC e DATASUS. Informações atualizadas automaticamente para acompanhamento da gestão.</p>
        </div>

        <div class="capa-kpis">
          ${cartao({
            rotulo: 'Cobertura potencial da APS',
            valor: contador(c.aps, 'pct', 2),
            meta: `${ic('pessoas')} Potencial de ${fmt(c.potencial)} pessoas`,
            barra: barraProgresso(c.aps, '#0559bf', 'Cobertura alcançada'),
            rodape: `<span>SIAPS · ${esc(c.ref || '—')}</span>`,
            icone: 'escudo', destaque: 'destaque-azul', indice: 1,
          })}
          ${cartao({
            rotulo: 'Cobertura de Saúde Bucal',
            valor: contador(c.sb, 'pct', 2),
            meta: `${ic('dente')} ${(c.equipesSb || []).filter((e) => e.qtd).map((e) => `${e.sigla}: ${e.qtd}`).join(' · ') || 'Sem equipes eSB'}`,
            barra: barraProgresso(c.sb, '#10b981', 'Cobertura alcançada'),
            rodape: `<span>SIAPS · ${esc(c.ref || '—')}</span>`,
            icone: 'dente', destaque: 'destaque-verde', indice: 2,
          })}
          ${cartao({
            rotulo: 'Repasses APS no mês',
            valor: contador(rep.total, 'moeda'),
            meta: `${ic('dinheiro')} Saúde da Família ${fmt(rep.saudeFamilia, 'moeda0')}`,
            barra: barraComposicao([
              { nome: 'Saúde da Família', valor: rep.saudeFamilia, cor: '#0559bf' },
              { nome: 'ACS', valor: rep.acs, cor: '#f59e0b' },
              { nome: 'Saúde Bucal', valor: rep.saudeBucal, cor: '#10b981' },
            ]),
            rodape: `<span>SIAPS · ${esc(rep.ref || '—')}</span>`,
            icone: 'dinheiro', destaque: 'destaque-amarelo', indice: 3,
          })}
          ${cartao({
            rotulo: `Produção MAC aprovada ${sia.ano ? `(${sia.ano})` : ''}`,
            valor: contador(m.total, 'moeda'),
            meta: `${ic('hospital')} ${fmt(sih.aih)} AIH · ${fmt(sia.aprovada)} procedimentos`,
            barra: barraComposicao([
              { nome: 'SIA ambulatorial', valor: sia.valorAprovado, cor: '#0559bf' },
              { nome: 'SIH hospitalar', valor: sih.valor, cor: '#7c3aed' },
            ]),
            rodape: `<span>DATASUS · SIA + SIH</span>`,
            icone: 'hospital', destaque: 'destaque-roxo', indice: 4,
          })}
        </div>

        <div class="capa-chips animar" style="--i:5">
          ${chips.map((x) => `<span class="chip">${ic(x.icone)} ${esc(x.rotulo)} <b>${fmt(x.valor)}</b></span>`).join('')}
        </div>
      </div>`;
  }

  function telaCobertura() {
    const c = aps().cobertura;
    if (!c) return semDados('cobertura da APS');
    const totalEquipes = (c.equipes || []).reduce((soma, e) => soma + e.qtd, 0);
    const notaExcesso = [c.aps, c.sb, c.acs].some((x) => x > 100)
      ? `<div class="nota">${ic('alerta')} Cobertura potencial acima de 100% conforme regras da nota técnica do Ministério da Saúde.</div>` : '';

    return `
      ${cabecalho('Cobertura da Atenção Primária', 'Equipes credenciadas, potencial de cobertura e Saúde Bucal no município.', 'APS · Cobertura', `SIAPS · ${c.ref || '—'}`)}
      <div class="slide-corpo" style="grid-template-rows:minmax(0,1fr) auto auto">
        <div class="aneis animar" style="--i:1">
          ${anel({
            pct: c.aps, cor: '#0559bf', titulo: 'Cobertura da APS',
            equipes: c.equipes || [],
            detalhe: `Potencial de <b>${fmt(c.potencial)}</b> pessoas<br>${totalEquipes} equipes credenciadas`,
            destaque: 'destaque-azul', indice: 0,
          })}
          ${anel({
            pct: c.sb, cor: '#10b981', titulo: 'Saúde Bucal',
            equipes: c.equipesSb || [],
            detalhe: `Potencial de <b>${fmt(c.potencialSb)}</b> pessoas<br>${(c.equipesSb || []).filter((e) => e.qtd).reduce((s, e) => s + e.qtd, 0)} equipes de Saúde Bucal`,
            destaque: 'destaque-verde', indice: 1,
          })}
          ${anel({
            pct: c.acs, cor: '#f59e0b', titulo: 'Agentes Comunitários',
            equipes: [{ sigla: 'ACS', qtd: c.acsQtd }],
            detalhe: `Potencial de <b>${fmt(c.potencialAcs)}</b> pessoas<br>${fmt(c.acsQtd)} agentes comunitários`,
            destaque: 'destaque-amarelo', indice: 2,
          })}
        </div>
        <div class="linha animar" style="--i:2">
          <div class="destaque-linha" style="flex:1">
            <span class="rotulo">Eq. homologadas</span>
            <span class="valor">${contador(aps().homologacao?.equipes)}</span>
          </div>
          <div class="destaque-linha" style="flex:1">
            <span class="rotulo">Eq. sem envio de produção</span>
            <span class="valor">${contador(aps().ausencia?.total)}</span>
          </div>
          <div class="destaque-linha" style="flex:1">
            <span class="rotulo">Solicitações em aberto</span>
            <span class="valor">${contador(aps().solicitacoes?.solicitadas)}</span>
          </div>
        </div>
        ${notaExcesso}
      </div>`;
  }

  function telaProducaoAps() {
    const p = aps().producao;
    if (!p) return semDados('produção da APS');
    const itens = [
      { rotulo: 'Consultas médicas', valor: p.medico, hab: p.porHab?.medico, icone: 'coracao', destaque: 'destaque-azul' },
      { rotulo: 'Consultas de enfermagem', valor: p.enfermeiro, hab: p.porHab?.enfermeiro, icone: 'atividade', destaque: 'destaque-verde' },
      { rotulo: 'Atendimentos odontológicos', valor: p.odonto, hab: p.porHab?.odonto, icone: 'dente', destaque: 'destaque-amarelo' },
      { rotulo: 'Procedimentos realizados', valor: p.procedimentos, hab: p.porHab?.procedimentos, icone: 'prancheta', destaque: 'destaque-roxo' },
      { rotulo: 'Visitas domiciliares', valor: p.visitas, hab: p.porHab?.visitas, icone: 'casa', destaque: 'destaque-vermelho' },
    ];

    const cores = {
      'destaque-azul': '#0559bf',
      'destaque-verde': '#10b981',
      'destaque-amarelo': '#f59e0b',
      'destaque-roxo': '#7c3aed',
      'destaque-vermelho': '#ef4444',
    };
    const porHabitante = [...itens]
      .sort((a, b) => (b.hab || 0) - (a.hab || 0))
      .map((item) => ({
        nome: item.rotulo.replace('Consultas de ', 'Consultas ').replace('Atendimentos ', 'Atend. '),
        valor: item.hab || 0,
        cor: cores[item.destaque],
      }));

    return `
      ${cabecalho('Produção da Atenção Primária', 'Atendimentos individuais, procedimentos e visitas realizados pelas equipes.', 'APS · Produção', `SIAPS · ${p.ref || '—'}`)}
      <div class="slide-corpo" style="grid-template-rows:auto minmax(0,1fr) auto">
        <div class="grade-5 animar" style="--i:1">
          ${itens.map((item, i) => cartao({
            rotulo: item.rotulo,
            valor: contador(item.valor),
            unidade: 'no mês',
            meta: `${ic('tendencia')} ${nf2.format(item.hab || 0)} por habitante`,
            rodape: `<span>Competência ${esc(p.ref || '—')}</span>`,
            icone: item.icone, destaque: item.destaque, indice: i,
          })).join('')}
        </div>

        <article class="cartao cartao-cheio destaque-verde animar" style="--i:2">
          <div class="cartao-topo">
            <div class="cartao-icone verde">${ic('tendencia')}</div>
            <div class="cartao-rotulo">Produção por habitante no mês — comparação entre os tipos de atendimento</div>
          </div>
          ${barrasHorizontais(porHabitante, {
            formato: (v) => `${nf2.format(v)} por hab.`,
            maximo: Math.max(...porHabitante.map((x) => x.valor), 0.01),
          })}
          <div class="nota" style="margin-top:auto">${ic('documento')} Indicadores calculados pelo SIAPS a partir da produção aprovada e da população estimada do município.</div>
        </article>

        <div class="linha animar" style="--i:3">
          <div class="destaque-linha" style="flex:1">
            <span class="rotulo">${ic('pessoas')} Equipes com ausência de envio</span>
            <span class="valor">${contador(aps().ausencia?.total)}</span>
          </div>
          <div class="destaque-linha" style="flex:1">
            <span class="rotulo">${ic('check')} Equipes homologadas</span>
            <span class="valor">${contador(aps().homologacao?.equipes)}</span>
          </div>
          <div class="destaque-linha" style="flex:1">
            <span class="rotulo">${ic('hospital')} Estabelecimentos homologados</span>
            <span class="valor">${contador(aps().homologacao?.estabelecimentos)}</span>
          </div>
          <div class="destaque-linha" style="flex:1">
            <span class="rotulo">${ic('relogio')} Homologação</span>
            <span class="valor" style="font-size:.85rem">${esc(aps().homologacao?.ref || '—')}</span>
          </div>
        </div>
      </div>`;
  }

  function telaFinanciamentoAps() {
    const r = aps().repasses;
    if (!r) return semDados('financiamento da APS');
    const partes = [
      { nome: 'Saúde da Família', valor: r.saudeFamilia, cor: '#0559bf' },
      { nome: 'Agentes Comunitários', valor: r.acs, cor: '#f59e0b' },
      { nome: 'Saúde Bucal', valor: r.saudeBucal, cor: '#10b981' },
    ];
    const total = r.total || partes.reduce((s, p) => s + p.valor, 0);
    const popReferencia = aps().cobertura?.potencial || 0;
    const porHabitante = popReferencia ? total / popReferencia : 0;
    const historico = r.historico?.valores || [];
    const mediaPeriodo = historico.length ? historico.reduce((soma, v) => soma + v, 0) / historico.length : 0;
    const maiorRepasse = historico.length ? Math.max(...historico) : 0;

    return `
      ${cabecalho('Financiamento da APS', 'Repasses mensais, composição por programa e média móvel de 12 meses.', 'APS · Financiamento', `SIAPS · ${r.ref || '—'}`)}
      <div class="slide-corpo grade-2-1">
        <article class="cartao cartao-cheio destaque-azul animar" style="--i:1">
          <div class="cartao-topo">
            <div class="cartao-icone">${ic('grafico')}</div>
            <div class="cartao-rotulo">Histórico mensal de repasses &amp; média móvel (12m)</div>
          </div>
          <div class="grafico">
            ${graficoColunas({
              labels: r.historico?.labels || [],
              valores: r.historico?.valores || [],
              media: r.historico?.mediaMovel || null,
              cor: '#0559bf', altura: 300,
            })}
          </div>
          <div class="legenda">
            <span><i style="--cor:#0559bf"></i>Repasse mensal</span>
            <span><i style="--cor:#f59e0b"></i>Média móvel 12 meses</span>
          </div>
        </article>

        <div class="coluna">
          <article class="cartao destaque-amarelo animar" style="--i:2">
            <div class="cartao-topo">
              <div class="cartao-icone amarelo">${ic('dinheiro')}</div>
              <div class="cartao-rotulo">Total de repasses APS no mês</div>
            </div>
            <div class="cartao-valor">${contador(total, 'moeda')}</div>
            <div class="cartao-meta">${ic('relogio')} Competência ${esc(r.ref || '—')}</div>
          </article>

          <article class="cartao cartao-cheio animar" style="--i:3">
            <div class="cartao-rotulo">${ic('grafico')} Detalhamento por programa</div>
            ${barrasHorizontais(partes, { formato: (v) => fmt(v, 'moeda0') })}
            <table class="tabela" style="margin-top:.5rem">
              <tr><td>Repasse por habitante</td><td><b>${fmt(porHabitante, 'moeda')}</b></td></tr>
              <tr><td>Média mensal (12 meses)</td><td><b>${fmt(mediaPeriodo, 'moeda0')}</b></td></tr>
              <tr><td>Maior repasse do período</td><td><b>${fmt(maiorRepasse, 'moeda0')}</b></td></tr>
              <tr><td>População de referência</td><td><b>${fmt(popReferencia)} pessoas</b></td></tr>
            </table>
            <div class="legenda" style="margin-top:auto">
              <span>${nf1.format(total ? (partes[0].valor / total) * 100 : 0)}% Saúde da Família</span>
              <span>${nf1.format(total ? (partes[2].valor / total) * 100 : 0)}% Saúde Bucal</span>
            </div>
          </article>
        </div>
      </div>`;
  }

  function telaVisitasAcs() {
    const v = aps().acsVisitas;
    if (!v) return semDados('visitas dos ACS');
    const hist = v.historico || [];
    const series = [
      { nome: 'Realizadas', valores: hist.map((h) => h.realizadas), cor: '#10b981' },
      { nome: 'Ausentes', valores: hist.map((h) => h.ausentes), cor: '#f59e0b' },
      { nome: 'Recusadas', valores: hist.map((h) => h.recusadas), cor: '#ef4444' },
    ];
    const pctRealizadas = v.total ? (v.realizadas / v.total) * 100 : 0;

    return `
      ${cabecalho('Visitas domiciliares dos ACS', 'Produção mensal das visitas e aproveitamento da equipe de Agentes Comunitários de Saúde.', 'APS · ACS', `SIAPS · ${v.ref || '—'}`)}
      <div class="slide-corpo grade-3-2">
        <article class="cartao cartao-cheio destaque-verde animar" style="--i:1">
          <div class="cartao-topo">
            <div class="cartao-icone verde">${ic('casa')}</div>
            <div class="cartao-rotulo">Visitas por situação — últimos 12 meses</div>
          </div>
          <div class="grafico">${graficoEmpilhado({ labels: hist.map((h) => h.ref), series, altura: 300 })}</div>
          <div class="legenda">
            <span><i style="--cor:#10b981"></i>Realizadas</span>
            <span><i style="--cor:#f59e0b"></i>Ausentes</span>
            <span><i style="--cor:#ef4444"></i>Recusadas</span>
          </div>
        </article>

        <div class="coluna">
          <article class="cartao destaque-verde animar" style="--i:2">
            <div class="cartao-topo">
              <div class="cartao-icone verde">${ic('check')}</div>
              <div class="cartao-rotulo">Visitas realizadas</div>
            </div>
            <div class="cartao-valor">${contador(v.realizadas)} <small>de ${fmt(v.total)}</small></div>
            <div class="cartao-meta">${nf1.format(pctRealizadas)}% do total · ${contador(v.ausentes)} ausentes · ${fmt(v.recusadas)} recusadas</div>
            ${barraProgresso(pctRealizadas, '#10b981', 'Aproveitamento das visitas')}
          </article>

          <article class="cartao cartao-cheio destaque-azul animar" style="--i:3">
            <div class="cartao-topo">
              <div class="cartao-icone azul">${ic('pessoas')}</div>
              <div class="cartao-rotulo">Equipe de Agentes Comunitários de Saúde</div>
            </div>
            <div class="grade-2" style="margin:.1rem 0">
              <div>
                <div class="cartao-valor">${contador(v.qtdAcs)}</div>
                <div class="cartao-meta">ACS credenciados no município</div>
              </div>
              <div>
                <div class="cartao-valor">${contador(v.mediaMes)}<small>/mês</small></div>
                <div class="cartao-meta">${nf1.format(v.mediaDia)} visitas por ACS em dia útil</div>
              </div>
            </div>
            ${barraComposicao([
              { nome: 'Realizadas', valor: v.realizadas, cor: '#10b981' },
              { nome: 'Ausentes', valor: v.ausentes, cor: '#f59e0b' },
              { nome: 'Recusadas', valor: v.recusadas, cor: '#ef4444' },
            ])}
            <table class="tabela" style="margin-top:.5rem">
              <tr><td>Visitas previstas no mês</td><td><b>${fmt(v.total)}</b></td></tr>
              <tr><td>Visitas realizadas</td><td><b>${fmt(v.realizadas)}</b></td></tr>
              <tr><td>Ausências registradas</td><td><b>${fmt(v.ausentes)}</b></td></tr>
              <tr><td>Recusas registradas</td><td><b>${fmt(v.recusadas)}</b></td></tr>
            </table>
            <div class="nota" style="margin-top:auto">${ic('documento')} Aproveitamento de ${nf1.format(pctRealizadas)}% sobre as visitas previstas no período.</div>
          </article>
        </div>
      </div>`;
  }

  function telaCredenciamento() {
    const s = aps().solicitacoes;
    const h = aps().homologacao;
    const cof = aps().cofinanciamento || [];
    if (!s && !h && !cof.length) return semDados('credenciamento e cofinanciamento');

    const cores = { regular: '#ef4444', suficiente: '#f59e0b', bom: '#3b82f6', otimo: '#10b981' };

    return `
      ${cabecalho('Credenciamento e cofinanciamento', 'Situação das solicitações de equipes e desempenho nos indicadores de cofinanciamento da APS.', 'APS · Gestão', s?.ref ? `SIAPS · ${s.ref}` : 'SIAPS')}
      <div class="slide-corpo">
        <div class="grade-4 animar" style="--i:1">
          ${cartao({ rotulo: 'Equipes homologadas', valor: contador(h?.equipes), unidade: 'equipes', meta: `${ic('check')} ${esc(h?.ref || '')}`, icone: 'escudo', destaque: 'destaque-azul', indice: 0 })}
          ${cartao({ rotulo: 'Estabelecimentos homologados', valor: contador(h?.estabelecimentos), unidade: 'local(is)', meta: `${ic('hospital')} ${esc(h?.ref || '')}`, icone: 'hospital', destaque: 'destaque-verde', indice: 1 })}
          ${cartao({ rotulo: 'Solicitações credenciadas', valor: contador(s?.credenciadas), unidade: 'de ' + fmt(s?.total || 0), meta: `${ic('check')} Processos concluídos`, icone: 'documento', destaque: 'destaque-amarelo', indice: 2 })}
          ${cartao({ rotulo: 'Solicitações em andamento', valor: contador(s?.solicitadas), unidade: 'solicitações', meta: `${ic('relogio')} Aguardando análise`, icone: 'prancheta', destaque: 'destaque-vermelho', indice: 3 })}
        </div>

        <article class="cartao cartao-cheio animar" style="--i:2">
          <div class="cartao-topo">
            <div class="cartao-icone roxo">${ic('alvo')}</div>
            <div class="cartao-rotulo">Desempenho no cofinanciamento — CVAT (Dimensão Acompanhamento)</div>
          </div>
          ${cof.length ? cof.map((q) => `
            <div class="barra-horizontal" style="grid-template-columns:1fr auto;margin-top:.5rem">
              <span class="nome">${esc(q.quadrimestre)}</span>
              <span class="num">${nf1.format(q.total ? (q.otimo / q.total) * 100 : 0)}% ótimo</span>
              <div class="trilho" style="display:flex;height:.7rem;gap:2px;background:transparent">
                ${['regular', 'suficiente', 'bom', 'otimo'].map((chave) => q[chave] ? `<div class="preenchimento" style="--cor:${cores[chave]};--largura:${((q[chave] / q.total) * 100).toFixed(1)}%;border-radius:.2rem"></div>` : '').join('')}
              </div>
            </div>`).join('') : '<div class="sem-dados">Sem dados de cofinanciamento</div>'}
          <div class="legenda" style="margin-top:auto">
            <span><i style="--cor:#ef4444"></i>Regular</span>
            <span><i style="--cor:#f59e0b"></i>Suficiente</span>
            <span><i style="--cor:#3b82f6"></i>Bom</span>
            <span><i style="--cor:#10b981"></i>Ótimo</span>
          </div>
        </article>
      </div>`;
  }

  function telaMacTeto() {
    const t = mac().teto;
    const m = mac();
    if (!t) return semDados('teto MAC');
    return `
      ${cabecalho('Teto MAC e produção', 'Limites financeiros da Média e Alta Complexidade e produção aprovada no último ano fechado.', 'MAC · Teto', t.periodo ? `SISMAC · ${t.periodo}` : 'SISMAC')}
      <div class="slide-corpo">
        <div class="grade-3 animar" style="--i:1">
          ${cartao({ rotulo: 'Teto MAC — sem incentivos', valor: contador(t.semIncentivos, 'moeda'), unidade: 'ano', meta: `${ic('dinheiro')} Mensal ${fmt(t.mensalSemIncentivos, 'moeda')}`, barra: barraProgresso(t.total ? (t.semIncentivos / t.total) * 100 : 0, '#0559bf', 'Participação no teto total'), icone: 'hospital', destaque: 'destaque-azul', indice: 0 })}
          ${cartao({ rotulo: 'Incentivos adicionais', valor: contador(t.incentivos, 'moeda'), unidade: 'ano', meta: `${ic('dinheiro')} Mensal ${fmt(t.mensalIncentivos, 'moeda')}`, barra: barraProgresso(t.total ? (t.incentivos / t.total) * 100 : 0, '#10b981', 'Participação no teto total'), icone: 'tendencia', destaque: 'destaque-verde', indice: 1 })}
          ${cartao({ rotulo: 'Teto MAC total (com incentivos)', valor: contador(t.total, 'moeda'), unidade: 'ano', meta: `${ic('dinheiro')} Mensal ${fmt(t.mensalTotal, 'moeda')}`, barra: barraProgresso(100, '#7c3aed', 'Teto anual completo'), icone: 'alvo', destaque: 'destaque-roxo', indice: 2 })}
        </div>

        <div class="grade-2 animar" style="--i:2;flex:1">
          <article class="cartao cartao-cheio destaque-amarelo">
            <div class="cartao-topo">
              <div class="cartao-icone amarelo">${ic('atividade')}</div>
              <div class="cartao-rotulo">Produção MAC aprovada ${esc(m.sia?.ano || '')} (SIA + SIH)</div>
            </div>
            <div class="cartao-valor" style="font-size:clamp(1.9rem,3vw,3.4rem)">${contador(m.total, 'moeda')}</div>
            <div class="cartao-meta">SIA ${fmt(m.sia?.valorAprovado, 'moeda')} + SIH ${fmt(m.sih?.valor, 'moeda')}</div>
            ${barraComposicao([
              { nome: 'SIA ambulatorial', valor: m.sia?.valorAprovado, cor: '#0559bf' },
              { nome: 'SIH hospitalar', valor: m.sih?.valor, cor: '#7c3aed' },
            ])}
            <div class="destaque-linha" style="margin-top:auto">
              <span class="rotulo">Diferença teto × produção (com incentivos)</span>
              <span class="valor" style="color:#b91c1c">${fmt(m.diferenca?.comIncentivos, 'moeda')}</span>
            </div>
          </article>

          <article class="cartao cartao-cheio destaque-azul">
            <div class="cartao-topo">
              <div class="cartao-icone">${ic('prancheta')}</div>
              <div class="cartao-rotulo">Leitura do indicador</div>
            </div>
            <p style="font-size:.78rem;line-height:1.55;color:#475569;margin:.2rem 0">
              O teto MAC representa o limite anual sob gestão municipal. A produção aprovada considera todos os
              estabelecimentos localizados no território, inclusive unidades de gestão estadual — por isso o valor
              produzido é superior ao teto municipal.
            </p>
            <table class="tabela" style="margin:.2rem 0">
              <tr><td>Teto mensal sem incentivos</td><td><b>${fmt(t.mensalSemIncentivos, 'moeda')}</b></td></tr>
              <tr><td>Incentivos mensais</td><td><b>${fmt(t.mensalIncentivos, 'moeda')}</b></td></tr>
              <tr><td>Teto mensal total</td><td><b>${fmt(t.mensalTotal, 'moeda')}</b></td></tr>
            </table>
            <div class="linha" style="gap:.6rem;margin-top:auto">
              <div class="destaque-linha" style="flex:1">
                <span class="rotulo">Diferença sem incentivos</span>
                <span class="valor">${fmt(m.diferenca?.semIncentivos, 'moeda')}</span>
              </div>
            </div>
            <div class="nota">${ic('alerta')} Fonte: SISMAC (${esc(t.periodo || '12 meses')}) e DATASUS (${esc(m.sia?.ano || '—')}).</div>
          </article>
        </div>
      </div>`;
  }

  function telaSiaSih() {
    const m = mac();
    const sia = m.sia || {};
    const sih = m.sih || {};
    const mensal = m.mensal || [];
    if (!sia.ano && !sih.ano) return semDados('produção ambulatorial e hospitalar');

    return `
      ${cabecalho('Produção ambulatorial e hospitalar', 'SIA e SIH: volume aprovado, valores e glosas da Média e Alta Complexidade.', 'MAC · Produção', `DATASUS · ${sia.ano || ''}`)}
      <div class="slide-corpo">
        <div class="grade-2 animar" style="--i:1">
          ${cartao({ rotulo: 'SIA · procedimentos aprovados', valor: contador(sia.aprovada), unidade: `de ${fmt(sia.apresentada)} apresentados`, meta: `${ic('tendencia')} ${nf1.format(sia.pctQtdAprovada || 0)}% de aprovação · ${fmt(sia.glosa, 'moeda')} de glosa`, icone: 'prancheta', destaque: 'destaque-azul', indice: 0 })}
          ${cartao({ rotulo: 'SIH · AIH aprovadas', valor: contador(sih.aih), unidade: 'internações', meta: `${ic('dinheiro')} ${fmt(sih.valor, 'moeda')} · média ${fmt(sih.mediaAih, 'moeda')} por AIH`, icone: 'hospital', destaque: 'destaque-roxo', indice: 1 })}
        </div>

        <article class="cartao cartao-cheio destaque-verde animar" style="--i:2">
          <div class="cartao-topo">
            <div class="cartao-icone verde">${ic('grafico')}</div>
            <div class="cartao-rotulo">Evolução mensal do valor aprovado — SIA + SIH</div>
          </div>
          <div class="grafico">${graficoEmpilhado({
            labels: mensal.map((x) => x.ref),
            series: [
              { nome: 'SIA', valores: mensal.map((x) => x.sia), cor: '#0559bf' },
              { nome: 'SIH', valores: mensal.map((x) => x.sih), cor: '#7c3aed' },
            ],
            altura: 280,
          })}</div>
          <div class="legenda">
            <span><i style="--cor:#0559bf"></i>Ambulatorial (SIA)</span>
            <span><i style="--cor:#7c3aed"></i>Hospitalar (SIH)</span>
            <span style="margin-left:auto">Último mês: ${esc(mensal.at(-1)?.ref || '—')} · ${fmt(mensal.at(-1)?.total, 'moeda')}</span>
          </div>
        </article>
      </div>`;
  }

  function telaOncologiaMental() {
    const o = mac().oncologia || {};
    const sm = mac().saudeMental || {};
    const top = o.casosDetalhe?.top || [];
    if (!o.ano && !sm.ano) return semDados('oncologia e saúde mental');

    return `
      ${cabecalho('Oncologia e saúde mental', 'Tempo de início do tratamento oncológico e produção psicossocial (SIA/SIH).', 'MAC · Linhas de cuidado', o.ano ? `Painel ONCO · ${o.ano}` : 'DATASUS')}
      <div class="slide-corpo grade-2">
        <article class="cartao cartao-cheio destaque-vermelho animar" style="--i:1">
          <div class="cartao-topo">
            <div class="cartao-icone vermelho">${ic('alvo')}</div>
            <div class="cartao-rotulo">Oncologia — tempo até o tratamento (Lei 60 dias)</div>
          </div>
          <div class="linha" style="align-items:flex-end;gap:1.2rem;margin:.3rem 0">
            <div>
              <div class="numero-grande">${contador(o.tempoMedio, 'dec', 1)}</div>
              <div class="cartao-meta">dias em média</div>
            </div>
            <div>
              <div class="numero-grande" style="color:#047857">${contador(o.pct60, 'pct', 1)}</div>
              <div class="cartao-meta">iniciados em até 60 dias</div>
            </div>
            <div style="margin-left:auto;text-align:right">
              <div class="numero-grande">${contador(o.tratados)}<small style="font-size:.45em">/${fmt(o.casos)}</small></div>
              <div class="cartao-meta">casos tratados · ${fmt(o.mais60)} acima de 60 dias</div>
            </div>
          </div>
          <div class="cartao-rotulo" style="margin-top:.2rem">${ic('grafico')} Diagnósticos mais frequentes ${esc(o.casosDetalhe?.ano || '')}</div>
          ${barrasHorizontais(top.slice(0, 5).map((c) => ({ nome: `${c.cid} · ${c.desc}`, valor: c.casos })), { formato: (v) => `${v} caso${v === 1 ? '' : 's'}`, cor: '#ef4444' })}
          <div class="nota" style="margin-top:auto">${ic('documento')} Casos novos registrados no Painel ONCO · ${esc(o.casosDetalhe?.total || 0)} casos no ano · tempo medido até o 1º tratamento.</div>
        </article>

        <article class="cartao cartao-cheio destaque-roxo animar" style="--i:2">
          <div class="cartao-topo">
            <div class="cartao-icone roxo">${ic('coracao')}</div>
            <div class="cartao-rotulo">Saúde mental — produção psicossocial (${esc(sm.ano || '—')})</div>
          </div>
          <div class="grade-2" style="margin:.2rem 0">
            <div>
              <div class="numero-grande">${contador(sm.totalSia)}</div>
              <div class="cartao-meta">atendimentos ambulatoriais (SIA)</div>
            </div>
            <div>
              <div class="numero-grande">${contador(sm.totalSih)}</div>
              <div class="cartao-meta">internações (AIH) · ${fmt(sm.sih?.[0]?.valor, 'moeda')}</div>
            </div>
          </div>
          <div class="cartao-rotulo">${ic('grafico')} CID-10 mais atendidos</div>
          ${barrasHorizontais((sm.topCids || []).map((c) => ({ nome: `${c.cid} · ${c.desc}`, valor: c.total })), { formato: (v) => fmt(v), cor: '#7c3aed' })}
          <div class="nota" style="margin-top:auto">${ic('hospital')} ${esc(sm.sia?.[0]?.nome || '—')} · ${esc(sm.sih?.[0]?.nome || '—')}</div>
        </article>
      </div>`;
  }

  function telaVigilancia() {
    const v = dados.vigilancia || {};
    const mort = v.mortalidade || {};
    if (!mort.geral && !v.dengue && !v.internacoes) return semDados('vigilância em saúde');

    const anoAtual = new Date().getFullYear();
    const porAno = (lista) => [...(lista || [])].sort((a, b) => Number(a.ano) - Number(b.ano));
    const fechado = (lista) => {
      const serie = porAno(lista);
      const anteriores = serie.filter((x) => Number(x.ano) < anoAtual);
      return (anteriores.length ? anteriores : serie).at(-1) || null;
    };
    const anteriorA = (lista, alvo) => {
      if (!alvo) return null;
      const serie = porAno(lista).filter((x) => Number(x.ano) < Number(alvo.ano));
      return serie.at(-1) || null;
    };
    const variacao = (atual, base) => {
      const b = Number(base) || 0;
      if (!b) return '';
      const pct = ((Number(atual) - b) / b) * 100;
      return `${pct > 0 ? '+' : ''}${nf1.format(pct)}%`;
    };
    const comparativo = (atual, ant, campo = 'obitos') => (ant
      ? `${ic('tendencia')} ${ant.ano}: ${fmt(ant[campo], campo === 'valor' ? 'dec' : 'int', 1)} · ${variacao(atual, ant[campo])}`
      : '');

    const geral = fechado(mort.geral);
    const geralAnt = anteriorA(mort.geral, geral);
    const infantil = fechado(mort.infantil);
    const infantilAnt = anteriorA(mort.infantil, infantil);
    const tb = fechado(v.tuberculose);
    const tbAnt = anteriorA(v.tuberculose, tb);
    const dengue = porAno(v.dengue).at(-1);
    const dengueAnt = anteriorA(v.dengue, dengue);

    const internacoes = v.internacoes || {};
    const capitulos = internacoes.capitulos || [];
    const topCapitulos = capitulos.slice(0, 6);
    const externas = capitulos.find((c) => /^XIX/.test(c.capitulo)) || null;
    const limpar = (texto) => String(texto || '').replace(/^[IVXLC]+\.\s*/, '');

    const vacinacao = v.vacinacao || {};
    const vacinas = vacinacao.vacinas || [];
    const corVacina = (pct) => (pct >= 95 ? '#10b981' : pct >= 85 ? '#0559bf' : pct >= 70 ? '#eab308' : '#ef4444');
    const mediaVacinal = vacinas.length
      ? vacinas.reduce((soma, item) => soma + item.cobertura, 0) / vacinas.length
      : null;

    const srag = v.srag || {};
    const nascidos = v.nascidos || {};

    return `
      ${cabecalho('Vigilância em saúde', 'Mortalidade, agravos de notificação, cobertura vacinal e internações hospitalares no município.', 'VIGILÂNCIA · Indicadores', `DATASUS · ${anoAtual}`)}
      <div class="slide-corpo" style="grid-template-rows:auto minmax(0,1fr) auto">
        <div class="grade-4 animar" style="--i:1">
          ${cartao({
            rotulo: `Mortalidade geral — ${geral?.ano || '—'}`,
            valor: contador(geral?.obitos ?? 0),
            unidade: 'óbitos',
            meta: comparativo(geral?.obitos ?? 0, geralAnt),
            icone: 'coracao', destaque: 'destaque-azul', indice: 0,
          })}
          ${cartao({
            rotulo: `Mortalidade infantil — ${infantil?.ano || '—'}`,
            valor: contador(infantil?.obitos ?? 0),
            unidade: 'óbitos',
            meta: comparativo(infantil?.obitos ?? 0, infantilAnt),
            icone: 'bebe', destaque: 'destaque-verde', indice: 1,
          })}
          ${cartao({
            rotulo: `Tuberculose — ${tb?.ano || '—'}`,
            valor: contador(tb?.valor ?? 0, 'dec', 1),
            unidade: '/100 mil',
            meta: comparativo(tb?.valor ?? 0, tbAnt, 'valor'),
            icone: 'pulmao', destaque: 'destaque-vermelho', indice: 2,
          })}
          ${cartao({
            rotulo: `Dengue — ${dengue?.ano || '—'}`,
            valor: contador(dengue?.casos ?? 0),
            unidade: 'casos',
            meta: dengueAnt ? `${ic('tendencia')} ${dengueAnt.ano}: ${fmt(dengueAnt.casos)} casos · ${variacao(dengue.casos, dengueAnt.casos)}` : '',
            icone: 'virus', destaque: 'destaque-amarelo', indice: 3,
          })}
        </div>

        <div class="grade-2 animar" style="--i:2;min-height:0">
          <article class="cartao cartao-cheio destaque-verde">
            <div class="cartao-topo">
              <div class="cartao-icone verde">${ic('hospital')}</div>
              <div class="cartao-rotulo">Internações por capítulo CID-10 · ${esc(internacoes.ano || '—')}</div>
              <span class="pilula" style="margin-left:auto">${ic('banco')} ${fmt(internacoes.total ?? 0)} no ano</span>
            </div>
            ${topCapitulos.length
              ? barrasHorizontais(
                topCapitulos.map((c) => ({ nome: limpar(c.capitulo), valor: c.internacoes })),
                { formato: (x) => fmt(x), cor: '#10b981', classe: 'compacto' },
              )
              : '<div class="sem-dados">Sem dados de internações</div>'}
            <div class="nota" style="margin-top:auto">${ic('banco')} SIH/DATASUS · local de internação · ${esc(internacoes.ano || '—')} (ano em curso).</div>
          </article>

          <article class="cartao cartao-cheio destaque-roxo">
            <div class="cartao-topo">
              <div class="cartao-icone roxo">${ic('escudo')}</div>
              <div class="cartao-rotulo">Cobertura vacinal · ${esc(vacinacao.ano || '—')}</div>
              <span class="pilula ${mediaVacinal >= 95 ? 'verde' : 'amarela'}" style="margin-left:auto">${ic('alvo')} meta ${nf0.format(vacinacao.meta || 95)}%</span>
            </div>
            ${vacinas.length
              ? barrasHorizontais(
                vacinas.slice(0, 6).map((item) => ({ nome: item.nome, valor: item.cobertura, cor: corVacina(item.cobertura) })),
                { formato: (x) => `${nf1.format(x)}%`, maximo: 100, classe: 'compacto' },
              )
              : '<div class="sem-dados">Sem dados de vacinação</div>'}
            <div class="nota" style="margin-top:auto">${ic('check')} Média das vacinas: <b>${mediaVacinal == null ? '—' : `${nf1.format(mediaVacinal)}%`}</b> · SI-PNI/DATASUS.</div>
          </article>
        </div>

        <div class="grade-4 animar" style="--i:3">
          ${cartao({
            rotulo: 'SRAG',
            valor: contador(srag.total ?? 0),
            unidade: `casos · ${srag.ano || '—'}`,
            meta: `${ic('atividade')} ${nf1.format(srag.incidencia || 0)} casos por 100 mil hab.`,
            icone: 'atividade', destaque: 'destaque-vermelho', indice: 0,
          })}
          ${cartao({
            rotulo: 'Nascidos vivos',
            valor: contador(nascidos.total ?? 0),
            unidade: `· ${nascidos.ano || '—'}`,
            meta: `${ic('pessoas')} ${nf1.format(nascidos.total ? (nascidos.cesareo / nascidos.total) * 100 : 0)}% por cesariana`,
            icone: 'pessoas', destaque: 'destaque-azul', indice: 1,
          })}
          ${cartao({
            rotulo: `Hanseníase — ${fechado(v.hanseniase)?.ano || '—'}`,
            valor: contador(fechado(v.hanseniase)?.valor ?? 0, 'dec', 1),
            unidade: '/100 mil',
            meta: `${ic('escudo')} ${fechado(v.hanseniase)?.valor ? 'Coeficiente de detecção' : 'Sem casos no período'}`,
            icone: 'escudo', destaque: 'destaque-amarelo', indice: 2,
          })}
          ${cartao({
            rotulo: 'Internações por causas externas',
            valor: contador(externas?.internacoes ?? 0),
            unidade: `· ${internacoes.ano || '—'}`,
            meta: `${ic('alerta')} ${internacoes.total ? nf1.format(((externas?.internacoes || 0) / internacoes.total) * 100) : '0,0'}% do total de internações`,
            icone: 'alerta', destaque: 'destaque-verde', indice: 3,
          })}
        </div>
      </div>`;
  }

  /* --------------------------------------------------------------- montagem */

  function montarTelas() {
    const definicoes = [
      { id: 'capa', montar: telaCapa },
      { id: 'cobertura', montar: telaCobertura },
      { id: 'producao-aps', montar: telaProducaoAps },
      { id: 'financiamento-aps', montar: telaFinanciamentoAps },
      { id: 'visitas-acs', montar: telaVisitasAcs },
      { id: 'credenciamento', montar: telaCredenciamento },
      { id: 'mac-teto', montar: telaMacTeto },
      { id: 'sia-sih', montar: telaSiaSih },
      { id: 'onco-mental', montar: telaOncologiaMental },
      { id: 'vigilancia', montar: telaVigilancia },
    ];

    if (!dados) {
      palco.innerHTML = `
        <div class="slide ativo">
          <div class="sem-dados" style="height:100%">
            ${ic('alerta')}
            <strong>Nenhum dado disponível</strong>
            <span>Inicie o servidor com <code>python servidor.py</code> ou execute <code>python coletor.py</code> para gerar o cache.</span>
          </div>
        </div>`;
      return;
    }

    slides = definicoes.map((def, i) => {
      let conteudo = '';
      try {
        conteudo = def.montar();
      } catch (erro) {
        console.error('Falha ao montar a tela', def.id, erro);
        conteudo = semDados(def.id);
      }
      return `<section class="slide" data-tela="${def.id}" aria-hidden="true">${conteudo}</section>`;
    });

    palco.innerHTML = slides.join('');
    pontosEl.innerHTML = definicoes
      .map((def, i) => `<button class="ponto" data-ir="${i}" title="${esc(def.id)}" aria-label="Ir para a tela ${i + 1}"></button>`)
      .join('');

    [...palco.querySelectorAll('.slide')].forEach((slide, i) => {
      slide.setAttribute('aria-hidden', i === indice ? 'false' : 'true');
    });
    [...pontosEl.querySelectorAll('.ponto')].forEach((ponto, i) => {
      ponto.classList.toggle('ativo', i === indice);
    });
  }

  /* --------------------------------------------------------------- animações */

  function animarContadores(raiz) {
    if (reduzirMovimento) return;
    const alvos = raiz.querySelectorAll('.contador');
    alvos.forEach((el) => {
      const alvo = Number(el.dataset.contar);
      if (!Number.isFinite(alvo)) return;
      const tipo = el.dataset.tipo || 'int';
      const casas = Number(el.dataset.casas || 0);
      const duracao = 1100;
      const inicio = performance.now();
      const passo = (agora) => {
        const t = Math.min(1, (agora - inicio) / duracao);
        const suave = 1 - Math.pow(1 - t, 3);
        el.textContent = fmt(alvo * suave, tipo, casas);
        if (t < 1) requestAnimationFrame(passo);
        else el.textContent = fmt(alvo, tipo, casas);
      };
      requestAnimationFrame(passo);
    });
  }

  /* --------------------------------------------------------------- navegação */

  function animarBarra(ms) {
    barra.style.transition = 'none';
    barra.style.width = '0%';
    void barra.offsetWidth;
    barra.style.transition = `width ${ms}ms linear`;
    barra.style.width = '100%';
  }

  function agendar(ms) {
    clearTimeout(temporizador);
    inicioSlide = performance.now();
    restante = ms;
    animarBarra(ms);
    temporizador = setTimeout(() => {
      if (!pausado) mostrar((indice + 1) % (slides.length || 1));
    }, ms);
  }

  function mostrar(novoIndice) {
    if (!slides.length) return;
    indice = ((novoIndice % slides.length) + slides.length) % slides.length;

    [...palco.querySelectorAll('.slide')].forEach((slide, i) => {
      const ativo = i === indice;
      slide.classList.toggle('ativo', ativo);
      slide.setAttribute('aria-hidden', ativo ? 'false' : 'true');
      if (ativo) {
        // reinicia as animações de entrada
        slide.querySelectorAll('.animar, .cartao, .anel-cartao').forEach((el) => {
          el.style.animation = 'none';
          void el.offsetWidth;
          el.style.animation = '';
        });
      }
    });

    [...pontosEl.querySelectorAll('.ponto')].forEach((ponto, i) => ponto.classList.toggle('ativo', i === indice));

    const slideAtual = palco.querySelectorAll('.slide')[indice];
    if (slideAtual) animarContadores(slideAtual);

    pausado = false;
    atualizarBotaoPausa();
    agendar(DURACAO_SLIDE);
  }

  function proxima() { mostrar(indice + 1); }
  function anterior() { mostrar(indice - 1); }

  function alternarPausa() {
    pausado = !pausado;
    if (pausado) {
      clearTimeout(temporizador);
      restante = Math.max(1200, restante - (performance.now() - inicioSlide));
      const larguraAtual = barra.getBoundingClientRect().width;
      barra.style.transition = 'none';
      barra.style.width = `${larguraAtual}px`;
    } else {
      agendar(restante);
    }
    atualizarBotaoPausa();
  }

  function atualizarBotaoPausa() {
    const botao = $('#btn-pausar');
    if (botao) botao.style.color = pausado ? 'var(--azul)' : '';
    if (botao) botao.title = pausado ? 'Retomar (espaço)' : 'Pausar (espaço)';
  }

  function telaCheia() {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else document.documentElement.requestFullscreen?.().catch(() => {});
  }

  /* --------------------------------------------------------------- relógio e status */

  function atualizarRelogio() {
    const agora = new Date();
    $('#relogio').textContent = agora.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    $('#data').textContent = agora.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' });
  }

  function atualizarStatus() {
    const selo = $('#selo');
    const texto = $('#selo-texto');
    const online = dados?.online !== false;
    const vazio = !dados;

    selo.classList.toggle('offline', !online && !vazio);
    selo.classList.toggle('erro', vazio);
    texto.textContent = vazio ? 'sem dados' : (online ? 'ao vivo' : 'modo cache');

    const aviso = $('#aviso');
    const avisoTexto = $('#aviso-texto');
    if (dados?.avisoOffline) {
      aviso.hidden = false;
      avisoTexto.textContent = dados.avisoOffline;
    } else if (dados?.avisos?.length) {
      aviso.hidden = false;
      avisoTexto.textContent = `Coleta parcial: ${dados.avisos.join(' · ')}`;
    } else {
      aviso.hidden = true;
    }

    if (dados?.geradoEm) {
      const quando = new Date(dados.geradoEm);
      const hoje = new Date();
      const mesmoDia = quando.toDateString() === hoje.toDateString();
      const hora = quando.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      const dia = quando.toLocaleDateString('pt-BR');
      $('#rodape-atualizacao').textContent =
        `Última atualização: ${mesmoDia ? `hoje, ${hora}` : `${dia}, ${hora}`} · ${online ? 'conectado aos Painéis CONASEMS' : 'dados armazenados localmente'}`;
    }

    const municipio = dados?.municipio;
    if (municipio) {
      $('#municipio').textContent = `${municipio.nome} - ${municipio.uf}`;
      $('#municipio-sub').textContent = `${municipio.uf} · IBGE ${municipio.ibge}`;
      document.title = `Painel APS, MAC e Vigilância · ${municipio.nome}/${municipio.uf}`;
    }
  }

  /* --------------------------------------------------------------- identidade */

  function aplicarIdentidade(config) {
    const cfg = config || (dados && dados.config) || window.__PAINEL_CONFIG__;
    if (!cfg) return;
    const imagem = $('#marca-logo');
    const simbolo = $('#marca-simbolo');
    if (!imagem || !simbolo) return;

    if (cfg.logo) {
      const versao = cfg.logoVersao ? `?v=${encodeURIComponent(cfg.logoVersao)}` : '';
      const src = `${cfg.logo}${versao}`;
      if (imagem.getAttribute('src') !== src) imagem.src = src;
      imagem.hidden = false;
      simbolo.classList.add('com-logo');
    } else {
      imagem.hidden = true;
      imagem.removeAttribute('src');
      simbolo.classList.remove('com-logo');
    }
  }

  /* --------------------------------------------------------------- dados */

  async function buscarDados(url) {
    const resposta = await fetch(url, { cache: 'no-store' });
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    return resposta.json();
  }

  async function atualizarDados(primeira = false) {
    try {
      const novos = await buscarDados(primeira ? '/api/dados?refresh=1' : '/api/dados?refresh=1');
      if (novos && !novos.erro) {
        const mudou = novos.geradoEm && novos.geradoEm !== ultimoGeradoEm;
        dados = novos;
        ultimoGeradoEm = novos.geradoEm;
        usandoCache = false;
        aplicarIdentidade(novos.config);
        atualizarStatus();
        if (mudou || slides.length === 0) {
          montarTelas();
          mostrar(Math.min(indice, Math.max(0, slides.length - 1)));
        }

      }
    } catch (erro) {
      // Sem servidor (arquivo local) ou sem rede: usa o cache embutido.
      if (!usandoCache && window.__PAINEL_DADOS__) {
        usandoCache = true;
        dados = {
          ...window.__PAINEL_DADOS__,
          online: false,
          avisoOffline: 'Sem conexão com o servidor local — exibindo a última coleta armazenada. O painel volta a atualizar automaticamente quando a conexão for restabelecida.',
        };
        ultimoGeradoEm = dados.geradoEm;
        montarTelas();
        mostrar(0);
        atualizarStatus();
      }
    }
  }

  /* --------------------------------------------------------------- inicialização */

  function ligarEventos() {
    $('#btn-proxima').addEventListener('click', proxima);
    $('#btn-anterior').addEventListener('click', anterior);
    $('#btn-pausar').addEventListener('click', alternarPausa);
    $('#btn-tela').addEventListener('click', telaCheia);

    pontosEl.addEventListener('click', (evento) => {
      const botao = evento.target.closest('[data-ir]');
      if (botao) mostrar(Number(botao.dataset.ir));
    });

    palco.addEventListener('mouseenter', () => { if (!pausado) alternarPausa(); });
    palco.addEventListener('mouseleave', () => { if (pausado) alternarPausa(); });

    document.addEventListener('keydown', (evento) => {
      if (evento.key === 'ArrowRight') { proxima(); evento.preventDefault(); }
      else if (evento.key === 'ArrowLeft') { anterior(); evento.preventDefault(); }
      else if (evento.key === ' ') { alternarPausa(); evento.preventDefault(); }
      else if (evento.key.toLowerCase() === 'f') telaCheia();
    });

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (!pausado) alternarPausa();
      } else {
        if (pausado) alternarPausa();
        atualizarDados();
      }
    });

    setInterval(atualizarRelogio, 1000);
    setInterval(() => atualizarDados(), INTERVALO_RECARGA);
  }

  function iniciar() {
    atualizarRelogio();
    ligarEventos();
    aplicarIdentidade();

    // Primeiro pinta com o cache (garante imagem imediata na TV)…
    if (dados) {
      ultimoGeradoEm = dados.geradoEm;
      montarTelas();
      mostrar(0);
      atualizarStatus();
    }

    // …depois tenta o servidor local, que pode trazer dados novos.
    atualizarDados(true);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
})();
