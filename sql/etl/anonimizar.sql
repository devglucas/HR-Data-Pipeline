TRUNCATE anon.colaborador;

-- Pseudônimo com HMAC: sem a chave, não dá para refazer o cálculo a partir das matrículas.
-- Idade, tempo de casa e salário viram faixas. Grupos menores que k são suprimidos.
INSERT INTO anon.colaborador
WITH base AS (
    SELECT left(encode(hmac(v.matricula::text, %(chave)s, 'sha256'), 'hex'), 16) AS pseudonimo,
           u.departamento,
           CASE WHEN u.nivel_ordem <= 3 THEN 'Operacional' ELSE 'Liderança' END AS grupo_nivel,
           CASE WHEN idade < 30 THEN 'até 29' WHEN idade < 40 THEN '30 a 39' WHEN idade < 50 THEN '40 a 49' ELSE '50 ou mais' END AS faixa_etaria,
           p.genero,
           CASE WHEN anos < 1 THEN 'até 1 ano' WHEN anos < 3 THEN '1 a 3 anos' WHEN anos < 6 THEN '3 a 6 anos' ELSE '6 anos ou mais' END AS faixa_tempo_casa,
           CASE WHEN u.salario < 3000 THEN 'até 3 mil' WHEN u.salario < 6000 THEN '3 a 6 mil' WHEN u.salario < 12000 THEN '6 a 12 mil' ELSE 'acima de 12 mil' END AS faixa_salarial,
           CASE WHEN v.desligamento IS NULL THEN 'Ativo' ELSE 'Desligado' END AS situacao
    FROM rh.vinculo v
    JOIN rh.pessoa p USING (pessoa_id)
    JOIN rh.ultima_posicao u USING (matricula)
    CROSS JOIN LATERAL (SELECT date_part('year', age(coalesce(v.desligamento, %(referencia)s), p.nascimento))::int AS idade,
                               date_part('year', age(coalesce(v.desligamento, %(referencia)s), v.admissao))::int AS anos) t
), grupos AS (
    SELECT *, count(*) OVER (PARTITION BY departamento, grupo_nivel, faixa_etaria, genero) AS tamanho FROM base
)
SELECT pseudonimo, departamento, grupo_nivel, faixa_etaria, genero, faixa_tempo_casa, faixa_salarial, situacao
FROM grupos
WHERE tamanho >= %(k)s;
