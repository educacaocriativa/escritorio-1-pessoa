#!/bin/sh
# Equivalente de produção do initdb/01-rls-enforce.sql, mas sem senha hardcoded:
# lê APP_DB_PASSWORD do ambiente do container postgres (definido no docker-compose.prod.yml).
# Roda uma única vez, na primeira inicialização do volume (data dir vazio).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE e1p_app WITH LOGIN PASSWORD '$APP_DB_PASSWORD' NOSUPERUSER;
    GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_DB TO e1p_app;
    GRANT ALL ON SCHEMA public TO e1p_app;
EOSQL
