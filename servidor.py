#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor local do painel CONASEMS.

Serve o dashboard, o painel de configuração e uma API simples:

    GET  /                      -> painel (TV)
    GET  /config                -> configuração (município e logo)
    GET  /api/dados             -> último resumo salvo no banco (rápido)
    GET  /api/dados?refresh=1   -> tenta atualizar se os dados estiverem velhos
    GET  /api/dados?force=1     -> força uma nova coleta agora
    GET  /api/status            -> situação da última coleta
    GET  /api/config            -> configuração atual
    GET  /api/municipios        -> lista de municípios do IBGE
    POST /api/config            -> salva município/logo e coleta os dados

O servidor atualiza os dados sozinho de tempos em tempos, para que a TV da
secretaria permaneça sempre com informações recentes.

Uso local (Windows):
    python servidor.py                 # porta 8090 e abre o navegador
    python servidor.py --tv            # modo TV (sem abrir navegador)

Uso em container (Linux/Coolify):
    python servidor.py --tv --host 0.0.0.0 --porta 8090
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import coletor
import configuracao

RAIZ = Path(__file__).resolve().parent
PASTA_ASSETS = (RAIZ / "assets").resolve()
PORTA_PADRAO = int(os.environ.get("PORT", "8090"))
INTERVALO_MINUTOS = int(os.environ.get("PAINEL_INTERVALO_MINUTOS", "20"))
MINIMO_ENTRE_COLETAS = 180      # segundos entre coletas disparadas pela página
LIMITE_CORPO = 6_000_000        # ~4,5 MB em base64 (logo de até 2,5 MB)

TRAVA = threading.Lock()
TRAVA_CONFIG = threading.Lock()
ESTADO = {
    "ultima_tentativa": 0.0,
    "ultimo_sucesso": 0.0,
    "ultimo_erro": None,
    "coletando": False,
}


def agora_iso() -> str:
    return datetime.now(coletor.fuso_local()).isoformat()


def carregar() -> dict | None:
    return coletor.ler_ultimo_payload()


def atualizar(forcar: bool = False) -> dict | None:
    """Executa a coleta respeitando o intervalo mínimo entre tentativas."""
    with TRAVA:
        agora = time.time()
        if not forcar and (agora - ESTADO["ultima_tentativa"]) < MINIMO_ENTRE_COLETAS:
            return carregar()
        ESTADO["ultima_tentativa"] = agora
        ESTADO["coletando"] = True
        try:
            payload = coletor.atualizar()
            ESTADO["ultimo_sucesso"] = time.time()
            ESTADO["ultimo_erro"] = None
            print(f"[{agora_iso()}] Dados de {payload['municipio']['nome']}/{payload['municipio']['uf']} atualizados com sucesso.")
            return payload
        except Exception as erro:  # noqa: BLE001
            ESTADO["ultimo_erro"] = str(erro)
            print(f"[{agora_iso()}] Falha ao atualizar: {erro}", file=sys.stderr)
            dados = carregar()
            if dados:
                dados = dict(dados)
                dados["online"] = False
                dados["avisoOffline"] = (
                    "Sem conexão com os Painéis CONASEMS. Exibindo a última "
                    f"coleta de {dados.get('geradoEm', '')[:10]}."
                )
            return dados
        finally:
            ESTADO["coletando"] = False


def deve_atualizar(payload: dict | None, minutos: int = 5) -> bool:
    if not payload:
        return True
    try:
        gerado = datetime.fromisoformat(payload["geradoEm"])
        referencia = datetime.now(coletor.fuso_local())
        return (referencia - gerado).total_seconds() > minutos * 60
    except Exception:  # noqa: BLE001
        return True


