"""O banco precisa recusar dado inválido mesmo quando a limpeza em Python falha."""

import psycopg
import pytest
from psycopg import errors

from src.db import ErroDeMigracao, aplicar_migracoes

CPF_A, CPF_B = "11144477735", "52998224725"


def _pessoa(c, cpf=CPF_A):
    return c.execute("INSERT INTO rh.pessoa (cpf, nome, nascimento, genero) VALUES (%s, 'Ana', '1990-01-01', 'F') RETURNING pessoa_id", (cpf,)).fetchone()[0]


def _vinculo(c, matricula, pessoa, admissao="2020-01-01", desligamento=None, motivo=None):
    c.execute("INSERT INTO rh.vinculo (matricula, pessoa_id, admissao, desligamento, motivo, contrato) VALUES (%s, %s, %s, %s, %s, 'CLT')",
              (matricula, pessoa, admissao, desligamento, motivo))


def _versao(c, matricula, de, ate=None, salario=3000):
    c.execute("""INSERT INTO rh.historico_posicao (matricula, cargo_id, departamento_id, unidade_id, salario, valido_de, valido_ate, registrado_em)
                 VALUES (%s, 1, 1, 1, %s, %s, %s, %s)""", (matricula, salario, de, ate, de))


def test_cpf_invalido_e_recusado(banco):
    with pytest.raises(errors.CheckViolation):
        _pessoa(banco, "11144477700")


def test_cpf_repetido_e_recusado(banco):
    _pessoa(banco)
    with pytest.raises(errors.UniqueViolation):
        _pessoa(banco)


def test_desligamento_antes_da_admissao_e_recusado(banco):
    with pytest.raises(errors.CheckViolation):
        _vinculo(banco, 1, _pessoa(banco), "2020-01-01", "2019-01-01", "Justa causa")


def test_desligamento_exige_motivo(banco):
    with pytest.raises(errors.CheckViolation):
        _vinculo(banco, 1, _pessoa(banco), "2020-01-01", "2021-01-01", None)


def test_mesma_pessoa_nao_tem_dois_vinculos_ao_mesmo_tempo(banco):
    pessoa = _pessoa(banco)
    _vinculo(banco, 1, pessoa, "2020-01-01", "2022-01-01", "Justa causa")
    with pytest.raises(errors.ExclusionViolation):
        _vinculo(banco, 2, pessoa, "2021-06-01")


def test_recontratacao_depois_da_saida_e_aceita(banco):
    pessoa = _pessoa(banco)
    _vinculo(banco, 1, pessoa, "2020-01-01", "2022-01-01", "Pedido de demissão")
    _vinculo(banco, 2, pessoa, "2022-06-01")
    assert banco.execute("SELECT count(*) FROM rh.vinculo").fetchone()[0] == 2


def test_versoes_do_historico_nao_se_sobrepoem(banco):
    _vinculo(banco, 1, _pessoa(banco))
    _versao(banco, 1, "2020-01-01", "2021-01-01")
    with pytest.raises(errors.ExclusionViolation):
        _versao(banco, 1, "2020-06-01", "2020-12-01")


def test_so_existe_uma_versao_atual(banco):
    _vinculo(banco, 1, _pessoa(banco))
    _versao(banco, 1, "2020-01-01")
    with pytest.raises((errors.UniqueViolation, errors.ExclusionViolation)):
        _versao(banco, 1, "2021-01-01")


def test_gestor_precisa_existir(banco):
    _vinculo(banco, 1, _pessoa(banco))
    with pytest.raises(errors.ForeignKeyViolation):
        banco.execute("""INSERT INTO rh.historico_posicao (matricula, cargo_id, departamento_id, unidade_id, gestor_matricula, salario, valido_de, registrado_em)
                         VALUES (1, 1, 1, 1, 99999, 3000, '2020-01-01', '2020-01-01')""")


def test_folha_precisa_fechar_a_conta(banco):
    _vinculo(banco, 1, _pessoa(banco))
    with pytest.raises(errors.CheckViolation):
        banco.execute("""INSERT INTO rh.folha (matricula, competencia, salario_base, horas_extras, retroativo, descontos, liquido)
                         VALUES (1, '2024-01-01', 1000, 0, 0, 100, 950)""")


def test_afastamentos_do_mesmo_tipo_nao_se_sobrepoem(banco):
    _vinculo(banco, 1, _pessoa(banco))
    banco.execute("INSERT INTO rh.afastamento (matricula, tipo, periodo) VALUES (1, 'ferias', '[2024-01-01,2024-01-11)')")
    with pytest.raises(errors.ExclusionViolation):
        banco.execute("INSERT INTO rh.afastamento (matricula, tipo, periodo) VALUES (1, 'ferias', '[2024-01-05,2024-01-20)')")


def test_alteracao_no_vinculo_fica_na_auditoria_sem_dado_pessoal(banco):
    _vinculo(banco, 1, _pessoa(banco))
    banco.execute("UPDATE rh.vinculo SET contrato = 'Temporário' WHERE matricula = 1")
    antes, depois = banco.execute("SELECT antes, depois FROM etl.auditoria").fetchone()
    assert (antes["contrato"], depois["contrato"]) == ("CLT", "Temporário")


def test_migracao_alterada_depois_de_aplicada_e_erro(banco, tmp_path):
    (tmp_path / "001_esquemas.sql").write_text("SELECT 1")
    with pytest.raises(ErroDeMigracao):
        aplicar_migracoes(banco, tmp_path)


def test_migracoes_ja_aplicadas_nao_rodam_de_novo(banco):
    assert aplicar_migracoes(banco) == []
