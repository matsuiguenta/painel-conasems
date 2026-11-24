#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuração do painel CONASEMS.

Guarda, em `dados/config.json`, o município monitorado e o logo da Secretaria
de Saúde. Gera também `dados/config.js`, carregado pelo painel para exibir o
logo mesmo quando a página é aberta diretamente pelo `file://`.

O município também pode ser definido por variáveis de ambiente na primeira
execução (útil no Docker/Coolify):

    PAINEL_IBGE=410240
    PAINEL_MUNICIPIO=Bandeirantes
    PAINEL_UF=PR
"""

from __future__ import annotations

import base64
import json
import os
import re
import unicodedata
import urllib.parse
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PASTA_DADOS = Path(os.environ.get("PAINEL_DADOS") or (RAIZ / "dados")).resolve()
ARQ_CONFIG = PASTA_DADOS / "config.json"
CONFIG_JS = PASTA_DADOS / "config.js"
LISTA_MUNICIPIOS = RAIZ / "assets" / "municipios.json"
BASE_CONASEMS = "https://paineis.conasems.org.br"

MUNICIPIO_PADRAO = {"nome": "Bandeirantes", "uf": "PR", "ibge": "4102406"}
LOGO_MAXIMO = 2_500_000  # 2,5 MB

# Telas do painel, na ordem padrão. Os IDs são usados pelo app.js e pela
# configuração salva (ordem e telas ativas).
SLIDES = [
    {"id": "capa", "titulo": "Capa — visão geral"},
    {"id": "cobertura", "titulo": "Cobertura da APS"},
    {"id": "producao-aps", "titulo": "Produção da APS"},
    {"id": "financiamento-aps", "titulo": "Financiamento da APS"},
    {"id": "visitas-acs", "titulo": "Visitas domiciliares dos ACS"},
    {"id": "credenciamento", "titulo": "Credenciamento e cofinanciamento"},
    {"id": "mac-teto", "titulo": "Teto MAC e produção"},
    {"id": "sia-sih", "titulo": "Produção ambulatorial e hospitalar"},
    {"id": "onco-mental", "titulo": "Oncologia e saúde mental"},
    {"id": "vigilancia", "titulo": "Vigilância em saúde"},
    {"id": "rede", "titulo": "Rede assistencial"},
]

EXTENSOES_LOGO = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

_INDICE_MUNICIPIOS: dict[str, dict] | None = None


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------

def agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalizar_nome(nome: str) -> str:
    """'Cornélio Procópio' -> 'CORNELIO PROCOPIO' (usado na URL do painel)."""
    texto = unicodedata.normalize("NFKD", str(nome or ""))
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^A-Za-z0-9 ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip().upper()


def _resolver_municipio(dados: dict) -> dict | None:
    ibge = str(dados.get("ibge") or "").strip()
    if not ibge.isdigit():
        return None
    nome = str(dados.get("nome") or "").strip()
    uf = str(dados.get("uf") or "").strip().upper()
    if not nome or len(uf) != 2:
        return None
    return {"ibge": ibge, "nome": nome, "uf": uf}


def listar_municipios() -> list[list[str]]:
    """Lista [IBGE, nome, UF] de todos os municípios brasileiros."""
    try:
        dados = json.loads(LISTA_MUNICIPIOS.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else []
    except Exception:  # noqa: BLE001
        return []


def _indice() -> dict[str, dict]:
    global _INDICE_MUNICIPIOS
    if _INDICE_MUNICIPIOS is None:
        _INDICE_MUNICIPIOS = {}
        for item in listar_municipios():
            try:
                ibge, nome, uf = str(item[0]), str(item[1]), str(item[2])
            except (TypeError, IndexError):
                continue
            _INDICE_MUNICIPIOS[ibge] = {"ibge": ibge, "nome": nome, "uf": uf}
    return _INDICE_MUNICIPIOS


def buscar_municipio(ibge: str) -> dict | None:
    return _indice().get(str(ibge or "").strip())


def slides_padrao() -> list[dict]:
    return [{"id": item["id"], "ativo": True} for item in SLIDES]


def normalizar_slides(valor) -> list[dict]:
    """Valida ordem/ativação das telas, completando IDs ausentes."""
    validos = {item["id"] for item in SLIDES}
    ordem: list[dict] = []
    vistos: set[str] = set()

    if isinstance(valor, list):
        for item in valor:
            if isinstance(item, str):
                slide_id, ativo = item, True
            elif isinstance(item, dict):
                slide_id = str(item.get("id") or "").strip()
                ativo = item.get("ativo", True) is not False
            else:
                continue
            if slide_id in validos and slide_id not in vistos:
                vistos.add(slide_id)
                ordem.append({"id": slide_id, "ativo": ativo})

    # Telas novas (ou configuração antiga sem slides) entram no fim, ativas.
    for item in SLIDES:
        if item["id"] not in vistos:
            ordem.append({"id": item["id"], "ativo": True})

    # O painel precisa de pelo menos uma tela ativa.
    if not any(item["ativo"] for item in ordem):
        ordem[0]["ativo"] = True
    return ordem


def _municipio_inicial() -> dict:
    ibge = os.environ.get("PAINEL_IBGE", "").strip()
    nome = os.environ.get("PAINEL_MUNICIPIO", "").strip()
    uf = os.environ.get("PAINEL_UF", "").strip().upper()
    if ibge and nome and uf:
        return buscar_municipio(ibge) or {"ibge": ibge, "nome": nome, "uf": uf}
    return dict(MUNICIPIO_PADRAO)


# ---------------------------------------------------------------------------
# configuração
# ---------------------------------------------------------------------------

def carregar() -> dict:
    """Lê a configuração salva; se não existir, usa ambiente/padrão."""
    cfg = {
        "municipio": _municipio_inicial(),
        "logo": None,
        "logoAtualizadoEm": None,
        "slides": slides_padrao(),
        "atualizadoEm": None,
    }

    if ARQ_CONFIG.exists():
        try:
            salvo = json.loads(ARQ_CONFIG.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            salvo = {}
        if isinstance(salvo, dict):
            municipio = _resolver_municipio(salvo.get("municipio") or {})
            if municipio:
                oficial = buscar_municipio(municipio["ibge"])
                cfg["municipio"] = oficial or municipio
            logo = salvo.get("logo")
            cfg["logoAtualizadoEm"] = salvo.get("logoAtualizadoEm")
            if isinstance(logo, str) and logo.startswith("dados/logo."):
                arquivo = PASTA_DADOS / Path(logo).name
                if arquivo.is_file():
                    cfg["logo"] = logo
                else:
                    cfg["logoAtualizadoEm"] = None
            cfg["slides"] = normalizar_slides(salvo.get("slides"))
            cfg["atualizadoEm"] = salvo.get("atualizadoEm")
    return cfg


def salvar(cfg: dict) -> dict:
    """Grava config.json e regenera config.js."""
    municipio = _resolver_municipio(cfg.get("municipio") or {})
    if not municipio:
        raise ValueError("Município inválido.")
    logo = cfg.get("logo")
    if not (isinstance(logo, str) and logo.startswith("dados/logo.")):
        logo = None

    saida = {
        "municipio": municipio,
        "logo": logo,
        "logoAtualizadoEm": cfg.get("logoAtualizadoEm"),
        "slides": normalizar_slides(cfg.get("slides")),
        "atualizadoEm": agora_iso(),
    }
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    ARQ_CONFIG.write_text(
        json.dumps(saida, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    gravar_js(saida)
    return saida


def gravar_js(cfg: dict) -> None:
    """Gera dados/config.js para o painel (inclusive no modo file://)."""
    dados = {
        "municipio": cfg.get("municipio") or dict(MUNICIPIO_PADRAO),
        "logo": cfg.get("logo"),
        "logoVersao": cfg.get("logoAtualizadoEm"),
        "slides": normalizar_slides(cfg.get("slides")),
        "atualizadoEm": cfg.get("atualizadoEm"),
    }
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    CONFIG_JS.write_text(
        "/* Arquivo gerado por configuracao.py - nao editar. */\n"
        "window.__PAINEL_CONFIG__ = "
        + json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def resumo(cfg: dict | None = None) -> dict:
    cfg = cfg or carregar()
    return {
        "municipio": cfg.get("municipio"),
        "logo": cfg.get("logo"),
        "logoVersao": cfg.get("logoAtualizadoEm"),
        "slides": cfg.get("slides") or slides_padrao(),
        "atualizadoEm": cfg.get("atualizadoEm"),
    }


def ambiente(cfg: dict | None = None) -> dict:
    """Município + URLs dos três painéis do CONASEMS.

    O IBGE oficial tem 7 dígitos (ex.: 4102406). Os Painéis CONASEMS usam o
    código de 6 dígitos, sem o dígito verificador (ex.: 410240).
    """
    cfg = cfg or carregar()
    municipio = cfg["municipio"]
    ibge = str(municipio["ibge"])
    codigo = ibge[:6] if len(ibge) > 6 else ibge
    slug = urllib.parse.quote(normalizar_nome(municipio["nome"]), safe="")
    return {
        "municipio": municipio,
        "codigoConasems": codigo,
        "nome_url": slug,
        "urlAps": f"{BASE_CONASEMS}/atencao_basica/{codigo}/{slug}/cit",
        "urlMac": f"{BASE_CONASEMS}/producao/{codigo}/{slug}/cit",
        "urlVig": f"{BASE_CONASEMS}/vigilancia/{codigo}/{slug}/cit",
        "urlRede": f"{BASE_CONASEMS}/rede/{codigo}/{slug}/cit",
    }


# ---------------------------------------------------------------------------
# logo
# ---------------------------------------------------------------------------

def _remover_arquivos_logo() -> None:
    try:
        for arquivo in PASTA_DADOS.glob("logo.*"):
            if arquivo.is_file():
                arquivo.unlink()
    except Exception:  # noqa: BLE001
        pass


def salvar_logo(cfg: dict, data_url: str) -> dict:
    """Salva o logo enviado como data URL (base64) e devolve a config."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        raise ValueError("Envie uma imagem PNG, JPG, WEBP ou SVG.")
    cabecalho, separador, conteudo = data_url.partition(",")
    if not separador or ";base64" not in cabecalho.lower():
        raise ValueError("Formato de imagem não suportado.")
    if len(conteudo) > LOGO_MAXIMO * 2:
        raise ValueError("O logo deve ter no máximo 2,5 MB.")
    tipo = cabecalho[5:].split(";")[0].strip().lower()
    extensao = EXTENSOES_LOGO.get(tipo)
    if not extensao:
        raise ValueError("Use uma imagem PNG, JPG, WEBP ou SVG.")
    try:
        bruto = base64.b64decode(conteudo, validate=True)
    except Exception as erro:  # noqa: BLE001
        raise ValueError("Não foi possível ler a imagem enviada.") from erro
    if not bruto:
        raise ValueError("A imagem enviada está vazia.")
    if len(bruto) > LOGO_MAXIMO:
        raise ValueError("O logo deve ter no máximo 2,5 MB.")

    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    _remover_arquivos_logo()
    (PASTA_DADOS / f"logo{extensao}").write_bytes(bruto)

    novo = dict(cfg)
    novo["logo"] = f"dados/logo{extensao}"
    novo["logoAtualizadoEm"] = agora_iso()
    return novo


def remover_logo(cfg: dict) -> dict:
    _remover_arquivos_logo()
    novo = dict(cfg)
    novo["logo"] = None
    novo["logoAtualizadoEm"] = None
    return novo


# ---------------------------------------------------------------------------
# inicialização
# ---------------------------------------------------------------------------

def garantir() -> dict:
    """Cria config.json/config.js na primeira execução e devolve a config."""
    if not ARQ_CONFIG.exists():
        cfg = salvar(carregar())
    else:
        cfg = carregar()
        gravar_js(cfg)
    return cfg


if __name__ == "__main__":
    config = carregar()
    print(json.dumps(config, ensure_ascii=False, indent=2))
    print("Painel:", ambiente(config)["urlAps"])
