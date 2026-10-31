import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base, get_db


@pytest.fixture()
def client():
    """
    Cada teste roda contra um banco SQLite em memória isolado (zerado a
    cada teste), pra não depender de ordem de execução nem sujar o banco
    de verdade do projeto.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def cadastrar_e_logar(client, nome="Usuário Teste", email="teste@exemplo.com", senha="senha123"):
    client.post("/usuarios/", json={"nome": nome, "email": email, "senha": senha})
    res = client.post("/login/", json={"email": email, "senha": senha})
    assert res.status_code == 200, res.text
    data = res.json()
    return data["usuario_id"], data["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}
