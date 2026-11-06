"""
Carga no PostgreSQL. O Python cuida da limpeza; o histórico é montado em SQL, dentro de uma transação.

Fotos só andam para a frente: a sequência importa para o histórico, então um arquivo já
processado é ignorado, e o mesmo mês com conteúdo diferente é erro.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import psycopg

from src import clean, extract
from src.db import copiar, executar_arquivo
from src.settings import SQL_DIR
from src.utils import configurar_logger

log = configurar_logger("load")


class CargaForaDeOrdem(Exception):
    pass


def semear_catalogos(conexao: psycopg.Connection, config: dict, cat: dict) -> None:
    for codigo, regra in config["departamentos"].items():
        conexao.execute("INSERT INTO rh.departamento (codigo, nome) VALUES (%s, %s) ON CONFLICT (codigo) DO NOTHING", (codigo, regra["apelidos"][0]))
    for unidade in config["unidades"]:
        conexao.execute("INSERT INTO rh.unidade (nome) VALUES (%s) ON CONFLICT (nome) DO NOTHING", (unidade,))
    for nome, faixa in cat["faixas"].items():
        conexao.execute("""
            INSERT INTO rh.cargo (nome, nivel, nivel_ordem, faixa_min, faixa_max)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (nome) DO UPDATE SET faixa_min = EXCLUDED.faixa_min, faixa_max = EXCLUDED.faixa_max""",
                        (nome, faixa["nivel"], faixa["nivel_ordem"], faixa["faixa_min"], faixa["faixa_max"]))


def _registrar_quarentena(conexao: psycopg.Connection, df: pd.DataFrame, origem: str, competencia=None) -> None:
    for linha in df.to_dict("records"):
        conexao.execute("INSERT INTO etl.quarentena (origem, competencia, matricula, motivo, registro) VALUES (%s, %s, %s, %s, %s)",
                        (origem, competencia, str(linha.get("matricula")), linha["motivo"],
                         json.dumps({k: v for k, v in linha.items() if k not in ("matricula", "motivo") and pd.notna(v)}, default=str, ensure_ascii=False)))


def aplicar_foto(conexao: psycopg.Connection, caminho: Path, cat: dict) -> dict | None:
    competencia = pd.Timestamp(caminho.stem.split("_")[1] + "-01")
    assinatura = hashlib.sha256(caminho.read_bytes()).hexdigest()
    ja_carregada = conexao.execute("SELECT hash FROM etl.carga WHERE competencia = %s", (competencia,)).fetchone()
    if ja_carregada:
        if ja_carregada[0] != assinatura:
            raise CargaForaDeOrdem(f"{caminho.name} mudou depois de carregado: recrie o banco para reprocessar o histórico")
        return None
    ultima = conexao.execute("SELECT max(competencia) FROM etl.carga").fetchone()[0]
    if ultima and competencia < pd.Timestamp(ultima):
        raise CargaForaDeOrdem(f"{caminho.name} é anterior à última competência carregada ({ultima})")

    bruto = extract.ler_foto(caminho)
    limpos, quarentena = clean.limpar_foto(bruto, cat, competencia)
    with conexao.transaction():
        versoes = aplicar_limpos(conexao, limpos, bruto["matricula"], competencia)
        _registrar_quarentena(conexao, quarentena, "foto", competencia)
        conexao.execute("""INSERT INTO etl.carga (competencia, arquivo, hash, linhas_lidas, linhas_aplicadas, linhas_quarentena, versoes_criadas)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (competencia, caminho.name, assinatura, len(bruto), len(limpos), len(quarentena), versoes))
    return {"competencia": f"{competencia:%Y-%m}", "lidas": len(bruto), "aplicadas": len(limpos), "quarentena": len(quarentena), "versoes": versoes}


