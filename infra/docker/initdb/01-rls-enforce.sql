-- CRÍTICO PARA O ISOLAMENTO DE TENANT (Regra de Ouro nº 1).
--
-- A imagem do Postgres cria POSTGRES_USER (e1puser) como SUPERUSUÁRIO, e superusuários
-- IGNORAM Row-Level Security (mesmo com FORCE) — o que anularia todo o isolamento.
--
-- Solução (também válida em produção/RDS): a aplicação conecta como um papel DEDICADO,
-- NÃO-superusuário. Esse papel roda as migrations e portanto é DONO das tabelas; com
-- FORCE ROW LEVEL SECURITY, as políticas de tenant se aplicam a ele.
--
-- Roda uma única vez, na primeira inicialização do volume, como o superusuário de bootstrap.
CREATE ROLE e1p_app WITH LOGIN PASSWORD 'e1ppass' NOSUPERUSER;
GRANT ALL PRIVILEGES ON DATABASE e1pdb TO e1p_app;
GRANT ALL ON SCHEMA public TO e1p_app;
