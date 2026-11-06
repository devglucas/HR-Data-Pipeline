-- Foto reconstruída de cada fim de mês, a partir do histórico. As demais views partem dela.
-- Fica no esquema rh porque tem dados individuais.
CREATE MATERIALIZED VIEW rh.posicao_mensal AS
SELECT c.competencia AS mes,
       v.matricula, v.pessoa_id, p.genero, v.admissao, v.contrato,
       h.cargo_id, cg.nome AS cargo, cg.nivel, cg.nivel_ordem,
       h.departamento_id, d.nome AS departamento, u.nome AS unidade,
       h.gestor_matricula, h.salario,
       date_part('year', age(f.fim_mes, p.nascimento))::int AS idade,
       (f.fim_mes - v.admissao) / 30 AS meses_de_casa
FROM etl.carga c
CROSS JOIN LATERAL (SELECT (c.competencia + interval '1 month - 1 day')::date AS fim_mes) f
JOIN rh.vinculo v ON v.admissao <= f.fim_mes AND (v.desligamento IS NULL OR v.desligamento > f.fim_mes)
JOIN rh.pessoa p USING (pessoa_id)
JOIN rh.historico_posicao h ON h.matricula = v.matricula AND daterange(h.valido_de, h.valido_ate) @> f.fim_mes
JOIN rh.cargo cg USING (cargo_id)
JOIN rh.departamento d USING (departamento_id)
JOIN rh.unidade u USING (unidade_id)
WITH NO DATA;
CREATE UNIQUE INDEX posicao_mensal_chave ON rh.posicao_mensal (mes, matricula);

-- A última posição de cada vínculo: de onde a pessoa saiu.
CREATE VIEW rh.ultima_posicao AS
SELECT DISTINCT ON (h.matricula) h.*, d.nome AS departamento, cg.nivel, cg.nivel_ordem
FROM rh.historico_posicao h
JOIN rh.departamento d USING (departamento_id)
JOIN rh.cargo cg USING (cargo_id)
ORDER BY h.matricula, h.valido_de DESC;

CREATE VIEW analytics.headcount_mensal AS
SELECT mes, departamento, count(*) AS headcount
FROM rh.posicao_mensal
GROUP BY mes, departamento;

CREATE VIEW analytics.turnover_mensal AS
WITH hc AS (
    SELECT mes, count(*) AS final FROM rh.posicao_mensal GROUP BY mes
), saidas AS (
    SELECT date_trunc('month', desligamento)::date AS mes,
           count(*) AS desligamentos,
           count(*) FILTER (WHERE motivo = 'Pedido de demissão') AS voluntarios,
           count(*) FILTER (WHERE motivo IN ('Dispensa sem justa causa', 'Justa causa')) AS involuntarios,
           count(*) FILTER (WHERE motivo = 'Fim de contrato') AS fim_de_contrato,
           count(*) FILTER (WHERE desligamento_inferido) AS nao_informados
    FROM rh.vinculo WHERE desligamento IS NOT NULL GROUP BY 1
), base AS (
    SELECT hc.mes, hc.final, coalesce(lag(hc.final) OVER (ORDER BY hc.mes), hc.final) AS inicial,
           coalesce(s.desligamentos, 0) AS desligamentos, coalesce(s.voluntarios, 0) AS voluntarios,
           coalesce(s.involuntarios, 0) AS involuntarios, coalesce(s.fim_de_contrato, 0) AS fim_de_contrato,
           coalesce(s.nao_informados, 0) AS nao_informados
    FROM hc LEFT JOIN saidas s USING (mes)
)
SELECT mes, inicial AS headcount_inicial, final AS headcount_final, desligamentos, voluntarios, involuntarios, fim_de_contrato, nao_informados,
       round(desligamentos / ((inicial + final) / 2.0), 4) AS taxa_mensal,
       -- a janela só existe com 12 meses completos; antes disso a taxa ficaria subestimada
       CASE WHEN count(*) OVER janela = 12 THEN
           round(sum(desligamentos) OVER janela / avg((inicial + final) / 2.0) OVER janela, 4) END AS taxa_12_meses
FROM base
WINDOW janela AS (ORDER BY mes ROWS BETWEEN 11 PRECEDING AND CURRENT ROW);

