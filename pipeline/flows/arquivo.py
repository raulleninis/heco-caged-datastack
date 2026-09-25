"""
Repositório do arquivo de boletins (F15): git + estado de envio.

O arquivo é um repositório PRIVADO e SEPARADO deste (D07). O pipeline só
adiciona arquivos e dá push; o Netlify publica. O histórico do git é o backup
do que foi enviado (os boletins não se regeneram — ver boletim.py).

O estado de envio (envios.json) vive AQUI, não no warehouse (D03): se
vivesse no warehouse, apagar o .duckdb faria o próximo run reenviar todas as
competências à lista inteira. Fica na raiz do repositório, fora de public/,
então o site não o publica.

Cada gravação de estado é um commit com push. Se o push falhar, a função
levanta erro — o chamador nunca segue adiante (enviar e-mail) sem o estado
estar gravado no remoto.
"""

import hashlib
import html
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from boletim import nome_competencia

ENVIOS = "envios.json"
PUBLIC = "public"


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Arquivo:
    repo_url: str
    diretorio: Path
    branch: str = "main"
    deploy_key: Path | None = None

    # ------------------------------------------------------------------ git

    def _env(self) -> dict:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if self.deploy_key:
            conhecidos = self.diretorio.parent / "arquivo_known_hosts"
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {self.deploy_key} -o IdentitiesOnly=yes "
                f"-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={conhecidos}"
            )
        return env

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        cmd = [
            "git", "-c", "user.name=caged-pipeline", "-c", "user.email=pipeline@localhost", *args,
        ]
        r = subprocess.run(
            cmd, cwd=cwd or self.diretorio, env=self._env(), capture_output=True, text=True
        )
        if r.returncode != 0:
            # stderr do git pode citar a URL do remoto; não cita a chave.
            raise RuntimeError(f"git {args[0]} falhou: {r.stderr.strip()[:500]}")
        return r.stdout

    def sincronizar(self) -> None:
        """Deixa o clone local idêntico ao remoto. Qualquer coisa local não
        enviada é descartada de propósito: o remoto é a verdade (um `enviado`
        que não chegou a subir NÃO conta — o estado seguro é 'enviando')."""
        if not (self.diretorio / ".git").exists():
            self.diretorio.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--branch", self.branch, self.repo_url, str(self.diretorio),
                      cwd=self.diretorio.parent)
            return
        self._git("fetch", "origin", self.branch)
        self._git("reset", "--hard", f"origin/{self.branch}")
        self._git("clean", "-fd")

    def _commit_push(self, mensagem: str) -> None:
        self._git("add", "-A")
        if not self._git("status", "--porcelain").strip():
            return
        self._git("commit", "-m", mensagem)
        self._git("push", "origin", f"HEAD:{self.branch}")

    # --------------------------------------------------------------- estado

    def envios(self) -> dict[str, dict]:
        caminho = self.diretorio / ENVIOS
        if not caminho.exists():
            return {}
        return json.loads(caminho.read_text(encoding="utf-8"))

    def _pasta(self, competencia: str) -> Path:
        return self.diretorio / PUBLIC / f"{competencia[:4]}-{competencia[4:]}"

    def arquivos_da(self, competencia: str) -> tuple[Path, Path] | None:
        """Boletim e planilha já arquivados, se existirem (os dois)."""
        pasta = self._pasta(competencia)
        pdf, xlsx = pasta / f"boletim-{competencia}.pdf", pasta / f"planilha-{competencia}.xlsx"
        return (pdf, xlsx) if pdf.exists() and xlsx.exists() else None

    def arquivar(self, competencia: str, pdf: Path, xlsx: Path) -> tuple[Path, Path]:
        """Copia os arquivos para public/AAAA-MM/, regenera o índice e dá push.
        Devolve os caminhos DENTRO do arquivo: são esses bytes que se anexam."""
        pasta = self._pasta(competencia)
        pasta.mkdir(parents=True, exist_ok=True)
        destinos = []
        for origem in (pdf, xlsx):
            destino = pasta / origem.name
            shutil.copyfile(origem, destino)
            destinos.append(destino)
        self._gravar_indice()
        self._commit_push(f"arquivo: boletim e planilha de {competencia}")
        return destinos[0], destinos[1]

    def gravar_estado(self, competencia: str, **campos) -> dict:
        """Atualiza a entrada da competência em envios.json, regenera o índice
        e dá push (commit único)."""
        envios = self.envios()
        entrada = {**envios.get(competencia, {"competencia": competencia}), **campos}
        envios[competencia] = entrada
        (self.diretorio / ENVIOS).write_text(
            json.dumps(envios, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self._gravar_indice(envios)
        self._commit_push(f"envio {competencia}: {entrada.get('status', '?')}")
        return entrada

    # --------------------------------------------------------------- índice

    def _gravar_indice(self, envios: dict | None = None) -> None:
        envios = self.envios() if envios is None else envios
        raiz = self.diretorio / PUBLIC
        competencias = sorted(
            (p.name.replace("-", "") for p in raiz.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]") if p.is_dir()),
            reverse=True,
        )
        itens = []
        for c in competencias:
            pasta = f"{c[:4]}-{c[4:]}"
            info = envios.get(c, {})
            quando = info.get("enviado_em")
            situacao = f"enviado em {quando[:10]}" if info.get("status") == "enviado" and quando else "arquivado"
            itens.append(
                f'<li><strong>{html.escape(nome_competencia(c))}</strong> — {situacao}: '
                f'<a href="{pasta}/boletim-{c}.pdf">boletim (PDF)</a> · '
                f'<a href="{pasta}/planilha-{c}.xlsx">planilha (XLSX)</a></li>'
            )
        corpo = "\n".join(itens) or "<li>Nenhum boletim arquivado ainda.</li>"
        (raiz / "index.html").write_text(
            "<!doctype html>\n<html lang=\"pt-BR\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<meta name=\"robots\" content=\"noindex, nofollow\">\n"
            "<title>Arquivo de boletins CAGED</title>\n</head>\n<body>\n"
            "<h1>Arquivo de boletins CAGED — Nossa Senhora do Socorro/SE</h1>\n"
            "<p>Cada arquivo é exatamente o que foi enviado por e-mail naquela competência; "
            "não é regenerado.</p>\n"
            f"<ul>\n{corpo}\n</ul>\n"
            "<p><a href=\"/login.html?sair=1\">Sair</a></p>\n</body>\n</html>\n",
            encoding="utf-8",
        )