def aplicar_limpos(conexao: psycopg.Connection, limpos: pd.DataFrame, matriculas: pd.Series, competencia: pd.Timestamp) -> int:
    """Coloca a foto limpa na staging e monta o histórico em SQL. Devolve quantas versões foram criadas."""
    conexao.execute("TRUNCATE staging.foto, staging.presenca")
    copiar(conexao, limpos, "staging", "foto")
    copiar(conexao, pd.DataFrame({"matricula": matriculas}).drop_duplicates(), "staging", "presenca")
    antes = conexao.execute("SELECT count(*) FROM rh.historico_posicao").fetchone()[0]
    executar_arquivo(conexao, SQL_DIR / "etl" / "aplicar_foto.sql", {"competencia": competencia})
    return conexao.execute("SELECT count(*) FROM rh.historico_posicao").fetchone()[0] - antes


def carregar_folha(conexao: psycopg.Connection, arquivos: list[Path]) -> dict:
    """Upsert: reprocessar uma folha corrigida atualiza os valores, sem duplicar."""
    linhas = repetidas = orfas = 0
    for caminho in arquivos:
        df, repetidas_arquivo = clean.limpar_folha(extract.ler_folha(caminho))
        repetidas += repetidas_arquivo
        conhecidas = {r[0] for r in conexao.execute("SELECT matricula FROM rh.vinculo").fetchall()}
        sem_vinculo = df[~df["matricula"].isin(conhecidas)]
        orfas += len(sem_vinculo)
        with conexao.transaction():
            _registrar_quarentena(conexao, sem_vinculo[["matricula", "competencia"]].assign(motivo="folha_sem_vinculo"), "folha")
            conexao.execute("CREATE TEMP TABLE folha_tmp (LIKE rh.folha) ON COMMIT DROP")
            copiar(conexao, df[df["matricula"].isin(conhecidas)], "pg_temp", "folha_tmp")
            resultado = conexao.execute("""
                INSERT INTO rh.folha SELECT * FROM folha_tmp
                ON CONFLICT (matricula, competencia) DO UPDATE
                SET salario_base = EXCLUDED.salario_base, horas_extras = EXCLUDED.horas_extras, retroativo = EXCLUDED.retroativo,
                    descontos = EXCLUDED.descontos, liquido = EXCLUDED.liquido
                WHERE (rh.folha.salario_base, rh.folha.liquido) IS DISTINCT FROM (EXCLUDED.salario_base, EXCLUDED.liquido)""")
            linhas += resultado.rowcount
    return {"linhas": linhas, "repetidas": repetidas, "sem_vinculo": orfas}


def carregar_afastamentos(conexao: psycopg.Connection, caminho: Path, regras: dict) -> dict:
    limpos, rejeitados = clean.limpar_afastamentos(extract.ler_afastamentos(caminho), regras)
    with conexao.transaction():
        conexao.execute("TRUNCATE rh.afastamento")
        conexao.execute("DELETE FROM etl.quarentena WHERE origem = 'afastamento'")
        _registrar_quarentena(conexao, rejeitados, "afastamento")
        conexao.execute("CREATE TEMP TABLE afast_tmp (matricula integer, tipo text, inicio date, fim date) ON COMMIT DROP")
        copiar(conexao, limpos[["matricula", "tipo", "inicio", "fim"]], "pg_temp", "afast_tmp")
        # A constraint de exclusão decide sobre períodos sobrepostos; o que ela barra vai para a quarentena.
        inseridos = conexao.execute("""
            INSERT INTO rh.afastamento (matricula, tipo, periodo)
            SELECT a.matricula, a.tipo, daterange(a.inicio, a.fim, '[]')
            FROM afast_tmp a JOIN rh.vinculo v USING (matricula)
            ORDER BY a.inicio
            ON CONFLICT ON CONSTRAINT afastamento_sem_sobreposicao DO NOTHING""").rowcount
        conexao.execute("""
            INSERT INTO etl.quarentena (origem, matricula, motivo, registro)
            SELECT 'afastamento', a.matricula::text, 'periodo_sobreposto', jsonb_build_object('tipo', a.tipo, 'inicio', a.inicio, 'fim', a.fim)
            FROM afast_tmp a
            WHERE NOT EXISTS (SELECT 1 FROM rh.afastamento r
                              WHERE r.matricula = a.matricula AND r.tipo = a.tipo AND r.periodo = daterange(a.inicio, a.fim, '[]'))""")
    return {"inseridos": inseridos, "rejeitados": len(rejeitados), "sobrepostos": len(limpos) - inseridos}
