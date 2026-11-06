import json

import pandas as pd
import pytest

from src.extract import ArquivoDesconhecido, ler_afastamentos, ler_folha, ler_foto

ANTIGO = ("MATRICULA;NOME;CPF;DT_NASC;SEXO;DT_ADMISSAO;DT_DESLIG;MOT_DESLIG;CARGO;DEPTO;UNIDADE;MAT_GESTOR;SALARIO;TP_CONTRATO;INI_VIGENCIA\n"
          "10001;JOAO SA;123;05/01/1984;M;19/11/2016;;;ATENDENTE JR;ATENDIMENTO;SAO PAULO;10002;9.027,11;CLT;19/11/2016\n")
NOVO = ("matricula,nome_completo,cpf,data_nascimento,genero,data_admissao,data_desligamento,motivo_desligamento,cargo,area,unidade,"
        "matricula_gestor,salario_base,contrato,inicio_vigencia\n"
        "0010001,João Sá,111.444.777-35,1984-01-05,Masculino,2016-11-19,,,Atendente Júnior,Atendimento,São Paulo,0010002,9027.11,CLT,2016-11-19\n")


def test_os_dois_sistemas_viram_o_mesmo_formato(tmp_path):
    antigo, novo = tmp_path / "a.csv", tmp_path / "n.csv"
    antigo.write_text(ANTIGO, encoding="latin-1")
    novo.write_text(NOVO, encoding="utf-8")
    a, n = ler_foto(antigo), ler_foto(novo)
    assert list(a.columns) == list(n.columns)
    for coluna in ["matricula", "admissao", "gestor", "salario", "inicio_vigencia"]:
        assert a[coluna].iat[0] == n[coluna].iat[0]


def test_cabecalho_desconhecido_falha_em_vez_de_adivinhar(tmp_path):
    arquivo = tmp_path / "x.csv"
    arquivo.write_text("id;nome\n1;a\n", encoding="utf-8")
    with pytest.raises(ArquivoDesconhecido):
        ler_foto(arquivo)


def test_folha_converte_numero_e_competencia(tmp_path):
    arquivo = tmp_path / "f.csv"
    arquivo.write_text("matricula;competencia;salario_base;horas_extras;retroativo;descontos;liquido\n10;09/2024;1.000,50;0,00;0,00;100,00;900,50\n")
    linha = ler_folha(arquivo).iloc[0]
    assert linha["salario_base"] == 1000.5 and linha["competencia"] == pd.Timestamp("2024-09-01")


def test_cid_nao_passa_da_leitura(tmp_path):
    arquivo = tmp_path / "p.json"
    arquivo.write_text(json.dumps([{"matricula": 1, "afastamentos": [{"tipo": "atestado", "inicio": "2024-01-01", "fim": "2024-01-02", "cid": "F41"}]}]))
    assert "cid" not in ler_afastamentos(arquivo).columns
