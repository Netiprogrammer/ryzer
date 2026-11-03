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
    # pool_pre_ping: antes de usar uma conexão que estava parada no pool, o
    # SQLAlchemy testa se ela ainda está viva e, se não estiver, abre outra.
    # Isso é essencial com o Neon (Postgres serverless), que derruba conexões
    # ociosas: sem isso, a primeira requisição depois de um tempo parado
    # tomava "SSL connection has been closed unexpectedly" e virava um 500
    # (já aconteceu em produção na listagem da vitrine).
    # pool_recycle: renova conexões com mais de 5 min, antes do servidor
    # decidir fechá-las por conta própria.
    engine = create_engine(url_banco, pool_pre_ping=True, pool_recycle=300)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()