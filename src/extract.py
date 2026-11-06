"""
Leitura dos arquivos de origem.

A foto mensal vem de dois sistemas diferentes. Aqui os dois viram um único formato,
ainda sem nenhuma regra de limpeza: encoding, separador, nomes de coluna e tipos de data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

COLUNAS_ANTIGAS = {
    "MATRICULA": "matricula", "NOME": "nome", "CPF": "cpf", "DT_NASC": "nascimento", "SEXO": "genero", "DT_ADMISSAO": "admissao",
    "DT_DESLIG": "desligamento", "MOT_DESLIG": "motivo", "CARGO": "cargo", "DEPTO": "area", "UNIDADE": "unidade", "MAT_GESTOR": "gestor",
    "SALARIO": "salario", "TP_CONTRATO": "contrato", "INI_VIGENCIA": "inicio_vigencia",
}
COLUNAS_NOVAS = {
    "matricula": "matricula", "nome_completo": "nome", "cpf": "cpf", "data_nascimento": "nascimento", "genero": "genero",
    "data_admissao": "admissao", "data_desligamento": "desligamento", "motivo_desligamento": "motivo", "cargo": "cargo", "area": "area",
    "unidade": "unidade", "matricula_gestor": "gestor", "salario_base": "salario", "contrato": "contrato", "inicio_vigencia": "inicio_vigencia",
}
COLUNAS_DATA = ["nascimento", "admissao", "desligamento", "inicio_vigencia"]


class ArquivoDesconhecido(Exception):
    pass


def numero_br(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))


def ler_foto(caminho: Path) -> pd.DataFrame:
    """Reconhece o sistema pelo cabeçalho, e não pela data do arquivo."""
    bruto = caminho.read_bytes()
    primeira_linha = bruto.split(b"\n", 1)[0]
    if primeira_linha.startswith(b"MATRICULA;"):
        df = pd.read_csv(caminho, sep=";", encoding="latin-1", dtype=str, keep_default_na=False).rename(columns=COLUNAS_ANTIGAS)
        formato = "%d/%m/%Y"
        df["salario"] = numero_br(df["salario"])
    elif primeira_linha.startswith(b"matricula,"):
        df = pd.read_csv(caminho, encoding="utf-8", dtype=str, keep_default_na=False).rename(columns=COLUNAS_NOVAS)
        formato = "%Y-%m-%d"
        df["salario"] = pd.to_numeric(df["salario"])
    else:
        raise ArquivoDesconhecido(f"{caminho.name}: cabeçalho não reconhecido")
    for coluna in COLUNAS_DATA:
        df[coluna] = pd.to_datetime(df[coluna].replace("", None), format=formato)
    df["matricula"] = df["matricula"].astype(int)
    df["gestor"] = pd.to_numeric(df["gestor"].replace("", None)).astype("Int64")
    return df


def ler_folha(caminho: Path) -> pd.DataFrame:
    df = pd.read_csv(caminho, sep=";", dtype=str)
    valores = {c: numero_br(df[c]) for c in ["salario_base", "horas_extras", "retroativo", "descontos", "liquido"]}
    return df.assign(**valores, matricula=df["matricula"].astype(int), competencia=pd.to_datetime(df["competencia"], format="%m/%Y"))


def ler_afastamentos(caminho: Path) -> pd.DataFrame:
    """Achata o JSON por matrícula. O CID é dado de saúde e sem uso aqui, então não passa da leitura."""
    registros = json.loads(caminho.read_text(encoding="utf-8"))
    df = pd.json_normalize(registros, record_path="afastamentos", meta="matricula")
    return df.drop(columns="cid").assign(inicio=lambda d: pd.to_datetime(d["inicio"]), fim=lambda d: pd.to_datetime(d["fim"]))
