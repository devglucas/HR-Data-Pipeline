"""Lê do banco os indicadores que vão para o relatório. As regras ficam nas views."""

from __future__ import annotations

import pandas as pd
import psycopg

from src.db import consultar

CONSULTAS = {
    "headcount_mensal": "SELECT * FROM analytics.headcount_mensal ORDER BY mes, departamento",
    "turnover_mensal": "SELECT * FROM analytics.turnover_mensal ORDER BY mes",
    "turnover_departamento": "SELECT * FROM analytics.turnover_departamento ORDER BY turnover_anualizado DESC",
    "turnover_gestor": "SELECT * FROM analytics.turnover_gestor WHERE pessoas_mes >= 120",
    "retencao_admissao": "SELECT * FROM analytics.retencao_admissao ORDER BY departamento, dias",
    "gap_salarial": "SELECT * FROM analytics.gap_salarial ORDER BY diferenca",
    "estrutura_gestao": "SELECT * FROM analytics.estrutura_gestao ORDER BY camada",
    "ciclos_gestao": "SELECT * FROM analytics.ciclos_gestao ORDER BY mes, matricula",
    "absenteismo": "SELECT * FROM analytics.absenteismo ORDER BY taxa_absenteismo DESC",
    "pagamentos_apos_desligamento": "SELECT * FROM analytics.pagamentos_apos_desligamento ORDER BY matricula, competencia",
    "promocoes_por_area": """SELECT departamento, count(*) AS promocoes, round(avg(meses_de_casa), 1) AS meses_de_casa_medio,
                                    count(*) FILTER (WHERE registrada_com_atraso) AS registradas_com_atraso
                             FROM analytics.promocoes GROUP BY 1 ORDER BY 2 DESC""",
    "quarentena": "SELECT origem, motivo, count(*) AS linhas FROM etl.quarentena GROUP BY 1, 2 ORDER BY 1, 3 DESC",
    "cargas": """SELECT to_char(competencia, 'YYYY-MM') AS competencia, linhas_lidas, linhas_aplicadas, linhas_quarentena, versoes_criadas
                 FROM etl.carga ORDER BY competencia""",
}


def _para_numero(df: pd.DataFrame) -> pd.DataFrame:
    """O driver devolve numeric como Decimal; para gráficos e CSV, float basta."""
    decimais = [c for c in df.columns if df[c].map(lambda v: v.__class__.__name__ == "Decimal").any()]
    return df.astype({c: float for c in decimais})


def indicadores(conexao: psycopg.Connection) -> dict[str, pd.DataFrame]:
    return {nome: _para_numero(consultar(conexao, consulta)) for nome, consulta in CONSULTAS.items()}
