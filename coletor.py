#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor dos Painéis CONASEMS - município configurado no painel.

Consulta as APIs públicas dos painéis (APS, MAC e Vigilância em Saúde), monta
um resumo com os principais indicadores, grava em banco SQLite e gera um cache
JavaScript (dados/cache.js) para o painel funcionar mesmo sem internet.

O município monitorado é lido de dados/config.json (painel de configuração) e
pode ser definido por PAINEL_IBGE/PAINEL_MUNICIPIO/PAINEL_UF na primeira
execução.

Uso:
    python coletor.py
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import configuracao

BASE = "https://paineis.conasems.org.br"
IBGE = "410240"
MUNICIPIO = "BANDEIRANTES"
UF = "PR"

RAIZ = Path(__file__).resolve().parent
PASTA_DADOS = configuracao.PASTA_DADOS
BANCO = PASTA_DADOS / "conasems.db"
CACHE_JS = PASTA_DADOS / "cache.js"

URL_APS = f"{BASE}/atencao_basica/{IBGE}/{MUNICIPIO}/cit"
URL_MAC = f"{BASE}/producao/{IBGE}/{MUNICIPIO}/cit"
URL_VIG = f"{BASE}/vigilancia/{IBGE}/{MUNICIPIO}/cit"


def aplicar_config(ambiente: dict | None = None) -> dict:
    """Atualiza município e URLs a partir da configuração salva."""
    global IBGE, MUNICIPIO, UF, URL_APS, URL_MAC, URL_VIG
    ambiente = ambiente or configuracao.ambiente()
    municipio = ambiente["municipio"]
    IBGE = str(ambiente.get("codigoConasems") or municipio["ibge"])[:6]
    MUNICIPIO = ambiente["nome_url"]
    UF = municipio["uf"]
    URL_APS = ambiente["urlAps"]
    URL_MAC = ambiente["urlMac"]
    URL_VIG = ambiente["urlVig"]
    return ambiente

CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


# ---------------------------------------------------------------------------
# Infraestrutura HTTP
# ---------------------------------------------------------------------------

def fuso_local():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/Sao_Paulo")
    except Exception:  # banco de fusos ausente no Windows
        return timezone(timedelta(hours=-3))


def _decodificar(bruto: bytes) -> str:
    for codificacao in ("utf-8", "latin-1"):
        try:
            return bruto.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return bruto.decode("utf-8", "replace")


def http_get(url: str, tentativas: int = 3) -> str:
    ultimo_erro: Exception | None = None
    for tentativa in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=CABECALHOS)
            with urllib.request.urlopen(req, timeout=30) as resposta:
                return _decodificar(resposta.read())
        except Exception as erro:  # noqa: BLE001 - queremos registrar qualquer falha
            ultimo_erro = erro
            time.sleep(1.2 * (tentativa + 1))
    raise RuntimeError(f"Falha ao acessar {url}: {ultimo_erro}")


