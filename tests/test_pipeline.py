"""Ponta a ponta: carrega os 30 meses reais em um banco de teste e confere o resultado."""

import psycopg
import pytest
from psycopg import errors

from main import executar, recriar_banco
from src.db import conectar
from src.settings import dsn, segredo

BANCO = "rh_teste_e2e"


@pytest.fixture(scope="module")
def execucao(postgres, tmp_path_factory):
    recriar_banco(BANCO)
    return tmp_path_factory.mktemp("saida"), executar(BANCO, tmp_path_factory.mktemp("saida"))


@pytest.fixture
def analista(execucao):
    with psycopg.connect(dsn(BANCO, "rh_analista", segredo("RH_ANALISTA_SENHA")), autocommit=True) as conexao:
        yield conexao


def test_nenhuma_verificacao_critica_falha(execucao):
    _, resultado = execucao
    assert [v for v in resultado["verificacoes"] if v["severidade"] == "critica" and not v["ok"]] == []


def test_achados_de_negocio_aparecem_como_alerta(execucao):
    _, resultado = execucao
    assert {v["verificacao"] for v in resultado["verificacoes"] if v["severidade"] == "alerta" and not v["ok"]} == {
        "ninguém recebe depois de sair", "todo desligamento foi informado", "cadeia de gestão sem ciclos"}


def test_reestruturacao_aparece_no_turnover(execucao):
    _, resultado = execucao
    turnover = resultado["tabelas"]["turnover_mensal"]
    assert str(turnover.loc[turnover["desligamentos"].idxmax(), "mes"]) == "2024-08-01"


def test_gestor_problema_se_destaca_na_area(execucao):
    _, resultado = execucao
    comercial = resultado["tabelas"]["turnover_gestor"].query("departamento == 'Comercial'")
    assert comercial.iloc[0]["gestor_matricula"] == 10535


def test_turnover_12_meses_so_existe_com_janela_completa(execucao):
    _, resultado = execucao
    assert resultado["tabelas"]["turnover_mensal"]["taxa_12_meses"].isna().sum() == 11


def test_saidas_nao_tem_nome_nem_cpf(execucao):
    _, resultado = execucao
    for tabela in resultado["tabelas"].values():
        assert not {"nome", "cpf", "nascimento"} & set(tabela.columns)


def test_analista_le_indicadores_e_base_anonima(analista):
    assert analista.execute("SELECT count(*) FROM anon.colaborador").fetchone()[0] > 0
    assert analista.execute("SELECT count(*) FROM analytics.turnover_mensal").fetchone()[0] == 30


@pytest.mark.parametrize("tabela", ["rh.pessoa", "rh.vinculo", "rh.folha", "rh.posicao_mensal", "etl.quarentena", "analytics.turnover_gestor",
                                    "analytics.pagamentos_apos_desligamento"])
def test_analista_nao_le_dados_individuais(analista, tabela):
    with pytest.raises(errors.InsufficientPrivilege):
        analista.execute(f"SELECT 1 FROM {tabela} LIMIT 1")


def test_analista_nao_altera_dados(analista):
    with pytest.raises(errors.InsufficientPrivilege):
        analista.execute("DELETE FROM anon.colaborador")


def test_base_anonima_respeita_k_e_nao_expoe_identificadores(execucao):
    with conectar(BANCO) as conexao:
        colunas = {r[0] for r in conexao.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'anon'").fetchall()}
        menor = conexao.execute("""SELECT min(n) FROM (SELECT count(*) AS n FROM anon.colaborador
                                   GROUP BY departamento, grupo_nivel, faixa_etaria, genero) g""").fetchone()[0]
    assert not {"cpf", "nome", "matricula", "nascimento", "salario"} & colunas
    assert menor >= 5


def test_segunda_execucao_nao_muda_nada(execucao, tmp_path):
    _, primeira = execucao
    with conectar(BANCO) as conexao:
        contar = lambda: conexao.execute("""SELECT (SELECT count(*) FROM rh.historico_posicao), (SELECT count(*) FROM rh.folha),
                                                   (SELECT count(*) FROM rh.afastamento), (SELECT count(*) FROM etl.quarentena),
                                                   (SELECT count(*) FROM etl.auditoria)""").fetchone()
        antes = contar()
        segunda = executar(BANCO, tmp_path)
        assert segunda["cargas"] == [] and contar() == antes
    assert segunda["manifesto"]["sucesso"]
