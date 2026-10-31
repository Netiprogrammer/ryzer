from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

if "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Fixamos o driver explicitamente como psycopg2 (instalado via
    # psycopg2-binary no requirements.txt). Sem isso, versões mais novas
    # do SQLAlchemy tentam usar o driver "psycopg" (v3) por padrão para
    # URLs "postgresql://" simples, e como só o psycopg2 está instalado,
    # a aplicação nem sobe (ModuleNotFoundError: No module named 'psycopg').
    url_banco = SQLALCHEMY_DATABASE_URL
    if url_banco.startswith("postgresql://"):
        url_banco = url_banco.replace("postgresql://", "postgresql+psycopg2://", 1)
    engine = create_engine(url_banco)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()