def http_post(caminho: str, dados: dict, referer: str, tentativas: int = 3) -> str:
    url = f"{BASE}/assets/ajax/{caminho}"
    corpo = urllib.parse.urlencode(dados).encode("utf-8")
    ultimo_erro: Exception | None = None
    for tentativa in range(tentativas):
        try:
            cabecalhos = dict(CABECALHOS)
            cabecalhos["Referer"] = referer
            cabecalhos["Origin"] = BASE
            cabecalhos["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            req = urllib.request.Request(url, data=corpo, headers=cabecalhos)
            with urllib.request.urlopen(req, timeout=30) as resposta:
                return _decodificar(resposta.read())
        except Exception as erro:  # noqa: BLE001
            ultimo_erro = erro
            time.sleep(1.2 * (tentativa + 1))
    raise RuntimeError(f"Falha ao consultar {caminho}: {ultimo_erro}")


def json_post(caminho: str, dados: dict, referer: str):
    texto = http_post(caminho, dados, referer).strip()
    if not texto:
        return None
    return json.loads(texto)


# ---------------------------------------------------------------------------
# Conversores
# ---------------------------------------------------------------------------

def num(valor, padrao: float = 0.0) -> float:
    """Converte números no formato brasileiro ou americano."""
    if valor is None:
        return padrao
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto or texto in {"-", "—"}:
        return padrao
    texto = re.sub(r"[^\d,.\-]", "", texto)
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return padrao


def inteiro(valor, padrao: int = 0) -> int:
    return int(round(num(valor, padrao)))


def arred(valor: float, casas: int = 2) -> float:
    return round(float(valor), casas)


def mes_ano(referencia: str) -> str:
    """'2026-09-01' -> '09/2026'."""
    if not referencia:
        return ""
    partes = str(referencia)[:10].split("-")
    if len(partes) >= 2:
        return f"{partes[1]}/{partes[0]}"
    return str(referencia)


def ano_de(referencia: str) -> str:
    return str(referencia)[:4]


# ---------------------------------------------------------------------------
# Coleta APS
# ---------------------------------------------------------------------------

def coletar_aps(avisos: list[str]) -> dict:
    aps: dict = {"fonte": "SIAPS / Ministério da Saúde", "url": URL_APS}

    dados = None
    try:
        dados = json_post("atencao_basica_dados.php", {"ibge": IBGE, "tipo": "cit"}, URL_APS)
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"APS (dados gerais): {erro}")

    if dados:
        cobertura = dados.get("cobertura", {})
        aps["cobertura"] = {
            "aps": arred(num(cobertura.get("aps", {}).get("valor"))),
            "sb": arred(num(cobertura.get("sb", {}).get("valor"))),
            "acs": arred(num(cobertura.get("acs", {}).get("valor"))),
            "potencial": inteiro(cobertura.get("aps", {}).get("potencial")),
            "potencialSb": inteiro(cobertura.get("sb", {}).get("potencial")),
            "potencialAcs": inteiro(cobertura.get("acs", {}).get("potencial")),
            "ref": cobertura.get("aps", {}).get("referencia", ""),
            "equipes": [
                {"sigla": "eSF", "qtd": inteiro(cobertura.get("aps", {}).get("qtdEsf"))},
                {"sigla": "eAP 20h", "qtd": inteiro(cobertura.get("aps", {}).get("qtdEap20h"))},
                {"sigla": "eAP 30h", "qtd": inteiro(cobertura.get("aps", {}).get("qtdEap30h"))},
                {"sigla": "eCR", "qtd": inteiro(cobertura.get("aps", {}).get("qtdEcr"))},
                {"sigla": "eAPP", "qtd": inteiro(cobertura.get("aps", {}).get("qtdEapp"))},
                {"sigla": "eSFR", "qtd": inteiro(cobertura.get("aps", {}).get("qtdEsfr"))},
            ],
            "equipesSb": [
                {"sigla": "eSB 20h", "qtd": inteiro(cobertura.get("sb", {}).get("qtEsb20h"))},
                {"sigla": "eSB 30h", "qtd": inteiro(cobertura.get("sb", {}).get("qtEsb30h"))},
                {"sigla": "eSB 40h", "qtd": inteiro(cobertura.get("sb", {}).get("qtEsb40h"))},
            ],
            "acsQtd": inteiro(cobertura.get("acs", {}).get("qtAcsCobertura")),
        }

        homologacao = dados.get("homologacao", {})
        aps["homologacao"] = {
            "equipes": inteiro(homologacao.get("equipes", {}).get("total")),
            "estabelecimentos": inteiro(homologacao.get("estabelecimentos", {}).get("total")),
            "ref": homologacao.get("equipes", {}).get("referencia", ""),
        }

        pagamentos = dados.get("pagamentos", {})
        historico = pagamentos.get("totalHistory") or []
        rotulos = pagamentos.get("labelsHistory") or []
        media = pagamentos.get("movingAvg12") or []
        corte = max(0, len(historico) - 12)
        aps["repasses"] = {
            "total": arred(num(pagamentos.get("totalGeral"))),
            "saudeFamilia": arred(num(pagamentos.get("totalSaudeFamilia"))),
            "saudeBucal": arred(num(pagamentos.get("totalSaudeBucal"))),
            "acs": arred(num(pagamentos.get("totalACS"))),
            "ref": pagamentos.get("referencia", ""),
            "historico": {
                "labels": rotulos[corte:],
                "valores": [arred(num(v)) for v in historico[corte:]],
                "mediaMovel": [arred(num(v)) for v in media[corte:]],
            },
        }

        ausencia = dados.get("ausencia", {})
        aps["ausencia"] = {
            "total": inteiro(ausencia.get("total")),
            "ref": ausencia.get("referencia", ""),
        }

        producao = dados.get("producao", {})
        aps["producao"] = {
            "medico": inteiro(producao.get("atendimentoMedico")),
            "enfermeiro": inteiro(producao.get("atendimentoEnfermeiro")),
            "odonto": inteiro(producao.get("atendimentoOdontologico")),
            "procedimentos": inteiro(producao.get("procedimentos")),
            "visitas": inteiro(producao.get("visitasDomiciliares")),
            "ref": producao.get("referencia", ""),
            "porHab": {
                "medico": arred(num(producao.get("mediaMedHab"))),
                "enfermeiro": arred(num(producao.get("mediaEnfHab"))),
                "odonto": arred(num(producao.get("mediaOdontoHab"))),
                "procedimentos": arred(num(producao.get("mediaProcedimentosHab"))),
                "visitas": arred(num(producao.get("mediaVisitasHab"))),
            },
        }

    # --- Solicitações de credenciamento -----------------------------------
    try:
        hoje = datetime.now(fuso_local())
        referencia = hoje.replace(day=1).strftime("%Y-%m-01")
        gaps = None
        for tentativa in range(2):
            try:
                gaps = json_post(
                    "atencao_basica_dados.php",
                    {
                        "action": "gaps_data",
                        "ibge": IBGE,
                        "tipo": "cit",
                        "ref_gaps": referencia,
                        "rdqa": 0,
                    },
                    URL_APS,
                )
                break
            except Exception:  # noqa: BLE001
                # tenta o mês anterior
                referencia = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y-%m-01")
                time.sleep(0.6)
        if isinstance(gaps, dict):
            solicitacoes = gaps.get("solicitacoes") or []
            situacoes = Counter()
            for linha in solicitacoes:
                bruto = " ".join(str(c) for c in linha)
                texto = re.sub(r"<[^>]+>", " ", bruto)
                texto = re.sub(r"\s+", " ", texto).upper()
                if "CREDENCIADA" in texto:
                    situacoes["credenciadas"] += 1
                elif "SOLICITADA" in texto:
                    situacoes["solicitadas"] += 1
                elif "ANÁLISE" in texto or "ANALISE" in texto:
                    situacoes["emAnalise"] += 1
                elif "PORTARIA" in texto:
                    situacoes["publicadas"] += 1
                else:
                    situacoes["outras"] += 1
            aps["solicitacoes"] = {
                "total": len(solicitacoes),
                "credenciadas": situacoes.get("credenciadas", 0),
                "solicitadas": situacoes.get("solicitadas", 0),
                "emAnalise": situacoes.get("emAnalise", 0),
                "outras": situacoes.get("outras", 0),
                "ref": gaps.get("referenciaFormatada", ""),
            }
            estrategias = []
            for linha in gaps.get("estrategias") or []:
                if len(linha) >= 4:
                    try:
                        estrategias.append(
                            {
                                "nome": re.sub(r"\s+", " ", str(linha[0])).strip(),
                                "credenciadas": inteiro(linha[2]),
                                "solicitadas": inteiro(linha[1]) - inteiro(linha[2]) - inteiro(linha[3]),
                            }
                        )
                    except Exception:  # noqa: BLE001
                        continue
            aps["estrategias"] = estrategias
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"APS (credenciamento): {erro}")

    # --- Visitas dos ACS ---------------------------------------------------
    try:
        visitas = json_post("epidemiologia.php?option=visitaacs", {"ibge": IBGE, "tipo": "cit"}, URL_APS)
        if isinstance(visitas, list) and visitas:
            registros = sorted(visitas, key=lambda r: str(r.get("Data", "")))
            ultimo = registros[-1]
            realizadas = inteiro(ultimo.get("VisitaRealizada"))
            ausentes = inteiro(ultimo.get("Ausente"))
            recusadas = inteiro(ultimo.get("VisitaRecusada"))
            total = realizadas + ausentes + recusadas
            qtd_acs = inteiro(ultimo.get("QtdAcs"))
            aps["acsVisitas"] = {
                "ref": mes_ano(ultimo.get("Data", "")),
                "realizadas": realizadas,
                "ausentes": ausentes,
                "recusadas": recusadas,
                "total": total,
                "qtdAcs": qtd_acs,
                "mediaMes": inteiro(realizadas / qtd_acs) if qtd_acs else 0,
                # 22 dias úteis por mês, mesma regra usada pelo painel
                "mediaDia": arred(realizadas / (qtd_acs * 22), 1) if qtd_acs else 0,
                "historico": [
                    {
                        "ref": mes_ano(r.get("Data", "")),
                        "realizadas": inteiro(r.get("VisitaRealizada")),
                        "ausentes": inteiro(r.get("Ausente")),
                        "recusadas": inteiro(r.get("VisitaRecusada")),
                    }
                    for r in registros[-12:]
                ],
            }
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"APS (visitas ACS): {erro}")

    # --- Cofinanciamento (CVAT - Dimensão Acompanhamento) ------------------
    try:
        registros = json_post("producao.php?option=cofinanciamento", {"ibge": IBGE, "tipo": "cit"}, URL_APS)
        if isinstance(registros, list) and registros:
            agrupado = defaultdict(lambda: {"regular": 0, "suficiente": 0, "bom": 0, "otimo": 0})
            for linha in registros:
                if "Dimensão Acompanhamento" not in str(linha.get("dimensao_indicador", "")):
                    continue
                quadrimestre = str(linha.get("quadrimestre", ""))
                if len(quadrimestre) == 6:  # 2025Q2 -> Q2/25
                    quadrimestre = f"{quadrimestre[4:]}/{quadrimestre[2:4]}"
                grupo = agrupado[quadrimestre]
                grupo["regular"] += inteiro(linha.get("regular"))
                grupo["suficiente"] += inteiro(linha.get("suficiente"))
                grupo["bom"] += inteiro(linha.get("bom"))
                grupo["otimo"] += inteiro(linha.get("otimo"))
            def ordem_quadrimestre(item):
                nome = item[0]
                if "/" in nome:
                    quadrimestre, ano = nome.split("/")
                    return (ano, quadrimestre)
                return ("0", nome)

            aps["cofinanciamento"] = [
                {
                    "quadrimestre": q,
                    **valores,
                    "total": sum(valores.values()),
                }
                for q, valores in sorted(agrupado.items(), key=ordem_quadrimestre)
            ]
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"APS (cofinanciamento): {erro}")

    return aps


