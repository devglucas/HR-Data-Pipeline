-- Separação por responsabilidade: quem pode ler o quê é decidido por esquema.
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- permite EXCLUDE combinando igualdade e intervalo
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- HMAC da pseudonimização

CREATE SCHEMA staging;     -- recebe a foto já limpa, descartável
CREATE SCHEMA rh;          -- modelo normalizado, com dados pessoais
CREATE SCHEMA analytics;   -- indicadores
CREATE SCHEMA anon;        -- dados anonimizados, única área do analista
