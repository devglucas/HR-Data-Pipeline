"""Gráficos do relatório de pessoas."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.getLogger("matplotlib").setLevel(logging.WARNING)

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]
CINZA, TINTA_2, GRADE, EIXO, SUPERFICIE = "#b5b3ab", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _estilo() -> None:
    plt.rcParams.update({
        "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE, "font.size": 11,
        "axes.edgecolor": EIXO, "axes.labelcolor": TINTA_2, "xtick.color": TINTA_2, "ytick.color": TINTA_2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRADE,
        "axes.axisbelow": True, "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlepad": 24, "axes.titlelocation": "left",
    })


def _salvar(fig, pasta: Path, nome: str) -> None:
    fig.tight_layout()
    fig.savefig(pasta / f"{nome}.png", dpi=150)
    plt.close(fig)


def _rotulos_mes(ax, datas: pd.Series, passo: int = 3) -> None:
    datas = pd.to_datetime(datas).reset_index(drop=True)
    indices = list(range(0, len(datas), passo))
    ax.set_xticks(indices, [f"{MESES[datas[i].month - 1]}/{datas[i]:%y}" for i in indices])


def _legenda_superior(ax, colunas: int) -> None:
    ax.legend(frameon=False, ncols=colunas, loc="lower left", bbox_to_anchor=(0, 1.0), borderaxespad=0, fontsize=10)


def saidas_mensais(turnover: pd.DataFrame, pasta: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    posicoes = np.arange(len(turnover))
    base = np.zeros(len(turnover))
    for coluna, nome, cor in [("voluntarios", "Pedido de demissão", SERIES[0]), ("involuntarios", "Dispensa", SERIES[1]),
                              ("fim_de_contrato", "Fim de contrato", SERIES[2]), ("nao_informados", "Não informado", CINZA)]:
        ax.bar(posicoes, turnover[coluna], bottom=base, color=cor, label=nome, width=0.8)
        base = base + turnover[coluna].to_numpy()
    _rotulos_mes(ax, turnover["mes"])
    ax.set_ylabel("Desligamentos no mês")
    ax.set_title("A reestruturação de agosto de 2024 concentrou as dispensas")
    _legenda_superior(ax, 4)
    _salvar(fig, pasta, "01_desligamentos_mensais")


def turnover_12_meses(turnover: pd.DataFrame, pasta: Path) -> None:
    dados = turnover.dropna(subset=["taxa_12_meses"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    ax.plot(dados.index, dados["taxa_12_meses"] * 100, color=SERIES[0], linewidth=2.2)
    fim = dados["taxa_12_meses"].iat[-1] * 100
    ax.annotate(f"{fim:.1f}%", (dados.index[-1], fim), textcoords="offset points", xytext=(0, 9), ha="center", color=TINTA_2)
    _rotulos_mes(ax, dados["mes"])
    ax.set_ylim(0, 40)
    ax.set_ylabel("Turnover em 12 meses (%)")
    ax.set_title("A reestruturação elevou o turnover em 12 meses de 26% para 31%")
    _salvar(fig, pasta, "02_turnover_12_meses")


def turnover_area(tabela: pd.DataFrame, pasta: Path) -> None:
    dados = tabela.sort_values("turnover_anualizado")
    fig, ax = plt.subplots(figsize=(9, 4.6))
    barras = ax.barh(dados["departamento"], dados["turnover_anualizado"] * 100, color=SERIES[0])
    ax.bar_label(barras, fmt="%.0f%%", padding=4, color=TINTA_2)
    ax.grid(False)
    ax.set_xlabel("Turnover anualizado (%)")
    ax.set_title("Customer Success perde quase metade da equipe por ano")
    ax.margins(x=0.1)
    _salvar(fig, pasta, "03_turnover_por_area")


def gestores_comercial(tabela: pd.DataFrame, pasta: Path) -> None:
    dados = tabela[tabela["departamento"] == "Comercial"].sort_values("turnover_anualizado")
    area = dados["turnover_da_area"].iat[0] * 100
    fig, ax = plt.subplots(figsize=(9, 4.6))
    maior = dados["turnover_anualizado"].max()
    cores = [SERIES[1] if v == maior else SERIES[0] for v in dados["turnover_anualizado"]]
    barras = ax.barh([f"Gestor {m}" for m in dados["gestor_matricula"]], dados["turnover_anualizado"] * 100, color=cores)
    ax.bar_label(barras, fmt="%.0f%%", label_type="center", color="white", fontweight="bold")
    ax.axvline(area, color=TINTA_2, linewidth=1)
    ax.text(area + 1, -0.42, f"média da área: {area:.0f}%", color=TINTA_2, fontsize=9)
    ax.grid(False)
    ax.set_xlabel("Turnover anualizado da equipe (%)")
    ax.set_title("No Comercial, a saída se concentra na equipe de um gestor")
    ax.margins(x=0.1)
    _salvar(fig, pasta, "04_turnover_por_gestor")


def gap_salarial(tabela: pd.DataFrame, pasta: Path) -> None:
    dados = tabela.sort_values("diferenca", ascending=False)
    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    cores = [SERIES[1] if a in ("Tecnologia", "Comercial") else CINZA for a in dados["departamento"]]
    barras = ax.barh(dados["cargo"], dados["diferenca"] * 100, color=cores)
    ax.bar_label(barras, fmt="%.1f%%", padding=4, color=TINTA_2, fontsize=9)
    ax.axvline(0, color=TINTA_2, linewidth=1)
    ax.grid(False)
    ax.set_xlabel("Salário médio das mulheres em relação ao dos homens (%)")
    fig.suptitle("As maiores diferenças no mesmo cargo estão em Tecnologia e Comercial (em laranja)", x=0.02, ha="left", fontsize=13, fontweight="bold")
    ax.margins(x=0.12)
    _salvar(fig, pasta, "05_diferenca_salarial")


def saida_precoce(tabela: pd.DataFrame, pasta: Path) -> None:
    dados = tabela.pivot(index="departamento", columns="dias", values="taxa_saida").loc[["Customer Success", "Operações", "Comercial", "Tecnologia"]]
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    posicoes, largura = np.arange(len(dados)), 0.27
    for i, dias in enumerate(dados.columns):
        barras = ax.bar(posicoes + (i - 1) * largura, dados[dias] * 100, largura - 0.02, color=SERIES[i], label=f"Até {dias} dias")
        ax.bar_label(barras, fmt="%.0f%%", padding=3, fontsize=9, color=TINTA_2)
    ax.set_xticks(posicoes, dados.index)
    ax.set_ylabel("Admitidos que saíram (%)")
    ax.set_title("Comercial e Customer Success perdem mais de um terço dos admitidos em um ano")
    _legenda_superior(ax, 3)
    ax.margins(y=0.12)
    _salvar(fig, pasta, "06_saida_no_primeiro_ano")


def gerar(t: dict[str, pd.DataFrame], pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    _estilo()
    saidas_mensais(t["turnover_mensal"], pasta)
    turnover_12_meses(t["turnover_mensal"], pasta)
    turnover_area(t["turnover_departamento"], pasta)
    gestores_comercial(t["turnover_gestor"], pasta)
    gap_salarial(t["gap_salarial"], pasta)
    saida_precoce(t["retencao_admissao"], pasta)