# ---------------------------------------------------------------------------
# Coleta MAC
# ---------------------------------------------------------------------------

def _soma_ano(lista: list[dict], campo: str, ano: str) -> float:
    return sum(num(r.get(campo)) for r in lista if str(r.get("referencia", "")).endswith("/" + ano))


def _ano_fechado(*listas: list[dict]) -> str:
    """Ano mais recente com 12 competências em todas as séries informadas."""
    contagem = Counter()
    for lista in listas:
        anos = Counter(str(r.get("referencia", ""))[-4:] for r in lista if r.get("referencia"))
        if not anos:
            continue
        candidatos = {ano for ano, qtd in anos.items() if qtd >= 12}
        contagem.update(candidatos)
    if not contagem:
        todos = [ano for lista in listas for ano in (str(r.get("referencia", ""))[-4:] for r in lista) if ano]
        return max(todos) if todos else ""
    return max(contagem.keys())


def ler_teto_mac(avisos: list[str]) -> dict:
    teto = {}
    try:
        html = http_get(URL_MAC)
        cartoes = re.findall(
            r'<h5 class="saas-title">(.*?)</h5>\s*</div>\s*<h4 class="saas-value">(.*?)</h4>'
            r"\s*<div class=\"saas-subtitle\">(.*?)</div>\s*<div[^>]*>(.*?)</div>",
            html,
            re.S,
        )
        valores = {}
        for titulo, valor, _subtitulo, detalhe in cartoes:
            titulo_limpo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", titulo)).strip().lower()
            mensal = re.search(r"Mensal:\s*<strong[^>]*>(.*?)</strong>", detalhe, re.S)
            conversao = num(valor)
            mensal_valor = num(mensal.group(1)) if mensal else 0.0
            if "total" in titulo_limpo:
                valores["total"] = conversao
                valores["mensalTotal"] = mensal_valor
            elif "sem" in titulo_limpo:
                valores["semIncentivos"] = conversao
                valores["mensalSemIncentivos"] = mensal_valor
            elif "incentivo" in titulo_limpo:
                valores["incentivos"] = conversao
                valores["mensalIncentivos"] = mensal_valor
        periodo = re.search(r"SISMAC,\s*([0-9/]+ a [0-9/]+)", html)
        valores["periodo"] = periodo.group(1) if periodo else ""
        if valores.get("total"):
            teto = valores
        else:
            avisos.append("MAC: não foi possível interpretar o teto MAC no HTML.")
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"MAC (teto): {erro}")
    return teto


