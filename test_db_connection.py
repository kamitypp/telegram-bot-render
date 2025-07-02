import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
import sys
import configparser # Добавено за четене на ini файл

# Get DB URL from alembic.ini
try:
    config = configparser.ConfigParser()
    # Read alembic.ini relative to this script or current working dir
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alembic.ini')
    if not os.path.exists(config_path):
        config_path = os.path.join(os.getcwd(), 'alembic.ini')

    config.read(config_path)
    db_url = config['alembic']['sqlalchemy.url']
except Exception as e:
    print(f"Error reading alembic.ini: {e}", file=sys.stderr)
    sys.exit(1)

print(f"Attempting to connect to: {db_url}")

try:
    engine = create_engine(db_url)
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        print(f"Connection successful! Result: {result.scalar()}")
        print("Database connection test passed.")
except OperationalError as e:
    print(f"Operational Error (Database connection error): {e}", file=sys.stderr)
    print("This usually means incorrect password, host, or port.", file=sys.stderr)
    sys.exit(1)
except SQLAlchemyError as e:
    print(f"SQLAlchemy Error (general database error): {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred: {e}", file=sys.stderr)
    sys.exit(1)