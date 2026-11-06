"""
Verificações depois da carga. Críticas marcam a execução como malsucedida; alertas são
achados de negócio que alguém precisa olhar, e não erros do pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

from src.settings import ROOT_DIR


def _item(nome: str, severidade: str, ok: bool, detalhe: str) -> dict:
    return {"verificacao": nome, "severidade": severidade, "ok": bool(ok), "detalhe": detalhe}


def _valor(conexao: psycopg.Connection, consulta: str):
    return conexao.execute(consulta).fetchone()[0]


def verificar_historico(conexao: psycopg.Connection) -> list[dict]:
    lacunas = _valor(conexao, """
        SELECT count(*) FROM (
            SELECT valido_ate, lead(valido_de) OVER (PARTITION BY matricula ORDER BY valido_de) AS proxima FROM rh.historico_posicao
        ) t WHERE proxima IS NOT NULL AND proxima <> valido_ate""")
    ativos_sem_versao = _valor(conexao, """
        SELECT count(*) FROM rh.vinculo v
        WHERE v.desligamento IS NULL AND NOT EXISTS (SELECT 1 FROM rh.historico_posicao h WHERE h.matricula = v.matricula AND h.valido_ate IS NULL)""")
    desligados_abertos = _valor(conexao, """
        SELECT count(*) FROM rh.historico_posicao h JOIN rh.vinculo v USING (matricula)
        WHERE h.valido_ate IS NULL AND v.desligamento IS NOT NULL""")
    sem_gestor = _valor(conexao, """
        SELECT count(*) FROM rh.historico_posicao h JOIN rh.cargo c USING (cargo_id)
        WHERE h.valido_ate IS NULL AND h.gestor_matricula IS NULL AND c.nivel <> 'Presidente'""")
    return [
        _item("histórico sem lacunas entre versões", "critica", lacunas == 0, f"{lacunas} lacunas"),
        _item("todo ativo tem uma versão atual", "critica", ativos_sem_versao == 0, f"{ativos_sem_versao} sem versão"),
        _item("desligado não tem versão aberta", "critica", desligados_abertos == 0, f"{desligados_abertos} abertas"),
        _item("todo ativo tem gestor, exceto a presidência", "critica", sem_gestor == 0, f"{sem_gestor} sem gestor"),
    ]


def verificar_gabarito(conexao: psycopg.Connection, caminho: Path = ROOT_DIR / "data" / "external" / "gabarito.json") -> list[dict]:
    """Compara o banco com a verdade do gerador. Saídas silenciosas perdem o motivo, então o total é que deve bater."""
    if not caminho.exists():
        return []
    g = json.loads(caminho.read_text(encoding="utf-8"))
    headcount = {f"{m:%Y-%m}": n for m, n in conexao.execute("SELECT mes, count(*) FROM rh.posicao_mensal GROUP BY 1").fetchall()}
    diferentes = [m for m, n in g["headcount_por_mes"].items() if headcount.get(m) != n]
    conjunto = lambda consulta: {r[0] for r in conexao.execute(consulta).fetchall()}
    contagens = {
        "vinculos": _valor(conexao, "SELECT count(*) FROM rh.vinculo"), "pessoas": _valor(conexao, "SELECT count(*) FROM rh.pessoa"),
        "desligamentos": _valor(conexao, "SELECT count(*) FROM rh.vinculo WHERE desligamento IS NOT NULL"),
        "contratados_no_periodo": _valor(conexao, "SELECT count(*) FROM rh.vinculo WHERE admissao >= DATE '2023-01-01'"),
    }
    recontratados = _valor(conexao, "SELECT count(*) - count(DISTINCT pessoa_id) FROM rh.vinculo")
    silenciosos = conjunto("SELECT matricula FROM rh.vinculo WHERE desligamento_inferido")
    fantasmas = conjunto("SELECT matricula FROM analytics.pagamentos_apos_desligamento")
    ciclo = conjunto("SELECT matricula FROM analytics.ciclos_gestao")
    itens = [_item(f"gabarito: {nome}", "critica", valor == g[nome], f"{valor} x {g[nome]}") for nome, valor in contagens.items()]
    return itens + [
        _item("gabarito: headcount dos 30 meses", "critica", not diferentes, f"{len(diferentes)} meses diferentes"),
        _item("gabarito: recontratações", "critica", recontratados == g["recontratacoes"], f"{recontratados} x {g['recontratacoes']}"),
        _item("gabarito: desligamentos silenciosos", "critica", silenciosos == set(g["desligamentos_silenciosos"]), f"{len(silenciosos)} encontrados"),
        _item("gabarito: pagamentos após desligamento", "critica", fantasmas == set(g["pagos_apos_desligamento"]), f"{len(fantasmas)} matrículas"),
        _item("gabarito: ciclo de gestão", "critica", ciclo == {g["ciclo_de_gestao"]["gerente"], g["ciclo_de_gestao"]["subordinado"]}, f"{len(ciclo)} matrículas"),
    ]


def verificar_folha(conexao: psycopg.Connection) -> list[dict]:
    sem_folha = _valor(conexao, "SELECT count(*) FROM analytics.ativos_sem_folha")
    retroativos = _valor(conexao, "SELECT count(*) FROM analytics.salario_divergente WHERE lancamento_retroativo")
    promocoes = _valor(conexao, "SELECT count(*) FROM analytics.promocoes WHERE registrada_com_atraso")
    return [
        _item("todo ativo foi pago no mês", "critica", sem_folha == 0, f"{sem_folha} sem pagamento"),
        _item("divergência de salário explicada por lançamento retroativo", "critica", retroativos == promocoes, f"{retroativos} divergências, {promocoes} promoções com atraso"),
    ]


def verificar_anonimizacao(resumo: dict) -> list[dict]:
    return [_item("k-anonimato da base do analista", "critica", (resumo["menor_grupo"] or 0) >= resumo["k"],
                  f"menor grupo: {resumo['menor_grupo']}, k = {resumo['k']}, {resumo['suprimidos']} suprimidos")]


def alertas_de_negocio(conexao: psycopg.Connection) -> list[dict]:
    pagos = conexao.execute("SELECT count(DISTINCT matricula), coalesce(sum(liquido), 0) FROM analytics.pagamentos_apos_desligamento").fetchone()
    inferidos = _valor(conexao, "SELECT count(*) FROM rh.vinculo WHERE desligamento_inferido")
    ciclos = _valor(conexao, "SELECT count(DISTINCT mes) FROM analytics.ciclos_gestao")
    return [
        _item("ninguém recebe depois de sair", "alerta", pagos[0] == 0, f"{pagos[0]} pessoas, R$ {pagos[1]:.2f} líquidos"),
        _item("todo desligamento foi informado", "alerta", inferidos == 0, f"{inferidos} inferidos"),
        _item("cadeia de gestão sem ciclos", "alerta", ciclos == 0, f"{ciclos} meses com ciclo"),
    ]


def falhas_criticas(verificacoes: list[dict]) -> list[dict]:
    return [v for v in verificacoes if v["severidade"] == "critica" and not v["ok"]]