def coletar_mac(avisos: list[str]) -> dict:
    mac: dict = {"fonte": "SISMAC / DATASUS / Ministério da Saúde", "url": URL_MAC}

    mac["teto"] = ler_teto_mac(avisos)

    # --- Produção mensal SIA e SIH ----------------------------------------
    producao = None
    try:
        producao = json_post(
            "producao.php?option=producaoMac",
            {
                "ibge": IBGE,
                "tipo": "cit",
                "filtroAmbulatorial": "atendimento",
                "filtroHospitalar": "internacao",
            },
            URL_MAC,
        )
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"MAC (produção): {erro}")

    if isinstance(producao, list) and len(producao) >= 2:
        sia_mensal = sorted(producao[0], key=lambda r: (str(r.get("referencia"))[3:], str(r.get("referencia"))[:2]))
        sih_mensal = sorted(producao[1], key=lambda r: (str(r.get("referencia"))[3:], str(r.get("referencia"))[:2]))
        ano = _ano_fechado(sia_mensal, sih_mensal)

        sia = {
            "ano": ano,
            "apresentada": inteiro(_soma_ano(sia_mensal, "QtdApresentada", ano)),
            "aprovada": inteiro(_soma_ano(sia_mensal, "QtdAprovada", ano)),
            "valorApresentado": arred(_soma_ano(sia_mensal, "ValorApresentado", ano)),
            "valorAprovado": arred(_soma_ano(sia_mensal, "ValorAprovado", ano)),
        }
        sia["glosa"] = arred(sia["valorApresentado"] - sia["valorAprovado"])
        sia["pctAprovado"] = arred(100 * sia["valorAprovado"] / sia["valorApresentado"], 1) if sia["valorApresentado"] else 0
        sia["pctQtdAprovada"] = arred(100 * sia["aprovada"] / sia["apresentada"], 1) if sia["apresentada"] else 0
        if sia_mensal:
            ultimo = sia_mensal[-1]
            sia["ultimoMes"] = {
                "ref": ultimo.get("referencia", ""),
                "apresentada": inteiro(ultimo.get("QtdApresentada")),
                "aprovada": inteiro(ultimo.get("QtdAprovada")),
                "valorApresentado": arred(num(ultimo.get("ValorApresentado"))),
                "valorAprovado": arred(num(ultimo.get("ValorAprovado"))),
            }

        sih = {
            "ano": ano,
            "internacoes": inteiro(_soma_ano(sih_mensal, "internacoes", ano)),
            "aih": inteiro(_soma_ano(sih_mensal, "aih_aprovadas", ano)),
            "valor": arred(_soma_ano(sih_mensal, "valor_total", ano)),
        }
        sih["mediaAih"] = arred(sih["valor"] / sih["aih"]) if sih["aih"] else 0
        if sih_mensal:
            ultimo = sih_mensal[-1]
            sih["ultimoMes"] = {
                "ref": ultimo.get("referencia", ""),
                "internacoes": inteiro(ultimo.get("internacoes")),
                "aih": inteiro(ultimo.get("aih_aprovadas")),
                "valor": arred(num(ultimo.get("valor_total"))),
            }

        mac["sia"] = sia
        mac["sih"] = sih
        mac["total"] = arred(sia["valorAprovado"] + sih["valor"])

        if mac.get("teto"):
            mac["diferenca"] = {
                "semIncentivos": arred(mac["teto"].get("semIncentivos", 0) - mac["total"]),
                "comIncentivos": arred(mac["teto"].get("total", 0) - mac["total"]),
            }

        combinado = defaultdict(lambda: {"sia": 0.0, "sih": 0.0, "siaQtd": 0, "sihQtd": 0})
        for linha in sia_mensal:
            ref = linha.get("referencia", "")
            combinado[ref]["sia"] = num(linha.get("ValorAprovado"))
            combinado[ref]["siaQtd"] = inteiro(linha.get("QtdAprovada"))
        for linha in sih_mensal:
            ref = linha.get("referencia", "")
            combinado[ref]["sih"] = num(linha.get("valor_total"))
            combinado[ref]["sihQtd"] = inteiro(linha.get("aih_aprovadas"))

        def chave_ordenacao(item):
            referencia = item[0]
            if "/" in referencia:
                mes, ano_ref = referencia.split("/")
                return (ano_ref, mes)
            return ("0", "0")

        mensal = []
        for ref, valores in sorted(combinado.items(), key=chave_ordenacao)[-12:]:
            mensal.append(
                {
                    "ref": ref,
                    "sia": arred(valores["sia"]),
                    "sih": arred(valores["sih"]),
                    "total": arred(valores["sia"] + valores["sih"]),
                    "siaQtd": valores["siaQtd"],
                    "sihQtd": valores["sihQtd"],
                }
            )
        mac["mensal"] = mensal

    # --- Financiamento SIA ------------------------------------------------
    try:
        financiamento = json_post(
            "producao.php?option=producaoFinanciamentoSia",
            {"ibge": IBGE, "tipo": "cit", "filtroAmbulatorial": "atendimento"},
            URL_MAC,
        )
        if isinstance(financiamento, list) and financiamento:
            ultimo = sorted(financiamento, key=lambda r: (str(r.get("referencia"))[3:], str(r.get("referencia"))[:2]))[-1]
            mac["financiamento"] = {
                "ref": ultimo.get("referencia", ""),
                "mac": arred(num(ultimo.get("mac"))),
                "pab": arred(num(ultimo.get("pab"))),
                "faec": arred(num(ultimo.get("faec"))),
                "farmacia": arred(num(ultimo.get("assistencia_farmaceutica"))),
                "incentivoMac": arred(num(ultimo.get("incentivo_mac"))),
                "vigilancia": arred(num(ultimo.get("vigilancia_saude"))),
                "total": arred(num(ultimo.get("total"))),
            }
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"MAC (financiamento): {erro}")

    # --- Oncologia --------------------------------------------------------
    try:
        tempo = json_post("producao.php?option=oncologiaTempoTratamento", {"ibge": IBGE, "tipo": "cit"}, URL_MAC)
        if isinstance(tempo, list) and tempo:
            por_ano = sorted(tempo, key=lambda r: str(r.get("referencia", "")))
            atual = por_ano[-1]
            mac["oncologia"] = {
                "ano": inteiro(atual.get("ano")),
                "tempoMedio": arred(num(atual.get("tempo_medio_dias")), 1),
                "pct60": arred(num(atual.get("pct_ate_60_dias")), 1),
                "ate30": inteiro(atual.get("ate_30_dias")),
                "de31a60": inteiro(atual.get("de_31_a_60_dias")),
                "mais60": inteiro(atual.get("mais_de_60_dias")),
                "tratados": inteiro(atual.get("total_com_tratamento")),
                "casos": inteiro(atual.get("total_casos")),
                "semInfo": inteiro(atual.get("sem_informacao")),
                "historico": [
                    {
                        "ano": inteiro(r.get("ano")),
                        "tempoMedio": arred(num(r.get("tempo_medio_dias")), 1),
                        "pct60": arred(num(r.get("pct_ate_60_dias")), 1),
                        "casos": inteiro(r.get("total_casos")),
                    }
                    for r in por_ano
                ],
            }
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"MAC (oncologia - tempo): {erro}")

    try:
        casos = json_post("producao.php?option=oncologiaCasos", {"ibge": IBGE, "tipo": "cit"}, URL_MAC)
        if isinstance(casos, dict) and casos.get("data"):
            registros = casos["data"]
            anos = Counter(ano_de(r.get("referencia", "")) for r in registros)
            ano_atual = max(anos) if anos else ""
            filtrados = [r for r in registros if ano_de(r.get("referencia", "")) == ano_atual]
            agrupado = Counter()
            for registro in filtrados:
                agrupado[str(registro.get("diagnostico", "")).strip()] += inteiro(registro.get("casos"))
            top = []
            for diagnostico, quantidade in sorted(agrupado.items(), key=lambda x: (-x[1], x[0]))[:10]:
                codigo = diagnostico.split(" - ")[0]
                descricao = diagnostico.split(" - ", 1)[1].strip() if " - " in diagnostico else diagnostico
                top.append({"cid": codigo, "desc": descricao, "casos": quantidade})
            onco = mac.setdefault("oncologia", {})
            onco["casosDetalhe"] = {
                "ano": inteiro(ano_atual),
                "total": sum(agrupado.values()),
                "top": top,
            }
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"MAC (oncologia - casos): {erro}")

    # --- Saúde mental -----------------------------------------------------
    try:
        mental = json_post("producao.php?option=saudeMental", {"ibge": IBGE, "tipo": "cit"}, URL_MAC)
        if isinstance(mental, dict) and mental.get("success"):
            sia = mental.get("sia") or []
            sih = mental.get("sih") or []
            cids = mental.get("cid_detail") or []
            total_sia = sum(inteiro(r.get("qtd_aprovada")) for r in sia)
            total_sih = sum(inteiro(r.get("qtd_aih")) for r in sih)
            mac["saudeMental"] = {
                "ano": inteiro(mental.get("selected_year")),
                "sia": [
                    {"nome": r.get("nome_estabelecimento", ""), "qtd": inteiro(r.get("qtd_aprovada"))}
                    for r in sia
                ],
                "sih": [
                    {
                        "nome": r.get("nome_estabelecimento", ""),
                        "aih": inteiro(r.get("qtd_aih")),
                        "valor": arred(num(r.get("valor_total"))),
                    }
                    for r in sih
                ],
                "totalSia": total_sia,
                "totalSih": total_sih,
                "topCids": [
                    {
                        "cid": r.get("cid", ""),
                        "desc": r.get("descricao", ""),
                        "total": inteiro(r.get("sia_total")) + inteiro(r.get("sih_total")),
                    }
                    for r in sorted(
                        cids,
                        key=lambda r: -(inteiro(r.get("sia_total")) + inteiro(r.get("sih_total"))),
                    )[:5]
                ],
            }
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"MAC (saúde mental): {erro}")

    return mac


