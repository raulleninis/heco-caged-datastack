"""
Coletor diário de notícias (F19 parte 4): lê os feeds RSS/Atom de perfis/fontes_noticias.toml e
acumula título, link, data e resumo em /data/noticias/AAAA-MM.jsonl (mês da publicação).

Por que diário: os feeds guardam poucas notícias (a Infonet, 10 em ~2 dias). Coletar só no dia
do boletim perderia quase tudo. Por que fora do warehouse: o warehouse se reconstrói do FTP
(D03); as notícias não, porque o feed esquece. Os JSONL são o registro permanente.

Nunca derruba o flow diário: cada fonte falha sozinha e vira aviso. Uma fonte que falha 3 dias
seguidos gera um alerta de baixa prioridade (estado em /data/noticias/estado.json).

Só guarda o que o feed publica (título, link, data, resumo curto). O texto completo de uma
notícia só é lido depois, pelo pesquisador, e nunca é republicado: o boletim cita com link.
Respeita o robots.txt e um intervalo mínimo por host.

Uso manual:
    python flows/noticias.py            # coleta agora
"""

import hashlib
import html
import json
import os
import re
import time
import tomllib
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

AGENTE = "boletim-caged-coletor/1.0"
FONTES = Path(__file__).resolve().parent.parent / "perfis" / "fontes_noticias.toml"
PASTA = Path(os.environ.get("NOTICIAS_DIR", "/data/noticias"))
DIAS_PARA_ALERTA = 3
RESUMO_MAX = 600

_ATOM = "{http://www.w3.org/2005/Atom}"


def carregar_fontes(caminho: Path = FONTES) -> list[dict]:
    fontes = tomllib.loads(caminho.read_text(encoding="utf-8")).get("fontes", [])
    for f in fontes:
        faltando = {"nome", "feed", "escala"} - set(f)
        if faltando:
            raise ValueError(f"{caminho}: fonte {f.get('nome')} sem {sorted(faltando)}")
        if f["escala"] not in ("municipal", "regional", "estadual", "nacional"):
            raise ValueError(f"{caminho}: escala inválida em {f['nome']}: {f['escala']}")
    return fontes


def _texto_limpo(bruto: str | None) -> str:
    sem_tags = re.sub(r"<[^>]+>", " ", html.unescape(bruto or ""))
    return re.sub(r"\s+", " ", sem_tags).strip()[:RESUMO_MAX]