CREATE VIEW analytics.turnover_departamento AS
WITH exposicao AS (
    SELECT departamento_id, departamento, count(*) AS pessoas_mes FROM rh.posicao_mensal GROUP BY 1, 2
), saidas AS (
    SELECT u.departamento_id, count(*) AS desligamentos,
           count(*) FILTER (WHERE v.motivo = 'Pedido de demissão') AS voluntarios
    FROM rh.vinculo v JOIN rh.ultima_posicao u USING (matricula)
    WHERE v.desligamento IS NOT NULL GROUP BY 1
)
SELECT e.departamento, e.pessoas_mes, s.desligamentos, s.voluntarios,
       round(s.desligamentos * 12.0 / e.pessoas_mes, 4) AS turnover_anualizado
FROM exposicao e JOIN saidas s USING (departamento_id);

-- Turnover pelo gestor imediato no momento da saída, comparado com a própria área.
-- Fim de contrato não conta, e equipes pequenas ficam de fora: a taxa seria ruído.
CREATE VIEW analytics.turnover_gestor AS
WITH exposicao AS (
    SELECT gestor_matricula, departamento_id, departamento, count(*) AS pessoas_mes
    FROM rh.posicao_mensal WHERE gestor_matricula IS NOT NULL AND nivel_ordem <= 3 GROUP BY 1, 2, 3
), saidas AS (
    SELECT u.gestor_matricula, u.departamento_id, count(*) AS desligamentos
    FROM rh.vinculo v JOIN rh.ultima_posicao u USING (matricula)
    WHERE v.desligamento >= DATE '2023-01-01' AND u.nivel_ordem <= 3 AND v.motivo <> 'Fim de contrato'
    GROUP BY 1, 2
), por_gestor AS (
    SELECT e.gestor_matricula, e.departamento, e.pessoas_mes, coalesce(s.desligamentos, 0) AS desligamentos
    FROM exposicao e LEFT JOIN saidas s USING (gestor_matricula, departamento_id)
)
SELECT gestor_matricula, departamento, pessoas_mes, desligamentos,
       round(desligamentos * 12.0 / pessoas_mes, 4) AS turnover_anualizado,
       round(sum(desligamentos) OVER area * 12.0 / sum(pessoas_mes) OVER area, 4) AS turnover_da_area
FROM por_gestor
WINDOW area AS (PARTITION BY departamento)
ORDER BY turnover_anualizado DESC;

-- Quem saiu cedo. Só conta quem já teve tempo de completar cada prazo até o fim dos dados.
CREATE VIEW analytics.retencao_admissao AS
WITH limite AS (
    SELECT (max(competencia) + interval '1 month - 1 day')::date AS fim FROM etl.carga
), admitidos AS (
    SELECT v.matricula, v.admissao, v.desligamento, u.departamento
    FROM rh.vinculo v JOIN rh.ultima_posicao u USING (matricula)
    WHERE v.admissao >= DATE '2023-01-01'
)
SELECT a.departamento, p.dias, count(*) AS admitidos,
       count(*) FILTER (WHERE a.desligamento < a.admissao + p.dias) AS sairam,
       round(count(*) FILTER (WHERE a.desligamento < a.admissao + p.dias) / count(*)::numeric, 4) AS taxa_saida
FROM admitidos a
CROSS JOIN limite l
CROSS JOIN (VALUES (90), (180), (365)) AS p(dias)
WHERE a.admissao + p.dias <= l.fim
GROUP BY a.departamento, p.dias;

CREATE VIEW analytics.promocoes AS
WITH versoes AS (
    SELECT h.matricula, h.valido_de, h.registrado_em, c.nivel, c.nivel_ordem, d.nome AS departamento, v.admissao,
           lag(c.nivel_ordem) OVER (PARTITION BY h.matricula ORDER BY h.valido_de) AS nivel_anterior
    FROM rh.historico_posicao h
    JOIN rh.cargo c USING (cargo_id)
    JOIN rh.departamento d USING (departamento_id)
    JOIN rh.vinculo v USING (matricula)
)
SELECT matricula, departamento, nivel, valido_de, registrado_em, (valido_de - admissao) / 30 AS meses_de_casa,
       date_trunc('month', valido_de) < registrado_em AS registrada_com_atraso
FROM versoes
WHERE nivel_ordem > nivel_anterior;

-- Diferença salarial no mesmo cargo. A comparação só é feita com pelo menos 5 pessoas de cada gênero.
CREATE VIEW analytics.gap_salarial AS
WITH ultimo AS (SELECT * FROM rh.posicao_mensal WHERE mes = (SELECT max(mes) FROM rh.posicao_mensal)),
por_cargo AS (
    SELECT departamento, cargo, nivel_ordem,
           count(*) FILTER (WHERE genero = 'F') AS mulheres, count(*) FILTER (WHERE genero = 'M') AS homens,
           avg(salario) FILTER (WHERE genero = 'F') AS media_f, avg(salario) FILTER (WHERE genero = 'M') AS media_m
    FROM ultimo GROUP BY 1, 2, 3
)
SELECT departamento, cargo, mulheres, homens, round(media_f, 2) AS media_mulheres, round(media_m, 2) AS media_homens,
       round(media_f / media_m - 1, 4) AS diferenca