# ---------------------------------------------------------------------------
# Coleta Vigilância em Saúde
# ---------------------------------------------------------------------------

def coletar_vigilancia(avisos: list[str]) -> dict:
    vig: dict = {"fonte": "Vigilância em Saúde / DATASUS-MS", "url": URL_VIG}
    ano_atual = datetime.now(fuso_local()).year

    def consultar(opcao: str, extra: dict | None = None, arquivo: str = "vigilanciaemsaude.php"):
        dados = {"ibge": IBGE, "tipo": "cit"}
        if extra:
            dados.update(extra)
        return json_post(f"{arquivo}?option={opcao}", dados, URL_VIG)

    # --- Mortalidade geral e infantil -------------------------------------
    mortalidade: dict[str, list[dict]] = {}
    for chave, indicador in (
        ("geral", "TB_Mortalidade_Geral"),
        ("infantil", "TB_Mortalidade_Infantil"),
    ):
        try:
            registros = consultar("get_indicator_data", {"indicador": indicador})
            por_ano: dict[str, int] = defaultdict(int)
            for linha in registros or []:
                ano = ano_de(linha.get("referencia", ""))
                if ano.isdigit():
                    por_ano[ano] += inteiro(linha.get("obitos"))
            if por_ano:
                mortalidade[chave] = [
                    {"ano": int(ano), "obitos": obitos} for ano, obitos in sorted(por_ano.items())
                ]
        except Exception as erro:  # noqa: BLE001
            avisos.append(f"Vigilância (mortalidade {chave}): {erro}")
    if mortalidade:
        vig["mortalidade"] = mortalidade

    # --- Agravos de notificação (coeficientes por 100 mil) ----------------
    for chave, indicador in (
        ("tuberculose", "TB_Incidencia_Tuberculose"),
        ("hanseniase", "TB_Incidencia_Hanseniase"),
    ):
        try:
            registros = consultar("get_indicator_data", {"indicador": indicador})
            serie = [
                {"ano": int(ano_de(linha.get("ano", ""))), "valor": arred(num(linha.get("valor")), 3)}
                for linha in registros or []
                if ano_de(linha.get("ano", "")).isdigit()
            ]
            if serie:
                vig[chave] = sorted(serie, key=lambda item: item["ano"])
        except Exception as erro:  # noqa: BLE001
            avisos.append(f"Vigilância ({chave}): {erro}")

    # --- Dengue ------------------------------------------------------------
    try:
        registros = json_post("epidemiologia.php?option=Dengue", {"ibge": IBGE, "tipo": "cit"}, URL_VIG)
        if isinstance(registros, list) and registros:
            serie = []
            for chave, valor in registros[0].items():
                texto = str(chave)
                if texto.startswith("Ano") and texto[3:].isdigit():
                    serie.append({"ano": int(texto[3:]), "casos": inteiro(valor)})
            if serie:
                vig["dengue"] = sorted(serie, key=lambda item: item["ano"])
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"Vigilância (dengue): {erro}")

    # --- SRAG --------------------------------------------------------------
    try:
        dados = consultar("get_srag_table_data")
        if isinstance(dados, dict) and dados.get("data"):
            anos = [item for item in dados["data"] if inteiro(item.get("year")) == ano_atual]
            atual = (anos or dados["data"])[-1]
            vig["srag"] = {
                "ano": inteiro(atual.get("year")),
                "total": inteiro(atual.get("total")),
                "incidencia": arred(num(atual.get("incidence"))),
                "populacao": inteiro(dados.get("population")),
            }
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"Vigilância (SRAG): {erro}")

    # --- Cobertura vacinal -------------------------------------------------
    try:
        registros = consultar("vigenciaCoberturaVacinal")
        if isinstance(registros, list) and registros:
            atual = max(registros, key=lambda item: inteiro(item.get("ano")))
            nomes = (
                ("BCG", "BCG"),
                ("Penta", "Pentavalente"),
                ("Poliomielite", "Poliomielite"),
                ("MeningococoC", "Meningococo C"),
                ("Pneumococica", "Pneumocócica"),
                ("TripliceViralD1", "Tríplice viral D1"),
                ("FebreAmarela", "Febre amarela"),
                ("HepatiteA", "Hepatite A"),
            )
            vacinas = [
                {"nome": rotulo, "cobertura": arred(num(atual.get(chave)))}
                for chave, rotulo in nomes
                if atual.get(chave) not in (None, "")
            ]
            if vacinas:
                vig["vacinacao"] = {"ano": inteiro(atual.get("ano")), "meta": 95.0, "vacinas": vacinas}
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"Vigilância (vacinação): {erro}")

    # --- Nascidos vivos (último ano com registro) --------------------------
    for ano in (ano_atual - 1, ano_atual - 2):
        try:
            registros = consultar(
                "nascidosVivosPaginado",
                {"local": "estabelecimento", "ano": ano, "parto": "", "busca": "", "pagina": 1, "quantidade": 5},
            )
            if isinstance(registros, list) and registros:
                total = inteiro(registros[0].get("TotalNascidosGlobal"))
                if total:
                    vig["nascidos"] = {
                        "ano": ano,
                        "total": total,
                        "cesareo": inteiro(registros[0].get("TotalCesareoGlobal")),
                        "vaginal": inteiro(registros[0].get("TotalVaginalGlobal")),
                    }
                    break
        except Exception as erro:  # noqa: BLE001
            avisos.append(f"Vigilância (nascidos vivos {ano}): {erro}")

    # --- Internações por capítulo CID-10 -----------------------------------
    try:
        registros = consultar("morbidadeHospitalar", {"local_morbidade": "internacao", "ano": ano_atual})
        if isinstance(registros, list) and registros:
            capitulos = sorted(
                (
                    {"capitulo": str(item.get("ds_lista_morb", "")).strip(), "internacoes": inteiro(item.get("internacoes"))}
                    for item in registros
                ),
                key=lambda item: item["internacoes"],
                reverse=True,
            )
            vig["internacoes"] = {
                "ano": ano_atual,
                "total": sum(item["internacoes"] for item in capitulos),
                "capitulos": capitulos,
            }
    except Exception as erro:  # noqa: BLE001
        avisos.append(f"Vigilância (internações): {erro}")

    return vig


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------

