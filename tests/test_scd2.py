"""Comportamento do histórico (SCD tipo 2), com fotos montadas à mão."""

import shutil
from pathlib import Path

import pandas as pd
import pytest

from src import load
from src.clean import COLUNAS_STAGING

CPF_PRESIDENTE, CPF_ANA, CPF_BIA = "11144477735", "52998224725", "39053344705"


def _linha(matricula=2, cpf=CPF_ANA, **campos):
    base = {"matricula": matricula, "cpf": cpf, "nome": "Ana", "nascimento": pd.Timestamp("1990-01-01"), "genero": "F", "admissao": pd.Timestamp("2020-01-10"),
            "desligamento": None, "motivo": None, "cargo": "Atendente Júnior", "departamento": "ATENDIMENTO", "departamento_nome": "Atendimento",
            "unidade": "Recife", "gestor": 1, "salario": 2500.0, "contrato": "CLT", "inicio_vigencia": pd.Timestamp("2020-01-10")}
    return {**base, **campos}


PRESIDENTE = _linha(1, CPF_PRESIDENTE, gestor=None, cargo="Presidente", salario=95000.0, nome="Pres")


def _foto(banco, competencia, *linhas, presentes=None):
    df = pd.DataFrame([PRESIDENTE, *linhas])[COLUNAS_STAGING].astype({"gestor": "Int64"})
    with banco.transaction():
        return load.aplicar_limpos(banco, df, pd.Series(presentes or df["matricula"].tolist()), pd.Timestamp(competencia))


def _versoes(banco, matricula=2):
    return banco.execute("""SELECT salario::float, valido_de::text, valido_ate::text, registrado_em::text FROM rh.historico_posicao
                            WHERE matricula = %s ORDER BY valido_de""", (matricula,)).fetchall()


def test_primeira_carga_abre_uma_versao_por_pessoa(banco):
    assert _foto(banco, "2024-01-01", _linha()) == 2


def test_foto_igual_nao_cria_versao(banco):
    _foto(banco, "2024-01-01", _linha())
    assert _foto(banco, "2024-02-01", _linha()) == 0


def test_mudanca_fecha_a_versao_e_abre_outra_sem_lacuna(banco):
    _foto(banco, "2024-01-01", _linha())
    _foto(banco, "2024-02-01", _linha(salario=2800.0, inicio_vigencia=pd.Timestamp("2024-02-15")))
    assert _versoes(banco) == [(2500.0, "2020-01-10", "2024-02-15", "2024-01-01"), (2800.0, "2024-02-15", None, "2024-02-01")]


def test_promocao_lancada_com_atraso_vale_desde_a_vigencia(banco):
    _foto(banco, "2024-01-01", _linha())
    _foto(banco, "2024-03-01", _linha(cargo="Atendente Pleno", salario=2800.0, inicio_vigencia=pd.Timestamp("2024-01-20")))
    assert _versoes(banco)[1] == (2800.0, "2024-01-20", None, "2024-03-01")      # vigência antiga, registro recente


def test_renomear_a_area_nao_cria_versao(banco):
    _foto(banco, "2024-01-01", _linha())
    assert _foto(banco, "2024-02-01", _linha(departamento_nome="Customer Success")) == 0
    assert banco.execute("SELECT nome FROM rh.departamento WHERE codigo = 'ATENDIMENTO'").fetchone()[0] == "Customer Success"


def test_gestor_inexistente_mantem_o_anterior_e_registra(banco):
    _foto(banco, "2024-01-01", _linha())
    assert _foto(banco, "2024-02-01", _linha(gestor=99999)) == 0
    assert banco.execute("SELECT motivo FROM etl.quarentena").fetchall() == [("gestor_inexistente",)]


def test_gestor_que_faltava_e_preenchido_sem_nova_versao(banco):
    _foto(banco, "2024-01-01", _linha(gestor=99999))
    assert _foto(banco, "2024-02-01", _linha()) == 0
    assert banco.execute("SELECT gestor_matricula FROM rh.historico_posicao WHERE matricula = 2").fetchone()[0] == 1