class Manipulador(BaseHTTPRequestHandler):
    server_version = "PainelConasems/2.0"

    def log_message(self, formato, *args):  # silencia o log padrão
        pass

    # ------------------------------------------------------------------
    def _json(self, dados, codigo: int = 200) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, caminho: Path) -> None:
        if not caminho.is_file():
            self.send_error(404, "Arquivo não encontrado")
            return
        tipo, _ = mimetypes.guess_type(str(caminho))
        tipo = tipo or "application/octet-stream"
        if tipo.startswith("text/") or tipo in {"application/javascript", "application/json", "image/svg+xml"}:
            tipo += "; charset=utf-8"
        conteudo = caminho.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(conteudo)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(conteudo)

    def _ler_json(self, limite: int = LIMITE_CORPO):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho <= 0:
            raise ValueError("Corpo da requisição vazio.")
        if tamanho > limite:
            raise ValueError("Arquivo muito grande (limite de 2,5 MB para o logo).")
        try:
            return json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as erro:
            raise ValueError("JSON inválido.") from erro

    def _servir_dado(self, nome: str) -> None:
        self._arquivo(configuracao.PASTA_DADOS / nome)

    # ------------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        rota = url.path
        consulta = parse_qs(url.query)

        if rota == "/api/dados":
            forcar = consulta.get("force", ["0"])[0] in {"1", "true"}
            atualizar_agora = consulta.get("refresh", ["0"])[0] in {"1", "true"}
            dados = carregar()
            if forcar:
                dados = atualizar(forcar=True) or dados
            elif atualizar_agora and deve_atualizar(dados):
                dados = atualizar() or dados
            if not dados:
                # primeira execução: coleta síncrona
                dados = atualizar(forcar=True)
            if not dados:
                self._json({"erro": "Não há dados disponíveis.", "detalhe": ESTADO["ultimo_erro"]}, 503)
                return
            dados = dict(dados)
            dados["config"] = configuracao.resumo()
            self._json(dados)
            return

        if rota == "/api/config":
            cfg = configuracao.carregar()
            dados = carregar() or {}
            self._json(
                {
                    "config": configuracao.resumo(cfg),
                    "geradoEm": dados.get("geradoEm"),
                    "status": dados.get("status"),
                    "avisos": dados.get("avisos", []),
                    "coletando": ESTADO["coletando"],
                    "ultimoErro": ESTADO["ultimo_erro"],
                }
            )
            return

        if rota == "/api/municipios":
            self._json(configuracao.listar_municipios())
            return

        if rota == "/api/status":
            dados = carregar() or {}
            cfg = configuracao.carregar()
            self._json(
                {
                    "servidor": "no ar",
                    "porta": self.server.server_address[1],
                    "municipio": cfg["municipio"],
                    "ultimoSucesso": ESTADO["ultimo_sucesso"],
                    "ultimaTentativa": ESTADO["ultima_tentativa"],
                    "coletando": ESTADO["coletando"],
                    "ultimoErro": ESTADO["ultimo_erro"],
                    "geradoEm": dados.get("geradoEm"),
                    "online": dados.get("online", True),
                    "intervaloMinutos": INTERVALO_MINUTOS,
                }
            )
            return

        if rota == "/api/atualizar":
            dados = atualizar(forcar=True)
            self._json(dados or {"erro": "Falha ao atualizar"}, 200 if dados else 503)
            return

        # ---------------------------------------------------------- estáticos
        if rota in {"", "/", "/index.html"}:
            self._arquivo(RAIZ / "index.html")
            return
        if rota in {"/config", "/config.html"}:
            self._arquivo(RAIZ / "config.html")
            return
        if rota.startswith("/assets/"):
            destino = (RAIZ / rota.lstrip("/")).resolve()
            try:
                destino.relative_to(PASTA_ASSETS)
            except ValueError:
                self.send_error(404, "Arquivo não encontrado")
                return
            self._arquivo(destino)
            return
        if rota in {"/dados/cache.js", "/dados/config.js"}:
            self._servir_dado(rota.rsplit("/", 1)[-1])
            return
        cfg = configuracao.carregar()
        if cfg.get("logo") and rota == "/" + cfg["logo"]:
            self._servir_dado(Path(cfg["logo"]).name)
            return

        self.send_error(404, "Arquivo não encontrado")

    # ------------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/api/config":
            self.send_error(404, "Rota não encontrada")
            return

        try:
            corpo = self._ler_json()
        except ValueError as erro:
            self._json({"erro": str(erro)}, 400)
            return
        if not isinstance(corpo, dict):
            self._json({"erro": "Dados inválidos."}, 400)
            return

        with TRAVA_CONFIG:
            atual = configuracao.carregar()
            anterior = atual["municipio"]["ibge"]

            ibge = str(corpo.get("ibge") or "").strip()
            if ibge:
                municipio = configuracao.buscar_municipio(ibge)
                if not municipio:
                    self._json({"erro": f"Município com IBGE {ibge} não encontrado."}, 400)
                    return
                atual["municipio"] = municipio

            try:
                if corpo.get("logoDataUrl"):
                    atual = configuracao.salvar_logo(atual, corpo["logoDataUrl"])
                elif corpo.get("removerLogo"):
                    atual = configuracao.remover_logo(atual)
            except ValueError as erro:
                self._json({"erro": str(erro)}, 400)
                return

            try:
                atual = configuracao.salvar(atual)
            except ValueError as erro:
                self._json({"erro": str(erro)}, 400)
                return

            mudou_municipio = atual["municipio"]["ibge"] != anterior
            if mudou_municipio:
                # Os dados do município anterior não devem aparecer no novo.
                coletor.limpar_dados()
                with TRAVA:
                    ESTADO["ultima_tentativa"] = 0.0
                    ESTADO["ultimo_sucesso"] = 0.0
                    ESTADO["ultimo_erro"] = None

            dados = carregar()
            if mudou_municipio or not dados:
                dados = atualizar(forcar=True)

            resposta = {
                "ok": bool(dados),
                "coletou": mudou_municipio or not dados,
                "config": configuracao.resumo(atual),
                "geradoEm": (dados or {}).get("geradoEm"),
                "status": (dados or {}).get("status", "erro"),
                "avisos": (dados or {}).get("avisos", []),
                "erro": ESTADO["ultimo_erro"] if not dados else None,
            }
            self._json(resposta, 200 if dados else 502)


