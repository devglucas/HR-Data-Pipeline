"""
Base anonimizada para o analista.

Tirar nome e CPF não basta: área, idade e gênero juntos ainda podem apontar uma pessoa.
Por isso os dados viram faixas, e qualquer combinação com menos de k pessoas é suprimida
(k-anonimato). A verificação abaixo mede o resultado em vez de confiar na regra.
"""

from __future__ import annotations

import psycopg

from src.db import executar_arquivo
from src.settings import SQL_DIR, segredo

QUASE_IDENTIFICADORES = "departamento, grupo_nivel, faixa_etaria, genero"


def atualizar(conexao: psycopg.Connection, k: int) -> dict:
    referencia = conexao.execute("SELECT (max(competencia) + interval '1 month - 1 day')::date FROM etl.carga").fetchone()[0]
    with conexao.transaction():
        executar_arquivo(conexao, SQL_DIR / "etl" / "anonimizar.sql", {"chave": segredo("ANON_CHAVE"), "referencia": referencia, "k": k})
    total = conexao.execute("SELECT count(*) FROM rh.vinculo").fetchone()[0]
    publicados = conexao.execute("SELECT count(*) FROM anon.colaborador").fetchone()[0]
    menor = conexao.execute(f"SELECT min(n) FROM (SELECT count(*) AS n FROM anon.colaborador GROUP BY {QUASE_IDENTIFICADORES}) g").fetchone()[0]
    return {"vinculos": total, "publicados": publicados, "suprimidos": total - publicados, "menor_grupo": menor, "k": k}