FROM por_cargo
WHERE mulheres >= 5 AND homens >= 5;

CREATE VIEW analytics.estrutura_gestao AS
WITH RECURSIVE ultimo AS (
    SELECT * FROM rh.posicao_mensal WHERE mes = (SELECT max(mes) FROM rh.posicao_mensal)
), arvore AS (
    SELECT matricula, 1 AS camada FROM ultimo WHERE gestor_matricula IS NULL
    UNION ALL
    SELECT u.matricula, a.camada + 1 FROM ultimo u JOIN arvore a ON u.gestor_matricula = a.matricula
) CYCLE matricula SET em_ciclo USING caminho
SELECT a.camada, count(*) AS pessoas,
       round(avg(l.liderados) FILTER (WHERE l.liderados > 0), 1) AS media_liderados,
       max(l.liderados) AS maximo_liderados
FROM arvore a
LEFT JOIN LATERAL (SELECT count(*) AS liderados FROM ultimo u WHERE u.gestor_matricula = a.matricula) l ON true
WHERE NOT a.em_ciclo
GROUP BY a.camada;

-- Sobe a cadeia de gestão a partir de cada pessoa, mês a mês; a cláusula CYCLE acusa quem volta a si mesmo.
CREATE VIEW analytics.ciclos_gestao AS
WITH RECURSIVE cadeia AS (
    SELECT mes, matricula, gestor_matricula FROM rh.posicao_mensal
    UNION ALL
    SELECT c.mes, p.matricula, p.gestor_matricula
    FROM cadeia c JOIN rh.posicao_mensal p ON p.mes = c.mes AND p.matricula = c.gestor_matricula
) CYCLE matricula, mes SET em_ciclo USING caminho
SELECT DISTINCT mes, matricula FROM cadeia WHERE em_ciclo;

-- Folha contra cadastro: três perguntas que uma auditoria faria.
CREATE VIEW analytics.pagamentos_apos_desligamento AS
SELECT f.matricula, f.competencia, v.desligamento, v.desligamento_inferido, f.liquido
FROM rh.folha f JOIN rh.vinculo v USING (matricula)
WHERE f.competencia > date_trunc('month', v.desligamento);

CREATE VIEW analytics.ativos_sem_folha AS
SELECT p.mes, p.matricula
FROM rh.posicao_mensal p LEFT JOIN rh.folha f ON f.matricula = p.matricula AND f.competencia = p.mes
WHERE f.matricula IS NULL;

CREATE VIEW analytics.salario_divergente AS
WITH comparacao AS (
    SELECT f.matricula, f.competencia, f.salario_base, h.salario AS salario_cadastro, h.registrado_em
    FROM rh.folha f
    JOIN rh.vinculo v USING (matricula)
    JOIN rh.historico_posicao h ON h.matricula = f.matricula AND daterange(h.valido_de, h.valido_ate) @> LEAST(
        (f.competencia + interval '1 month - 1 day')::date, v.desligamento - 1)
    WHERE f.competencia <= coalesce(date_trunc('month', v.desligamento), f.competencia)
)
SELECT c.*, c.registrado_em > c.competencia AS lancamento_retroativo
FROM comparacao c
WHERE c.salario_base <> c.salario_cadastro;

CREATE VIEW analytics.absenteismo AS
WITH dias AS (
    SELECT a.matricula, date_trunc('month', d)::date AS mes, count(*) AS dias_atestado
    FROM rh.afastamento a
    CROSS JOIN LATERAL generate_series(lower(a.periodo), upper(a.periodo) - 1, interval '1 day') AS d
    WHERE a.tipo = 'atestado'
    GROUP BY 1, 2
)
SELECT p.departamento, count(*) AS pessoas_mes, coalesce(sum(d.dias_atestado), 0) AS dias_atestado,
       round(coalesce(sum(d.dias_atestado), 0) / (count(*) * 30.0), 4) AS taxa_absenteismo
FROM rh.posicao_mensal p
LEFT JOIN dias d ON d.matricula = p.matricula AND d.mes = p.mes
GROUP BY p.departamento;