def ciclo_de_fundo(intervalo_minutos: int) -> None:
    while True:
        time.sleep(intervalo_minutos * 60)
        try:
            atualizar(forcar=True)
        except Exception as erro:  # noqa: BLE001
            print(f"Falha na atualização de fundo: {erro}", file=sys.stderr)


def main() -> int:
    global INTERVALO_MINUTOS

    parser = argparse.ArgumentParser(description="Painel CONASEMS - APS, MAC e Vigilância")
    parser.add_argument("--porta", type=int, default=PORTA_PADRAO)
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--intervalo", type=int, default=INTERVALO_MINUTOS, help="minutos entre atualizações automáticas")
    parser.add_argument("--tv", action="store_true", help="não abre o navegador (modo TV)")
    parser.add_argument("--abrir", action="store_true", default=False, help="abre o navegador ao iniciar")
    args = parser.parse_args()

    INTERVALO_MINUTOS = max(1, args.intervalo)

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    config = configuracao.garantir()
    municipio = config["municipio"]

    # Primeira carga: se o banco estiver vazio, coleta antes de abrir o painel.
    if carregar() is None:
        print("Banco vazio - realizando a primeira coleta...")
        atualizar(forcar=True)

    threading.Thread(target=ciclo_de_fundo, args=(INTERVALO_MINUTOS,), daemon=True).start()

    servidor = ThreadingHTTPServer((args.host, args.porta), Manipulador)
    endereco = f"http://localhost:{args.porta}/"
    print(f"Painel de {municipio['nome']}/{municipio['uf']} disponível em {endereco}")
    print(f"Configuração: {endereco}config")
    print(f"Atualização automática a cada {INTERVALO_MINUTOS} min. Ctrl+C para encerrar.")

    if not args.tv:
        threading.Timer(1.2, lambda: webbrowser.open(endereco)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
