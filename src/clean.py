"""
Regras de limpeza da foto mensal.

Nada é descartado em silêncio: o que não pode entrar vai para a quarentena com motivo,
sem nome nem CPF, porque a quarentena é consultada por mais pessoas que o cadastro.
"""

from __future__ import annotations

import unicodedata

import pandas as pd

COLUNAS_STAGING = ["matricula", "cpf", "nome", "nascimento", "genero", "admissao", "desligamento", "motivo", "cargo", "departamento",
                   "departamento_nome", "unidade", "gestor", "salario", "contrato", "inicio_vigencia"]
GENEROS = {"F": "F", "M": "M", "FEMININO": "F", "MASCULINO": "M"}


def chave(texto: str) -> str:
    """Forma comparável: sem acento, em maiúsculas e sem espaços sobrando."""
    limpo = "".join(c for c in unicodedata.normalize("NFKD", str(texto)) if not unicodedata.combining(c))
    return " ".join(limpo.upper().split())


def cpf_valido(cpf: str) -> bool:
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False
    digitos = [int(c) for c in cpf]
    for tamanho in (9, 10):
        soma = sum(n * (tamanho + 1 - i) for i, n in enumerate(digitos[:tamanho]))
        if soma * 10 % 11 % 10 != digitos[tamanho]:
            return False
    return True


def nome_proprio(nome: str) -> str:
    return " ".join(nome.split())


def catalogos(config: dict) -> dict:
    """De-paras de cargo, área, unidade e contrato, nas grafias dos dois sistemas."""
    niveis = list(config["niveis"])
    cargos, faixas = {}, {}

    def registrar(canonico: str, base: float, nivel: str, *grafias: str) -> None:
        multiplicador = config["niveis"][nivel]
        faixa = config["faixa_salarial"]
        faixas[canonico] = {"nivel": nivel, "nivel_ordem": niveis.index(nivel) + 1, "faixa_min": round(base * multiplicador * faixa["minimo"], 2),
                            "faixa_max": round(base * multiplicador * faixa["maximo"], 2)}
        for grafia in (canonico, *grafias):
            cargos[chave(grafia)] = canonico

    abreviacoes = {nivel: sigla for sigla, nivel in config["abreviacoes_nivel"].items()}
    departamentos, nomes_area = {}, {}
    for codigo, regra in config["departamentos"].items():
        for apelido in regra["apelidos"]:
            departamentos[chave(apelido)] = codigo
            nomes_area[chave(apelido)] = apelido
        for nivel in niveis[:3]:
            registrar(f"{regra['familia']} {nivel}", regra["base"], nivel, f"{regra['abreviado']} {abreviacoes[nivel]}")
        for nivel in niveis[3:6]:
            registrar(f"{nivel} de {regra['apelidos'][0]}", regra["base"], nivel)
    registrar(config["presidente"]["nome"], config["presidente"]["base"], "Presidente")
    return {
        "cargos": cargos, "faixas": faixas, "departamentos": departamentos, "nomes_area": nomes_area,
        "unidades": {chave(u): u for u in config["unidades"]}, "contratos": {chave(c): c for c in config["contratos"]},
        "motivos": {chave(m): m for m in config["motivos_desligamento"]},
    }


def _rejeitar(df: pd.DataFrame, mascara: pd.Series, motivo: str, rejeitados: list) -> pd.DataFrame:
    if mascara.any():
        campos = df.loc[mascara, ["matricula", "cargo", "area", "salario", "admissao", "inicio_vigencia"]]
        rejeitados.append(campos.assign(motivo=motivo))
    return df.loc[~mascara]


def limpar_foto(df: pd.DataFrame, cat: dict, competencia: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    rejeitados: list[pd.DataFrame] = []
    fim_do_mes = competencia + pd.offsets.MonthEnd(0)

    # Linha repetida: vale a de vigência mais recente, a outra é um registro antigo que ficou no arquivo.
    ordenado = df.sort_values(["matricula", "inicio_vigencia"], kind="stable")
    repetida = ordenado.duplicated("matricula", keep="last")
    limpos = _rejeitar(ordenado, repetida, "linha_duplicada_antiga", rejeitados)

    limpos = limpos.assign(
        cpf=limpos["cpf"].str.replace(r"\D", "", regex=True).str.zfill(11),      # o sistema antigo perde zeros à esquerda
        nome=limpos["nome"].map(nome_proprio),
        genero=limpos["genero"].map(lambda g: GENEROS.get(chave(g))),
        cargo=limpos["cargo"].map(lambda c: cat["cargos"].get(chave(c))),
        departamento=limpos["area"].map(lambda a: cat["departamentos"].get(chave(a))),
        departamento_nome=limpos["area"].map(lambda a: cat["nomes_area"].get(chave(a))),
        unidade=limpos["unidade"].map(lambda u: cat["unidades"].get(chave(u))),
        contrato=limpos["contrato"].map(lambda c: cat["contratos"].get(chave(c))),
        motivo=limpos["motivo"].map(lambda m: cat["motivos"].get(chave(m)) if m else None),
    )

    limpos = _rejeitar(limpos, ~limpos["cpf"].map(cpf_valido), "cpf_invalido", rejeitados)
    limpos = _rejeitar(limpos, limpos["cargo"].isna(), "cargo_desconhecido", rejeitados)
    limpos = _rejeitar(limpos, limpos["departamento"].isna() | limpos["unidade"].isna(), "cadastro_desconhecido", rejeitados)
    limpos = _rejeitar(limpos, limpos["admissao"] > fim_do_mes, "admissao_no_futuro", rejeitados)
    faixa = limpos["cargo"].map(cat["faixas"])
    minimo, maximo = faixa.map(lambda f: f["faixa_min"]), faixa.map(lambda f: f["faixa_max"])
    limpos = _rejeitar(limpos, (limpos["salario"] < minimo) | (limpos["salario"] > maximo), "salario_fora_da_faixa", rejeitados)

    quarentena = pd.concat(rejeitados, ignore_index=True) if rejeitados else pd.DataFrame(columns=["matricula", "motivo"])
    return limpos[COLUNAS_STAGING], quarentena


def limpar_folha(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    repetida = df.duplicated(["matricula", "competencia"])
    return df.loc[~repetida], int(repetida.sum())


def limpar_afastamentos(df: pd.DataFrame, regras: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    tipos = {chave(grafia): tipo for tipo, grafias in regras.items() for grafia in grafias}
    df = df.assign(tipo=df["tipo"].map(lambda t: tipos.get(chave(t))))
    repetido = df.duplicated(["matricula", "tipo", "inicio", "fim"])
    sem_fim = df["fim"].isna()
    invertido = df["fim"] < df["inicio"]
    motivo = pd.Series(None, index=df.index, dtype="object")
    for mascara, texto in [(repetido, "repetido"), (sem_fim, "sem_data_fim"), (invertido, "fim_antes_do_inicio"), (df["tipo"].isna(), "tipo_desconhecido")]:
        motivo = motivo.mask(mascara & motivo.isna(), texto)
    return df[motivo.isna()], df[motivo.notna()].assign(motivo=motivo[motivo.notna()])
