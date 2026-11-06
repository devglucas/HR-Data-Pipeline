-- LGPD: o analista enxerga indicadores agregados e a base anonimizada. Nada além disso.
CREATE TABLE anon.colaborador (
    pseudonimo       text PRIMARY KEY,
    departamento     text NOT NULL,
    grupo_nivel      text NOT NULL,
    faixa_etaria     text NOT NULL,
    genero           char(1) NOT NULL,
    faixa_tempo_casa text NOT NULL,
    faixa_salarial   text NOT NULL,
    situacao         text NOT NULL
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rh_analista') THEN
        CREATE ROLE rh_analista NOLOGIN;
    END IF;
END $$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA anon, analytics TO rh_analista;
GRANT SELECT ON anon.colaborador TO rh_analista;
GRANT SELECT ON analytics.headcount_mensal, analytics.turnover_mensal, analytics.turnover_departamento,
                analytics.retencao_admissao, analytics.gap_salarial, analytics.absenteismo TO rh_analista;
