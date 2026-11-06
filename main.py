"""
Pipeline de RH: arquivos -> limpeza -> PostgreSQL (histórico) -> indicadores -> relatório.

    docker compose up -d --wait    sobe o banco
    python main.py                 carrega o que ainda não foi carregado
    python main.py --recriar       apaga o banco e reprocessa tudo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql

from src import analyze, anonymize, clean, load, quality, report, visualize
from src.db import aplicar_migracoes, conectar, consultar, definir_senha_do_analista
from src.settings import OUTPUT_DIR, RAW_DIR, carregar, segredo
from src.utils import configurar_logger, gravar_logs_em

log = configurar_logger("main")


def recriar_banco(banco: str) -> None:
    with conectar("postgres") as manutencao:
        manutencao.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(banco)))
        manutencao.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(banco)))


def executar(banco: str, saida: Path = OUTPUT_DIR) -> dict:
    inicio = time.perf_counter()
    config = carregar()
    cat = clean.catalogos(config)
    with conectar(banco) as conexao:
        migracoes = aplicar_migracoes(conexao)
        definir_senha_do_analista(conexao)
        load.semear_catalogos(conexao, config, cat)

        cargas = [r for r in (load.aplicar_foto(conexao, f, cat) for f in sorted((RAW_DIR / "rh").glob("*.csv"))) if r]
        log.info("fotos novas: %d | versões criadas: %d", len(cargas), sum(c["versoes"] for c in cargas))
        folha = load.carregar_folha(conexao, sorted((RAW_DIR / "folha").glob("*.csv")))
        afastamentos = load.carregar_afastamentos(conexao, RAW_DIR / "ponto" / "afastamentos.json", config["afastamentos"])
        log.info("folha: %s | afastamentos: %s", folha, afastamentos)

        conexao.execute("REFRESH MATERIALIZED VIEW rh.posicao_mensal")
        anon = anonymize.atualizar(conexao, config["anonimizacao"]["k"])
        verificacoes = [*quality.verificar_historico(conexao), *quality.verificar_gabarito(conexao), *quality.verificar_folha(conexao),
                        *quality.verificar_anonimizacao(anon), *quality.alertas_de_negocio(conexao)]
        falhas = quality.falhas_criticas(verificacoes)

        tabelas = analyze.indicadores(conexao)
        resumo = {"versoes": conexao.execute("SELECT count(*) FROM rh.historico_posicao").fetchone()[0]}
        base_anonima = consultar(conexao, "SELECT * FROM anon.colaborador ORDER BY pseudonimo")

    report.exportar({**tabelas, "colaboradores_anonimizados": base_anonima}, saida / "reports")
    report.escrever(tabelas, verificacoes, resumo, anon, saida / "relatorio.md")
    visualize.gerar(tabelas, saida / "charts")

    manifesto = {
        "executado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sucesso": not falhas,
        "duracao_s": round(time.perf_counter() - inicio, 2), "migracoes_aplicadas": migracoes, "fotos_carregadas": len(cargas), "folha": folha,
        "afastamentos": afastamentos, "anonimizacao": anon,
        "verificacoes": {"total": len(verificacoes), "criticas_com_falha": len(falhas), "alertas": sum(v["severidade"] == "alerta" and not v["ok"] for v in verificacoes)},
    }
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "run_manifest.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    for falha in falhas:
        log.error("verificação crítica falhou: %s (%s)", falha["verificacao"], falha["detalhe"])
    log.info("concluído em %.1fs | %d verificações, %d críticas com falha", manifesto["duracao_s"], len(verificacoes), len(falhas))
    return {"manifesto": manifesto, "verificacoes": verificacoes, "tabelas": tabelas, "cargas": cargas}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recriar", action="store_true", help="apaga o banco e reprocessa todo o histórico")
    argumentos = parser.parse_args()
    gravar_logs_em(OUTPUT_DIR / "logs" / "pipeline.log")
    banco = segredo("POSTGRES_DB")
    try:
        if argumentos.recriar:
            recriar_banco(banco)
        resultado = executar(banco)
    except psycopg.OperationalError as erro:
        log.error("sem conexão com o PostgreSQL. Rode `docker compose up -d --wait`. Detalhe: %s", erro)
        return 2
    return 0 if resultado["manifesto"]["sucesso"] else 1


if __name__ == "__main__":
    sys.exit(main())
