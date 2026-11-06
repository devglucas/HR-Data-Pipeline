-- O banco é a última barreira: mesmo que o Python erre, dado inválido não entra.

CREATE FUNCTION rh.cpf_valido(cpf text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    WITH digitos AS (
        SELECT i, substr(cpf, i, 1)::int AS n FROM generate_series(1, 11) AS i
    ), verificadores AS (
        SELECT (sum(n * (11 - i)) FILTER (WHERE i <= 9) * 10 % 11) % 10 AS d1,
               (sum(n * (12 - i)) FILTER (WHERE i <= 10) * 10 % 11) % 10 AS d2
        FROM digitos
    )
    SELECT cpf ~ '^[0-9]{11}$'
       AND cpf !~ '^(.)\1{10}$'
       AND d1 = substr(cpf, 10, 1)::int
       AND d2 = substr(cpf, 11, 1)::int
    FROM verificadores
$$;

CREATE TABLE rh.departamento (
    departamento_id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo          text NOT NULL UNIQUE,      -- estável: renomear a área não cria nova versão
    nome            text NOT NULL
);

CREATE TABLE rh.unidade (
    unidade_id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome       text NOT NULL UNIQUE
);

CREATE TABLE rh.cargo (
    cargo_id    smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome        text NOT NULL UNIQUE,
    nivel       text NOT NULL,
    nivel_ordem smallint NOT NULL CHECK (nivel_ordem >= 1),
    faixa_min   numeric(12, 2) NOT NULL,
    faixa_max   numeric(12, 2) NOT NULL,
    CHECK (faixa_min > 0 AND faixa_min < faixa_max)
);

-- Pessoa e vínculo são separados: quem volta à empresa é a mesma pessoa, com outra matrícula.
CREATE TABLE rh.pessoa (
    pessoa_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cpf        char(11) NOT NULL UNIQUE CHECK (rh.cpf_valido(cpf)),
    nome       text NOT NULL CHECK (length(trim(nome)) > 0),
    nascimento date NOT NULL CHECK (nascimento > DATE '1920-01-01'),
    genero     char(1) NOT NULL CHECK (genero IN ('F', 'M'))
);

CREATE TABLE rh.vinculo (
    matricula             integer PRIMARY KEY,
    pessoa_id             integer NOT NULL REFERENCES rh.pessoa,
    admissao              date NOT NULL,
    desligamento          date,
    motivo                text,
    desligamento_inferido boolean NOT NULL DEFAULT false,
    contrato              text NOT NULL CHECK (contrato IN ('CLT', 'Temporário')),
    CHECK (desligamento IS NULL OR desligamento >= admissao),
    CHECK ((desligamento IS NULL) = (motivo IS NULL)),
    -- a mesma pessoa não pode ter dois vínculos ao mesmo tempo
    CONSTRAINT vinculo_sem_sobreposicao EXCLUDE USING gist (pessoa_id WITH =, daterange(admissao, desligamento) WITH &&)
);

-- SCD tipo 2: cada mudança de cargo, área, unidade, gestor ou salário é uma nova versão.
-- O intervalo é [valido_de, valido_ate): valido_ate vazio indica a versão atual.
CREATE TABLE rh.historico_posicao (
    historico_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    matricula        integer NOT NULL REFERENCES rh.vinculo,
    cargo_id         smallint NOT NULL REFERENCES rh.cargo,
    departamento_id  smallint NOT NULL REFERENCES rh.departamento,
    unidade_id       smallint NOT NULL REFERENCES rh.unidade,
    gestor_matricula integer REFERENCES rh.vinculo,
    salario          numeric(12, 2) NOT NULL CHECK (salario >= 1000),
    valido_de        date NOT NULL,
    valido_ate       date,
    registrado_em    date NOT NULL,       -- competência em que a mudança chegou ao sistema
    CHECK (valido_ate IS NULL OR valido_ate > valido_de),
    CONSTRAINT historico_sem_sobreposicao EXCLUDE USING gist (matricula WITH =, daterange(valido_de, valido_ate) WITH &&)
);
CREATE UNIQUE INDEX historico_uma_versao_atual ON rh.historico_posicao (matricula) WHERE valido_ate IS NULL;
CREATE INDEX historico_gestor ON rh.historico_posicao (gestor_matricula);

CREATE TABLE rh.folha (
    matricula    integer NOT NULL REFERENCES rh.vinculo,
    competencia  date NOT NULL CHECK (extract(day FROM competencia) = 1),
    salario_base numeric(12, 2) NOT NULL CHECK (salario_base >= 0),
    horas_extras numeric(12, 2) NOT NULL DEFAULT 0 CHECK (horas_extras >= 0),
    retroativo   numeric(12, 2) NOT NULL DEFAULT 0 CHECK (retroativo >= 0),
    descontos    numeric(12, 2) NOT NULL DEFAULT 0 CHECK (descontos >= 0),
    liquido      numeric(12, 2) NOT NULL,
    PRIMARY KEY (matricula, competencia),
    CHECK (abs(salario_base + horas_extras + retroativo - descontos - liquido) <= 0.02)
);

CREATE TABLE rh.afastamento (
    afastamento_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    matricula      integer NOT NULL REFERENCES rh.vinculo,
    tipo           text NOT NULL CHECK (tipo IN ('ferias', 'atestado', 'licenca_maternidade')),
    periodo        daterange NOT NULL CHECK (NOT isempty(periodo) AND NOT upper_inf(periodo)),
    CONSTRAINT afastamento_sem_sobreposicao EXCLUDE USING gist (matricula WITH =, tipo WITH =, periodo WITH &&)
);