ESQUEMA = """
CREATE TABLE IF NOT EXISTS coletas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciado_em TEXT NOT NULL,
    concluido_em TEXT,
    status TEXT NOT NULL,
    mensagem TEXT
);

CREATE TABLE IF NOT EXISTS indicadores (
    chave TEXT PRIMARY KEY,
    grupo TEXT NOT NULL,
    rotulo TEXT NOT NULL,
    valor REAL,
    valor_texto TEXT,
    unidade TEXT,
    referencia TEXT,
    fonte TEXT,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historico (
    chave TEXT NOT NULL,
    coletado_em TEXT NOT NULL,
    valor REAL,
    PRIMARY KEY (chave, coletado_em)
);

CREATE TABLE IF NOT EXISTS series (
    nome TEXT NOT NULL,
    referencia TEXT NOT NULL,
    valor REAL,
    parte TEXT,
    ordem INTEGER,
    PRIMARY KEY (nome, referencia, parte)
);

CREATE TABLE IF NOT EXISTS painel (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    json TEXT NOT NULL,
    gerado_em TEXT NOT NULL
);
"""


def indicadores_do_payload(payload: dict) -> list[tuple]:
    """Lista (chave, grupo, rotulo, valor, texto, unidade, referencia, fonte)."""
    agora = payload["geradoEm"]
    aps = payload.get("aps", {})
    mac = payload.get("mac", {})
    linhas: list[tuple] = []

    def add(chave, grupo, rotulo, valor, texto="", unidade="", referencia="", fonte=""):
        linhas.append((chave, grupo, rotulo, valor, texto, unidade, referencia, fonte or agora))

    if aps.get("cobertura"):
        c = aps["cobertura"]
        add("aps.cobertura.aps", "APS", "Cobertura potencial da APS", c["aps"], f"{c['aps']:.2f}%", "%", c["ref"], "SIAPS")
        add("aps.cobertura.sb", "APS", "Cobertura de Saúde Bucal", c["sb"], f"{c['sb']:.2f}%", "%", c["ref"], "SIAPS")
        add("aps.cobertura.acs", "APS", "Cobertura de ACS", c["acs"], f"{c['acs']:.2f}%", "%", c["ref"], "SIAPS")
    if aps.get("homologacao"):
        h = aps["homologacao"]
        add("aps.homologacao.equipes", "APS", "Equipes homologadas", h["equipes"], str(h["equipes"]), "equipes", h["ref"], "SIAPS")
        add("aps.homologacao.estabelecimentos", "APS", "Estabelecimentos homologados", h["estabelecimentos"], str(h["estabelecimentos"]), "estabelecimentos", h["ref"], "SIAPS")
    if aps.get("producao"):
        p = aps["producao"]
        add("aps.producao.medico", "APS", "Consultas médicas", p["medico"], str(p["medico"]), "atendimentos", p["ref"], "SIAPS")
        add("aps.producao.enfermeiro", "APS", "Consultas de enfermagem", p["enfermeiro"], str(p["enfermeiro"]), "atendimentos", p["ref"], "SIAPS")
        add("aps.producao.odonto", "APS", "Atendimentos odontológicos", p["odonto"], str(p["odonto"]), "atendimentos", p["ref"], "SIAPS")
        add("aps.producao.procedimentos", "APS", "Procedimentos", p["procedimentos"], str(p["procedimentos"]), "procedimentos", p["ref"], "SIAPS")
        add("aps.producao.visitas", "APS", "Visitas domiciliares", p["visitas"], str(p["visitas"]), "visitas", p["ref"], "SIAPS")
    if aps.get("repasses"):
        r = aps["repasses"]
        add("aps.repasses.total", "APS", "Repasses APS no mês", r["total"], f"R$ {r['total']:.2f}", "R$", r["ref"], "SIAPS")
        add("aps.repasses.sf", "APS", "Repasse Saúde da Família", r["saudeFamilia"], f"R$ {r['saudeFamilia']:.2f}", "R$", r["ref"], "SIAPS")
        add("aps.repasses.sb", "APS", "Repasse Saúde Bucal", r["saudeBucal"], f"R$ {r['saudeBucal']:.2f}", "R$", r["ref"], "SIAPS")
        add("aps.repasses.acs", "APS", "Repasse ACS", r["acs"], f"R$ {r['acs']:.2f}", "R$", r["ref"], "SIAPS")
    if aps.get("acsVisitas"):
        v = aps["acsVisitas"]
        add("aps.acs.visitas.realizadas", "APS", "Visitas ACS realizadas", v["realizadas"], str(v["realizadas"]), "visitas", v["ref"], "SIAPS")
        add("aps.acs.visitas.ausentes", "APS", "Visitas ACS com ausência", v["ausentes"], str(v["ausentes"]), "visitas", v["ref"], "SIAPS")
        add("aps.acs.visitas.recusadas", "APS", "Visitas ACS recusadas", v["recusadas"], str(v["recusadas"]), "visitas", v["ref"], "SIAPS")
    if aps.get("ausencia"):
        add("aps.ausencia.producao", "APS", "Equipes sem envio de produção", aps["ausencia"]["total"], str(aps["ausencia"]["total"]), "equipes", aps["ausencia"]["ref"], "SIAPS")
    if aps.get("solicitacoes"):
        s = aps["solicitacoes"]
        add("aps.solicitacoes.total", "APS", "Solicitações de credenciamento", s["total"], str(s["total"]), "solicitações", s["ref"], "SIAPS")
        add("aps.solicitacoes.credenciadas", "APS", "Solicitações credenciadas", s["credenciadas"], str(s["credenciadas"]), "solicitações", s["ref"], "SIAPS")
        add("aps.solicitacoes.solicitadas", "APS", "Solicitações em andamento", s["solicitadas"], str(s["solicitadas"]), "solicitações", s["ref"], "SIAPS")
    if mac.get("teto"):
        t = mac["teto"]
        add("mac.teto.semIncentivos", "MAC", "Teto MAC anual (sem incentivos)", t.get("semIncentivos", 0), "", "R$", t.get("periodo", ""), "SISMAC")
        add("mac.teto.incentivos", "MAC", "Incentivos MAC anuais", t.get("incentivos", 0), "", "R$", t.get("periodo", ""), "SISMAC")
        add("mac.teto.total", "MAC", "Teto MAC anual (com incentivos)", t.get("total", 0), "", "R$", t.get("periodo", ""), "SISMAC")
    if mac.get("sia"):
        s = mac["sia"]
        add("mac.sia.apresentada", "MAC", "Produção ambulatorial apresentada", s["apresentada"], str(s["apresentada"]), "procedimentos", s["ano"], "DATASUS/SIA")
        add("mac.sia.aprovada", "MAC", "Produção ambulatorial aprovada", s["aprovada"], str(s["aprovada"]), "procedimentos", s["ano"], "DATASUS/SIA")
        add("mac.sia.valorAprovado", "MAC", "Valor aprovado SIA", s["valorAprovado"], "", "R$", s["ano"], "DATASUS/SIA")
    if mac.get("sih"):
        s = mac["sih"]
        add("mac.sih.aih", "MAC", "AIH aprovadas", s["aih"], str(s["aih"]), "AIH", s["ano"], "DATASUS/SIH")
        add("mac.sih.valor", "MAC", "Valor aprovado SIH", s["valor"], "", "R$", s["ano"], "DATASUS/SIH")
    if mac.get("total"):
        add("mac.total", "MAC", "Produção MAC aprovada (SIA+SIH)", mac["total"], "", "R$", mac.get("sia", {}).get("ano", ""), "DATASUS")
    if mac.get("oncologia"):
        o = mac["oncologia"]
        add("mac.onco.tempoMedio", "MAC", "Tempo médio até início do tratamento", o.get("tempoMedio", 0), "", "dias", str(o.get("ano", "")), "Painel ONCO")
        add("mac.onco.pct60", "MAC", "Conformidade Lei 60 dias", o.get("pct60", 0), "", "%", str(o.get("ano", "")), "Painel ONCO")

    vig = payload.get("vigilancia") or {}
    if vig:
        ano_corrente = int(str(payload["geradoEm"])[:4])

        def ultimo(serie, campo):
            serie = serie or []
            if not serie:
                return None
            fechados = [item for item in serie if int(item.get("ano", 0)) < ano_corrente]
            return (fechados or serie)[-1]

        geral = ultimo((vig.get("mortalidade") or {}).get("geral"), "obitos")
        if geral:
            add("vig.mortalidade.geral", "VIGILÂNCIA", "Óbitos gerais (ano fechado)", geral["obitos"], str(geral["obitos"]), "óbitos", str(geral["ano"]), "SIM/DATASUS")
        infantil = ultimo((vig.get("mortalidade") or {}).get("infantil"), "obitos")
        if infantil:
            add("vig.mortalidade.infantil", "VIGILÂNCIA", "Óbitos infantis (ano fechado)", infantil["obitos"], str(infantil["obitos"]), "óbitos", str(infantil["ano"]), "SIM/DATASUS")
        tb = ultimo(vig.get("tuberculose"), "valor")
        if tb:
            add("vig.tuberculose", "VIGILÂNCIA", "Incidência de tuberculose", tb["valor"], f"{tb['valor']:.2f}/100 mil", "/100 mil", str(tb["ano"]), "SINAN/DATASUS")
        han = ultimo(vig.get("hanseniase"), "valor")
        if han:
            add("vig.hanseniase", "VIGILÂNCIA", "Incidência de hanseníase", han["valor"], f"{han['valor']:.2f}/100 mil", "/100 mil", str(han["ano"]), "SINAN/DATASUS")
        dengue = (vig.get("dengue") or [None])[-1]
        if dengue:
            add("vig.dengue", "VIGILÂNCIA", "Casos de dengue", dengue["casos"], str(dengue["casos"]), "casos", str(dengue["ano"]), "SINAN/DATASUS")
        srag = vig.get("srag")
        if srag:
            add("vig.srag", "VIGILÂNCIA", "Casos de SRAG", srag["total"], str(srag["total"]), "casos", str(srag["ano"]), "SIVEP-Gripe")
            add("vig.srag.incidencia", "VIGILÂNCIA", "Incidência de SRAG", srag["incidencia"], f"{srag['incidencia']:.2f}/100 mil", "/100 mil", str(srag["ano"]), "SIVEP-Gripe")
        nascidos = vig.get("nascidos")
        if nascidos:
            add("vig.nascidos", "VIGILÂNCIA", "Nascidos vivos", nascidos["total"], str(nascidos["total"]), "nascimentos", str(nascidos["ano"]), "SINASC/DATASUS")
        internacoes = vig.get("internacoes")
        if internacoes:
            add("vig.internacoes", "VIGILÂNCIA", "Internações hospitalares", internacoes["total"], str(internacoes["total"]), "internações", str(internacoes["ano"]), "SIH/DATASUS")
    return linhas


