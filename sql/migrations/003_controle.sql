-- Controle de carga, quarentena e auditoria. Nada aqui guarda CPF ou nome.
CREATE SCHEMA etl;

CREATE TABLE etl.carga (
    competencia       date PRIMARY KEY,
    arquivo           text NOT NULL,
    hash              text NOT NULL,
    linhas_lidas      integer NOT NULL,
    linhas_aplicadas  integer NOT NULL,
    linhas_quarentena integer NOT NULL,
    versoes_criadas   integer NOT NULL,
    processado_em     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE etl.quarentena (
    quarentena_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    origem        text NOT NULL,
    competencia   date,
    matricula     text,
    motivo        text NOT NULL,
    registro      jsonb NOT NULL,
    criado_em     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE etl.auditoria (
    auditoria_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tabela       text NOT NULL,
    operacao     text NOT NULL,
    antes        jsonb,
    depois       jsonb,
    momento      timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION etl.auditar() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO etl.auditoria (tabela, operacao, antes, depois)
    VALUES (TG_TABLE_NAME, TG_OP,
            CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) - 'cpf' - 'nome' - 'nascimento' END,
            CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) - 'cpf' - 'nome' - 'nascimento' END);
    RETURN NULL;
END $$;

-- Só alterações ficam registradas: a carga inicial não precisa de trilha.
CREATE TRIGGER vinculo_auditoria AFTER UPDATE OR DELETE ON rh.vinculo FOR EACH ROW EXECUTE FUNCTION etl.auditar();

CREATE UNLOGGED TABLE staging.foto (
    matricula         integer PRIMARY KEY,
    cpf               char(11) NOT NULL,
    nome              text NOT NULL,
    nascimento        date NOT NULL,
    genero            char(1) NOT NULL,
    admissao          date NOT NULL,
    desligamento      date,
    motivo            text,
    cargo             text NOT NULL,
    departamento      text NOT NULL,
    departamento_nome text NOT NULL,
    unidade           text NOT NULL,
    gestor            integer,
    salario           numeric(12, 2) NOT NULL,
    contrato          text NOT NULL,
    inicio_vigencia   date NOT NULL
);

-- Todas as matrículas do arquivo, inclusive as que foram para a quarentena:
-- uma linha rejeitada não pode ser confundida com um desligamento.
CREATE UNLOGGED TABLE staging.presenca (matricula integer PRIMARY KEY);
