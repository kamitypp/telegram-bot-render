from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool, create_engine

from alembic import context

import os
import sys
from dotenv import load_dotenv

# Зареди променливите от .env файла
load_dotenv()
sys.path.append(os.path.abspath('.')) 

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from models import db
target_metadata = db.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create a connection
    to the database only once, then we can re-use
    that connection in the migrations themselves.

    """
    # Read the DATABASE_URL environment variable first (for Render)
    # If not found, use the URL from alembic.ini (for local generation)
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        connectable = create_engine(db_url)
    else:
        # Fallback to sqlalchemy.url in alembic.ini if DATABASE_URL env var is not set
        # This is primarily for local migration generation if DATABASE_URL isn't exported
        connectable = engine_from_config(
            config.get_section_arg(config.config_ini_section),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()
            

