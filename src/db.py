"""Conexão, migrações versionadas e carga em massa com COPY."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import psycopg
from psycopg import sql

from src.settings import SQL_DIR, dsn, segredo


class ErroDeMigracao(Exception):
    pass


def conectar(banco: str | None = None) -> psycopg.Connection:
    """Autocommit: cada bloco que precisa ser atômico abre a própria transação, de forma explícita."""
    return psycopg.connect(dsn(banco), autocommit=True)


def aplicar_migracoes(conexao: psycopg.Connection, pasta: Path = SQL_DIR / "migrations") -> list[str]:
    """Aplica em ordem o que ainda não rodou. Migração já aplicada e alterada depois é erro, não é ignorada."""
    conexao.execute("""CREATE TABLE IF NOT EXISTS public.migracao (
        arquivo text PRIMARY KEY, hash text NOT NULL, aplicada_em timestamptz NOT NULL DEFAULT now())""")
    aplicadas = dict(conexao.execute("SELECT arquivo, hash FROM public.migracao").fetchall())
    novas = []
    for arquivo in sorted(pasta.glob("*.sql")):
        conteudo = arquivo.read_text(encoding="utf-8")
        assinatura = hashlib.sha256(conteudo.encode()).hexdigest()
        if arquivo.name in aplicadas:
            if aplicadas[arquivo.name] != assinatura:
                raise ErroDeMigracao(f"{arquivo.name} foi alterada depois de aplicada: crie uma nova migração")
            continue
        with conexao.transaction():
            conexao.execute(conteudo)
            conexao.execute("INSERT INTO public.migracao (arquivo, hash) VALUES (%s, %s)", (arquivo.name, assinatura))
        novas.append(arquivo.name)
    return novas


def definir_senha_do_analista(conexao: psycopg.Connection) -> None:
    conexao.execute(sql.SQL("ALTER ROLE rh_analista LOGIN PASSWORD {}").format(sql.Literal(segredo("RH_ANALISTA_SENHA"))))


def copiar(conexao: psycopg.Connection, df: pd.DataFrame, esquema: str, tabela: str) -> None:
    """COPY é a forma mais rápida de carregar no PostgreSQL. Vazios viram NULL."""
    colunas = sql.SQL(", ").join(map(sql.Identifier, df.columns))
    comando = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(sql.Identifier(esquema), sql.Identifier(tabela), colunas)
    linhas = df.astype(object).where(df.notna(), None).itertuples(index=False, name=None)
    with conexao.cursor().copy(comando) as copia:
        for linha in linhas:
            copia.write_row(linha)


def consultar(conexao: psycopg.Connection, consulta: str, parametros: dict | None = None) -> pd.DataFrame:
    cursor = conexao.execute(consulta, parametros)
    return pd.DataFrame(cursor.fetchall(), columns=[c.name for c in cursor.description])


def executar_arquivo(conexao: psycopg.Connection, arquivo: Path, parametros: dict) -> None:
    """Executa um arquivo de comandos, um a um, para aceitar parâmetros."""
    for comando in remover_comentarios(arquivo.read_text(encoding="utf-8")).split(";"):
        if comando.strip():
            conexao.execute(comando, parametros)


def remover_comentarios(texto: str) -> str:
    return "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("--"))