def test_vigencia_anterior_a_versao_atual_vai_para_a_quarentena(banco):
    _foto(banco, "2024-01-01", _linha())
    _foto(banco, "2024-02-01", _linha(salario=2800.0, inicio_vigencia=pd.Timestamp("2019-01-01")))
    assert len(_versoes(banco)) == 1
    assert banco.execute("SELECT motivo FROM etl.quarentena").fetchone()[0] == "vigencia_conflitante"


def test_desligamento_fecha_a_versao_atual(banco):
    _foto(banco, "2024-01-01", _linha())
    _foto(banco, "2024-02-01", _linha(desligamento=pd.Timestamp("2024-02-20"), motivo="Pedido de demissão"))
    assert _versoes(banco)[-1][2] == "2024-02-20"


def test_mudanca_com_vigencia_depois_da_saida_nao_entra(banco):
    _foto(banco, "2024-01-01", _linha())
    _foto(banco, "2024-02-01", _linha(desligamento=pd.Timestamp("2024-02-10"), motivo="Justa causa", salario=2800.0, inicio_vigencia=pd.Timestamp("2024-02-20")))
    assert len(_versoes(banco)) == 1
    assert banco.execute("SELECT motivo FROM etl.quarentena").fetchone()[0] == "vigencia_apos_desligamento"


def test_quem_some_do_arquivo_tem_saida_inferida(banco):
    _foto(banco, "2024-01-01", _linha())
    _foto(banco, "2024-02-01")
    assert banco.execute("SELECT desligamento::text, motivo, desligamento_inferido FROM rh.vinculo WHERE matricula = 2").fetchone() == (
        "2024-02-01", "Não informado", True)
    assert _versoes(banco)[-1][2] == "2024-02-01"


def test_linha_em_quarentena_nao_vira_desligamento(banco):
    _foto(banco, "2024-01-01", _linha())
    _foto(banco, "2024-02-01", presentes=[1, 2])        # a matrícula 2 estava no arquivo, mas a linha foi rejeitada
    assert banco.execute("SELECT desligamento FROM rh.vinculo WHERE matricula = 2").fetchone()[0] is None


def test_recontratacao_reaproveita_a_pessoa(banco):
    _foto(banco, "2024-01-01", _linha())
    _foto(banco, "2024-02-01", _linha(desligamento=pd.Timestamp("2024-02-10"), motivo="Pedido de demissão"))
    novo = pd.Timestamp("2024-06-01")
    _foto(banco, "2024-06-01", _linha(3, admissao=novo, inicio_vigencia=novo))
    assert banco.execute("SELECT count(*), count(DISTINCT pessoa_id) FROM rh.vinculo WHERE matricula <> 1").fetchone() == (2, 1)


def test_correcao_de_nome_atualiza_a_pessoa(banco):
    _foto(banco, "2024-01-01", _linha(nome="ANA"))
    _foto(banco, "2024-02-01", _linha(nome="Ana Sá"))
    assert banco.execute("SELECT nome FROM rh.pessoa WHERE cpf = %s", (CPF_ANA,)).fetchone()[0] == "Ana Sá"


def test_foto_ja_carregada_e_ignorada_e_mudanca_no_arquivo_e_erro(banco, catalogo, tmp_path):
    origem = Path("data/raw/rh/colaboradores_2023-01.csv")
    arquivo = tmp_path / origem.name
    shutil.copy(origem, arquivo)
    assert load.aplicar_foto(banco, arquivo, catalogo) is not None
    assert load.aplicar_foto(banco, arquivo, catalogo) is None
    arquivo.write_text(arquivo.read_text(encoding="latin-1") + "\n", encoding="latin-1")
    with pytest.raises(load.CargaForaDeOrdem):
        load.aplicar_foto(banco, arquivo, catalogo)


def test_foto_anterior_a_ultima_carregada_e_erro(banco, catalogo, tmp_path):
    for nome in ["colaboradores_2023-02.csv", "colaboradores_2023-01.csv"]:
        shutil.copy(Path("data/raw/rh") / nome, tmp_path / nome)
    load.aplicar_foto(banco, tmp_path / "colaboradores_2023-02.csv", catalogo)
    with pytest.raises(load.CargaForaDeOrdem):
        load.aplicar_foto(banco, tmp_path / "colaboradores_2023-01.csv", catalogo)