def series_do_payload(payload: dict) -> list[tuple]:
    """Lista (nome, referencia, valor, parte, ordem)."""
    linhas: list[tuple] = []
    aps = payload.get("aps", {})
    mac = payload.get("mac", {})

    repasses = aps.get("repasses", {}).get("historico", {})
    for i, (rotulo, valor) in enumerate(zip(repasses.get("labels", []), repasses.get("valores", []))):
        linhas.append(("aps.repasses", rotulo, valor, "repasse", i))
    for i, valor in enumerate(repasses.get("mediaMovel", [])):
        linhas.append(("aps.repasses", repasses["labels"][i], valor, "media", i))

    for i, item in enumerate(aps.get("acsVisitas", {}).get("historico", [])):
        for parte in ("realizadas", "ausentes", "recusadas"):
            linhas.append(("aps.acs.visitas", item["ref"], item[parte], parte, i))

    for i, item in enumerate(mac.get("mensal", [])):
        linhas.append(("mac.mensal", item["ref"], item["sia"], "sia", i))
        linhas.append(("mac.mensal", item["ref"], item["sih"], "sih", i))

    for i, item in enumerate(mac.get("oncologia", {}).get("historico", [])):
        linhas.append(("mac.onco.historico", str(item["ano"]), item["tempoMedio"], "tempo", i))
        linhas.append(("mac.onco.historico", str(item["ano"]), item["pct60"], "pct60", i))

    vig = payload.get("vigilancia") or {}
    for chave in ("geral", "infantil"):
        for item in (vig.get("mortalidade") or {}).get(chave, []):
            linhas.append((f"vig.mortalidade.{chave}", str(item["ano"]), item["obitos"], "obitos", item["ano"]))
    for chave in ("tuberculose", "hanseniase"):
        for item in vig.get(chave, []):
            linhas.append((f"vig.{chave}", str(item["ano"]), item["valor"], "incidencia", item["ano"]))
    for item in vig.get("dengue", []):
        linhas.append(("vig.dengue", str(item["ano"]), item["casos"], "casos", item["ano"]))
    for item in vig.get("vacinacao", {}).get("vacinas", []):
        linhas.append(("vig.vacinacao", str(vig["vacinacao"]["ano"]), item["cobertura"], item["nome"], 0))
    internacoes = vig.get("internacoes") or {}
    for i, item in enumerate(internacoes.get("capitulos", [])):
        linhas.append(("vig.internacoes", item["capitulo"], item["internacoes"], str(internacoes.get("ano", "")), i))

    return linhas


