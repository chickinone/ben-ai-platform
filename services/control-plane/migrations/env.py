import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def database_url() -> str:
    url = os.environ.get("BEN_MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Thiếu BEN_MIGRATION_DATABASE_URL, ví dụ "
            "postgresql+psycopg://ben:<mật khẩu>@localhost:5432/ben "
            "(dùng role owner, không dùng ben_app)"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
