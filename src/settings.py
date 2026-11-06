"""Configuração: catálogos em YAML e segredos no ambiente (ou no .env, para o banco local)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "raw"
SQL_DIR = ROOT_DIR / "sql"
OUTPUT_DIR = ROOT_DIR / "output"
REPORTS_DIR = OUTPUT_DIR / "reports"
CHARTS_DIR = OUTPUT_DIR / "charts"

PADROES = {
    "POSTGRES_USER": "rh_admin", "POSTGRES_PASSWORD": "senha-local-de-desenvolvimento", "POSTGRES_DB": "rh", "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5433", "RH_ANALISTA_SENHA": "senha-local-do-analista", "ANON_CHAVE": "chave-local-de-desenvolvimento",
}


def _arquivo_env(caminho: Path = ROOT_DIR / ".env") -> dict[str, str]:
    if not caminho.exists():
        return {}
    linhas = (l.strip() for l in caminho.read_text(encoding="utf-8").splitlines())
    return dict(l.split("=", 1) for l in linhas if l and not l.startswith("#") and "=" in l)


def segredo(nome: str) -> str:
    """Ambiente > .env > padrão local. Os padrões só servem para o banco do docker-compose."""
    return os.environ.get(nome) or _arquivo_env().get(nome) or PADROES[nome]


def dsn(banco: str | None = None, usuario: str | None = None, senha: str | None = None) -> str:
    return (f"host={segredo('POSTGRES_HOST')} port={segredo('POSTGRES_PORT')} dbname={banco or segredo('POSTGRES_DB')} "
            f"user={usuario or segredo('POSTGRES_USER')} password={senha or segredo('POSTGRES_PASSWORD')}")


def carregar(caminho: Path = ROOT_DIR / "config" / "rh.yaml") -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))
