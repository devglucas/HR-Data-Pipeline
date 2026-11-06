"""Relatório em Markdown e exportação das tabelas. Nenhuma saída tem nome ou CPF."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.utils import df_para_markdown, formatar_br


def exportar(tabelas: dict[str, pd.DataFrame], pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, tabela in tabelas.items():
        tabela.to_csv(pasta / f"{nome}.csv", index=False, float_format="%.4f")


def escrever(t: dict[str, pd.DataFrame], verificacoes: list[dict], resumo: dict, anon: dict, destino: Path) -> None:
    turnover = t["turnover_mensal"]
    ultimo = turnover.iloc[-1]
    pagos = t["pagamentos_apos_desligamento"]
    tabela_v = pd.DataFrame(verificacoes).assign(resultado=lambda d: d["ok"].map({True: "ok", False: "falhou"}))
    partes = [
        "# Relatório de pessoas: Nortia Serviços\n",
        "## Resumo\n",
        f"- Headcount final: {formatar_br(int(ultimo['headcount_final']))}",
        f"- Turnover nos últimos 12 meses: {formatar_br(float(ultimo['taxa_12_meses']) * 100, 1)}%",
        f"- Versões no histórico de posições: {formatar_br(resumo['versoes'])}",
        f"- Pagamentos depois do desligamento: {pagos['matricula'].nunique()} pessoas, R$ {formatar_br(float(pagos['liquido'].sum()))}",
        f"- Base anonimizada: {formatar_br(anon['publicados'])} registros publicados e {anon['suprimidos']} suprimidos (k = {anon['k']})\n",
        "## Turnover por área\n", df_para_markdown(t["turnover_departamento"], 4), "",
        "## Turnover por gestor\n", df_para_markdown(t["turnover_gestor"].head(10), 4), "",
        "## Saída nos primeiros meses\n", df_para_markdown(t["retencao_admissao"], 4), "",
        "## Diferença salarial no mesmo cargo\n", df_para_markdown(t["gap_salarial"], 4), "",
        "## Promoções\n", df_para_markdown(t["promocoes_por_area"], 1), "",
        "## Estrutura de gestão\n", df_para_markdown(t["estrutura_gestao"], 1), "",
        "## Absenteísmo por atestados\n", df_para_markdown(t["absenteismo"], 4), "",
        "## Quarentena\n", df_para_markdown(t["quarentena"]), "",
        "## Verificações\n", df_para_markdown(tabela_v[["verificacao", "severidade", "resultado", "detalhe"]]), "",
    ]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(partes), encoding="utf-8")
