import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)

# "postgresql+psycopg" tells SQLAlchemy to use the psycopg 3 driver
engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1))
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