def _data(bruto: str | None) -> str | None:
    """RFC 822 (RSS) ou ISO 8601 (Atom) -> ISO em UTC; None se ilegível."""
    if not bruto:
        return None
    try:
        d = parsedate_to_datetime(bruto.strip())
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(bruto.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def ler_feed(conteudo: bytes) -> list[dict]:
    """Itens de um feed RSS 2.0 ou Atom: titulo, link, publicado_em, resumo.

    Tolera vários documentos XML colados na mesma resposta (o feed do Sebrae SE, em
    29/09/2026, vinha com dois <rss> inteiros em sequência): lê cada um e junta os itens."""
    partes = [p for p in re.split(rb"(?=<\?xml)", conteudo.strip()) if p.strip()]
    itens, erros = [], []
    for parte in partes:
        try:
            itens += _ler_documento(ET.fromstring(parte))
        except ET.ParseError as e:
            erros.append(e)
    if erros and not itens:
        raise erros[0]
    return itens


def _ler_documento(raiz) -> list[dict]:
    itens = []
    if raiz.tag == f"{_ATOM}feed":
        for e in raiz.findall(f"{_ATOM}entry"):
            # Sem `or`: no ElementTree, um elemento sem filhos é falso em contexto booleano.
            link = e.find(f"{_ATOM}link[@rel='alternate']")
            if link is None:
                link = e.find(f"{_ATOM}link")
            itens.append({
                "titulo": _texto_limpo(e.findtext(f"{_ATOM}title")),
                "link": (link.get("href") if link is not None else "") or "",
                "publicado_em": _data(e.findtext(f"{_ATOM}published") or e.findtext(f"{_ATOM}updated")),
                "resumo": _texto_limpo(e.findtext(f"{_ATOM}summary") or e.findtext(f"{_ATOM}content")),
            })
    else:
        for e in raiz.iter("item"):
            itens.append({
                "titulo": _texto_limpo(e.findtext("title")),
                "link": (e.findtext("link") or "").strip(),
                "publicado_em": _data(e.findtext("pubDate")),
                "resumo": _texto_limpo(e.findtext("description")),
            })
    return [i for i in itens if i["titulo"] and i["link"]]


def _baixar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _permitido(url: str, baixar=_baixar) -> bool:
    partes = urlsplit(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.parse(baixar(f"{partes.scheme}://{partes.netloc}/robots.txt").decode("utf-8", "ignore").splitlines())
    except Exception:
        return True  # sem robots.txt legível: a convenção é permitir
    return rp.can_fetch(AGENTE, url)


def _id(link: str) -> str:
    return hashlib.sha1(link.encode()).hexdigest()[:16]


class Arquivo:
    """Os JSONL mensais, com deduplicação pelo link."""

    def __init__(self, pasta: Path = PASTA):
        self.pasta = pasta
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._vistos: set[str] | None = None

    def vistos(self) -> set[str]:
        if self._vistos is None:
            self._vistos = set()
            for arq in self.pasta.glob("????-??.jsonl"):
                with arq.open(encoding="utf-8") as f:
                    self._vistos |= {json.loads(l)["id"] for l in f if l.strip()}
        return self._vistos

    def gravar(self, fonte: dict, item: dict, agora: str) -> bool:
        ident = _id(item["link"])
        if ident in self.vistos():
            return False
        registro = {"id": ident, "fonte": fonte["nome"], "escala": fonte["escala"], **item, "coletado_em": agora}
        mes = (item["publicado_em"] or agora)[:7]
        with (self.pasta / f"{mes}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        self._vistos.add(ident)
        return True

    def ler(self, mes: str) -> list[dict]:
        arq = self.pasta / f"{mes}.jsonl"
        if not arq.exists():
            return []
        return [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]


def coletar(fontes: list[dict] | None = None, arquivo: Arquivo | None = None, baixar=_baixar,
            dormir=time.sleep, avisar=None) -> dict:
    """Coleta todas as fontes. Nunca levanta exceção por causa de uma fonte: devolve o
    resumo {fonte: novos | 'erro: ...'} e atualiza o estado de falhas consecutivas."""
    fontes = fontes if fontes is not None else carregar_fontes()
    arquivo = arquivo or Arquivo()
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    estado_arq = arquivo.pasta / "estado.json"
    estado = json.loads(estado_arq.read_text(encoding="utf-8")) if estado_arq.exists() else {}
    ultimo_acesso: dict[str, float] = {}
    resumo = {}
    for fonte in fontes:
        host = urlsplit(fonte["feed"]).netloc
        espera = fonte.get("intervalo_s", 2) - (time.monotonic() - ultimo_acesso.get(host, -1e9))
        if espera > 0:
            dormir(espera)
        try:
            if not _permitido(fonte["feed"], baixar):
                raise PermissionError("robots.txt não permite")
            itens = ler_feed(baixar(fonte["feed"]))
            novos = sum(arquivo.gravar(fonte, i, agora) for i in itens)
            resumo[fonte["nome"]] = novos
            estado[fonte["nome"]] = {"ultimo_sucesso": agora, "falhas_seguidas": 0}
        except Exception as e:  # uma fonte fora do ar não pode derrubar as outras nem o flow
            resumo[fonte["nome"]] = f"erro: {type(e).__name__}: {e}"[:200]
            s = estado.setdefault(fonte["nome"], {"ultimo_sucesso": None, "falhas_seguidas": 0})
            s["falhas_seguidas"] += 1
            if s["falhas_seguidas"] == DIAS_PARA_ALERTA and avisar:
                avisar(fonte["nome"], resumo[fonte["nome"]])
        finally:
            ultimo_acesso[host] = time.monotonic()
    estado_arq.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resumo


if __name__ == "__main__":
    print(json.dumps(coletar(), ensure_ascii=False, indent=2))
