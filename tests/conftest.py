"""Os testes de banco usam bancos próprios no mesmo container. Sem o Docker no ar, eles são pulados."""

import psycopg
import pytest
from psycopg import sql

from src import clean, load
from src.db import aplicar_migracoes, conectar
from src.settings import carregar


def _recriar(banco: str) -> None:
    with conectar("postgres") as manutencao:
        manutencao.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(banco)))
        manutencao.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(banco)))


@pytest.fixture(scope="session")
def postgres():
    try:
        conectar("postgres").close()
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL fora do ar: rode `docker compose up -d --wait`")


@pytest.fixture(scope="session")
def catalogo():
    return clean.catalogos(carregar())


@pytest.fixture
def banco(postgres, catalogo):
    """Banco vazio, com o esquema e os catálogos, novo para cada teste."""
    _recriar("rh_teste")
    with conectar("rh_teste") as conexao:
        aplicar_migracoes(conexao)
        load.semear_catalogos(conexao, carregar(), catalogo)
        yield conexao