def gravar_banco(payload: dict) -> None:
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    agora = payload["geradoEm"]
    con = sqlite3.connect(BANCO)
    try:
        con.executescript(ESQUEMA)
        cur = con.cursor()
        cur.execute(
            "INSERT INTO coletas (iniciado_em, concluido_em, status, mensagem) VALUES (?, ?, ?, ?)",
            (payload.get("iniciadoEm", agora), agora, payload.get("status", "ok"), "; ".join(payload.get("avisos", []))),
        )
        cur.executemany(
            """INSERT INTO indicadores (chave, grupo, rotulo, valor, valor_texto, unidade, referencia, fonte, atualizado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chave) DO UPDATE SET
                 grupo=excluded.grupo, rotulo=excluded.rotulo, valor=excluded.valor,
                 valor_texto=excluded.valor_texto, unidade=excluded.unidade,
                 referencia=excluded.referencia, fonte=excluded.fonte, atualizado_em=excluded.atualizado_em""",
            [(*linha, agora) for linha in indicadores_do_payload(payload)],
        )
        cur.executemany(
            "INSERT OR REPLACE INTO historico (chave, coletado_em, valor) VALUES (?, ?, ?)",
            [(linha[0], agora, linha[3]) for linha in indicadores_do_payload(payload)],
        )
        cur.execute("DELETE FROM series")
        cur.executemany(
            "INSERT OR REPLACE INTO series (nome, referencia, valor, parte, ordem) VALUES (?, ?, ?, ?, ?)",
            series_do_payload(payload),
        )
        cur.execute(
            "INSERT INTO painel (id, json, gerado_em) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET json=excluded.json, gerado_em=excluded.gerado_em",
            (json.dumps(payload, ensure_ascii=False), agora),
        )
        con.commit()
    finally:
        con.close()


def gravar_cache(payload: dict) -> None:
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    conteudo = (
        "/* Cache gerado automaticamente pelo coletor - nao editar. */\n"
        "window.__PAINEL_DADOS__ = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    CACHE_JS.write_text(conteudo, encoding="utf-8")


def ler_ultimo_payload() -> dict | None:
    if not BANCO.exists():
        return None
    try:
        con = sqlite3.connect(BANCO)
        try:
            linha = con.execute("SELECT json FROM painel WHERE id = 1").fetchone()
        finally:
            con.close()
        return json.loads(linha[0]) if linha else None
    except Exception:  # noqa: BLE001
        return None


def limpar_dados() -> None:
    """Apaga os dados coletados (usado ao trocar o município monitorado)."""
    if BANCO.exists():
        con = sqlite3.connect(BANCO)
        try:
            con.executescript(
                "DELETE FROM painel; DELETE FROM indicadores; DELETE FROM historico;"
                "DELETE FROM series; DELETE FROM coletas;"
            )
            con.commit()
        finally:
            con.close()
    CACHE_JS.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def coletar() -> dict:
    cfg = configuracao.carregar()
    configuracao.gravar_js(cfg)
    ambiente = aplicar_config(configuracao.ambiente(cfg))
    iniciado = datetime.now(fuso_local())
    avisos: list[str] = []
    aps = coletar_aps(avisos)
    mac = coletar_mac(avisos)
    vigilancia = coletar_vigilancia(avisos)

    if not (aps.get("cobertura") or mac.get("sia")):
        raise RuntimeError("Nenhum dado essencial foi obtido dos painéis.")

    payload = {
        "municipio": ambiente["municipio"],
        "fonte": "Painéis CONASEMS",
        "urls": {"aps": ambiente["urlAps"], "mac": ambiente["urlMac"], "vigilancia": ambiente["urlVig"]},
        "iniciadoEm": iniciado.isoformat(),
        "geradoEm": datetime.now(fuso_local()).isoformat(),
        "status": "parcial" if avisos else "ok",
        "online": True,
        "avisos": avisos,
        "aps": aps,
        "mac": mac,
        "vigilancia": vigilancia,
    }
    return payload


def atualizar() -> dict:
    payload = coletar()
    gravar_banco(payload)
    gravar_cache(payload)
    return payload


def main() -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    configuracao.garantir()
    ambiente = configuracao.ambiente()
    municipio = ambiente["municipio"]
    print(f"Consultando os Painéis CONASEMS ({municipio['nome']}/{municipio['uf']} - IBGE {municipio['ibge']})...")
    payload = atualizar()
    resumo = {
        "municipio": payload.get("municipio"),
        "geradoEm": payload["geradoEm"],
        "status": payload["status"],
        "coberturaAPS": payload.get("aps", {}).get("cobertura", {}).get("aps"),
        "macTotal": payload.get("mac", {}).get("total"),
        "avisos": payload.get("avisos", []),
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    print(f"Banco: {BANCO}")
    print(f"Cache: {CACHE_JS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
