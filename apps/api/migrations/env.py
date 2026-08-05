from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db.registry import Base  # importa todos os modelos

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    # `disable_existing_loggers=False` é obrigatório: o PADRÃO do `fileConfig` é `True`, e aí
    # ele marca `disabled=True` em TODO logger que já existe e não está nomeado no alembic.ini
    # — `e1p.whatsapp`, `e1p.notifications`, `e1p.worker`... Depois disso, `logger.info` e
    # `logger.exception` viram no-op silencioso para o resto do processo.
    #
    # Produção escapa por acidente de topologia (o compose roda `sh -c "alembic upgrade head &&
    # uvicorn ..."`, processos separados), mas dentro do pytest um único teste que aplica
    # migrations silencia o logging da aplicação para todos os testes seguintes — foi assim que
    # `test_reescrita_e_logada` passava sozinho e falhava na suíte inteira. Qualquer código
    # futuro que migre no MESMO processo em que a app loga herdaria o silêncio em produção, que
    # é a mesma classe do bug já registrado no CLAUDE.md (logs que "somem").
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
