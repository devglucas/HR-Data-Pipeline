-- Aplica a foto de uma competência. Roda em uma única transação: ou entra tudo, ou nada.

-- Nome atual da área: atualização simples, sem histórico (SCD tipo 1).
UPDATE rh.departamento d SET nome = n.departamento_nome
FROM (SELECT DISTINCT departamento, departamento_nome FROM staging.foto) n
WHERE d.codigo = n.departamento AND d.nome IS DISTINCT FROM n.departamento_nome;

INSERT INTO rh.pessoa (cpf, nome, nascimento, genero)
SELECT DISTINCT ON (cpf) cpf, nome, nascimento, genero FROM staging.foto ORDER BY cpf, admissao DESC
ON CONFLICT (cpf) DO UPDATE
SET nome = EXCLUDED.nome, nascimento = EXCLUDED.nascimento, genero = EXCLUDED.genero
WHERE (rh.pessoa.nome, rh.pessoa.nascimento, rh.pessoa.genero) IS DISTINCT FROM (EXCLUDED.nome, EXCLUDED.nascimento, EXCLUDED.genero);

INSERT INTO rh.vinculo (matricula, pessoa_id, admissao, desligamento, motivo, contrato)
SELECT f.matricula, p.pessoa_id, f.admissao, f.desligamento, f.motivo, f.contrato
FROM staging.foto f JOIN rh.pessoa p USING (cpf)
ON CONFLICT (matricula) DO UPDATE
SET desligamento = EXCLUDED.desligamento, motivo = EXCLUDED.motivo, contrato = EXCLUDED.contrato
WHERE (rh.vinculo.desligamento, rh.vinculo.motivo, rh.vinculo.contrato) IS DISTINCT FROM (EXCLUDED.desligamento, EXCLUDED.motivo, EXCLUDED.contrato);

-- Gestor que faltava na primeira carga é correção, não mudança: preenche a versão atual.
UPDATE rh.historico_posicao h SET gestor_matricula = f.gestor
FROM staging.foto f JOIN rh.vinculo g ON g.matricula = f.gestor
WHERE h.matricula = f.matricula AND h.valido_ate IS NULL AND h.gestor_matricula IS NULL;

-- Resolve as chaves. Gestor que não existe no cadastro não vira versão: fica o gestor anterior.
CREATE TEMP TABLE foto_resolvida ON COMMIT DROP AS
SELECT f.matricula, c.cargo_id, d.departamento_id, u.unidade_id,
       CASE WHEN g.matricula IS NOT NULL THEN f.gestor ELSE a.gestor_matricula END AS gestor,
       f.gestor IS NOT NULL AND g.matricula IS NULL AS gestor_invalido,
       f.salario, f.inicio_vigencia, f.desligamento,
       a.historico_id, a.valido_de,
       a.historico_id IS NOT NULL
         AND (a.cargo_id, a.departamento_id, a.unidade_id, a.gestor_matricula, a.salario)
             IS DISTINCT FROM (c.cargo_id, d.departamento_id, u.unidade_id,
                               CASE WHEN g.matricula IS NOT NULL THEN f.gestor ELSE a.gestor_matricula END, f.salario) AS mudou
FROM staging.foto f
JOIN rh.cargo c ON c.nome = f.cargo
JOIN rh.departamento d ON d.codigo = f.departamento
JOIN rh.unidade u ON u.nome = f.unidade
LEFT JOIN rh.vinculo g ON g.matricula = f.gestor
LEFT JOIN rh.historico_posicao a ON a.matricula = f.matricula AND a.valido_ate IS NULL;

INSERT INTO etl.quarentena (origem, competencia, matricula, motivo, registro)
SELECT 'foto', %(competencia)s, matricula::text, 'gestor_inexistente', jsonb_build_object('gestor_informado', f.gestor)
FROM foto_resolvida r JOIN staging.foto f USING (matricula)
WHERE r.gestor_invalido;

-- Mudança com vigência igual ou anterior à versão atual não cabe na linha do tempo.
INSERT INTO etl.quarentena (origem, competencia, matricula, motivo, registro)
SELECT 'foto', %(competencia)s, matricula::text, 'vigencia_conflitante',
       jsonb_build_object('inicio_vigencia', inicio_vigencia, 'versao_atual_desde', valido_de)
FROM foto_resolvida
WHERE mudou AND inicio_vigencia <= valido_de;

-- Mudança que só valeria depois da saída nunca chegou a existir.
INSERT INTO etl.quarentena (origem, competencia, matricula, motivo, registro)
SELECT 'foto', %(competencia)s, matricula::text, 'vigencia_apos_desligamento',
       jsonb_build_object('inicio_vigencia', inicio_vigencia, 'desligamento', desligamento)
FROM foto_resolvida
WHERE mudou AND inicio_vigencia > valido_de AND inicio_vigencia >= desligamento;

-- Fecha a versão atual de quem mudou.
UPDATE rh.historico_posicao h SET valido_ate = r.inicio_vigencia
FROM foto_resolvida r
WHERE h.historico_id = r.historico_id AND r.mudou AND r.inicio_vigencia > r.valido_de
  AND (r.desligamento IS NULL OR r.inicio_vigencia < r.desligamento);

-- Abre a nova versão: para quem mudou e para quem entrou agora.
INSERT INTO rh.historico_posicao (matricula, cargo_id, departamento_id, unidade_id, gestor_matricula, salario, valido_de, registrado_em)
SELECT matricula, cargo_id, departamento_id, unidade_id, gestor, salario, inicio_vigencia, %(competencia)s
FROM foto_resolvida r
WHERE (r.historico_id IS NULL AND NOT EXISTS (SELECT 1 FROM rh.historico_posicao h WHERE h.matricula = r.matricula))
   OR (r.mudou AND r.inicio_vigencia > r.valido_de AND (r.desligamento IS NULL OR r.inicio_vigencia < r.desligamento));

-- Quem sumiu do arquivo sem data de desligamento: a saída é inferida e fica marcada.
UPDATE rh.vinculo v
SET desligamento = %(competencia)s, motivo = 'Não informado', desligamento_inferido = true
WHERE v.desligamento IS NULL
  AND NOT EXISTS (SELECT 1 FROM staging.presenca p WHERE p.matricula = v.matricula);

-- Vínculo encerrado não tem versão atual.
UPDATE rh.historico_posicao h SET valido_ate = v.desligamento
FROM rh.vinculo v
WHERE h.matricula = v.matricula AND h.valido_ate IS NULL AND v.desligamento IS NOT NULL;
