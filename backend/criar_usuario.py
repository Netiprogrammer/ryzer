import sys
import os

# Adiciona o diretório atual ao path para achar o pacote backend
sys.path.append(os.getcwd())

from sqlalchemy import text

from backend.database import SessionLocal, engine
from backend.models import Usuario, Projeto, StatusProjeto, Base
from backend.security import gerar_senha_hash

# Chave arbitrária (só precisa ser constante) para o advisory lock do
# Postgres usado abaixo, evitando corrida entre múltiplos processos.
_ADVISORY_LOCK_KEY = 72_700_001

PRODUTOS_DEMO = [
    ("Placa de Vídeo RTX 4070 Super 12GB", 4299.90, "hardware",
     "Chave de ativação enviada via e-mail após confirmação."),
    ("Processador Ryzen 7 7800X3D", 2199.00, "hardware",
     "Código de rastreio Correios: BR123456789DEMO."),
    ("Mouse Gamer Logitech G502 Lightspeed", 349.90, "perifericos",
     "Link de frete grátis + nota fiscal enviados por e-mail."),
    ("Teclado Mecânico Logitech Pro X", 599.90, "perifericos",
     "Código de rastreio Correios: BR987654321DEMO."),
    ("PC Gamer Completo Ryzen 5 + RTX 3060", 5890.00, "computadores",
     "Instruções de retirada/entrega combinadas via chat."),
    ("Curso Completo de Python para Dados", 197.00, "software",
     "Link de acesso à plataforma: https://exemplo.com/curso-python (demo)."),
]


def criar_usuario_inicial():
    print("🔄 Verificando integridade do banco de dados...")

    # Em produção o Render sobe a aplicação com vários processos (workers)
    # ao mesmo tempo, e cada um chama essa função no próprio startup. Sem
    # proteção, todos tentam criar as tabelas/tipos e inserir o mesmo
    # usuário admin/vendedor ao mesmo tempo — o Postgres rejeita a criação
    # duplicada (do tipo enum, ou do e-mail que é unique), abortando a
    # transação de quem perde a corrida. Um advisory lock do Postgres
    # serializa a função inteira (schema + seed): só um processo passa
    # por vez, os demais esperam a vez e, ao continuar, tudo já existe
    # (create_all/seed são idempotentes, não fazem nada de novo).
    # SQLite (uso local/dev, processo único) não tem essa corrida, então
    # pula o lock, que nem existe nesse dialeto.
    usa_lock_postgres = engine.dialect.name == "postgresql"
    lock_conn = None
    if usa_lock_postgres:
        lock_conn = engine.connect()
        lock_conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})

    try:
        Base.metadata.create_all(bind=engine)
        _seed_dados_iniciais()
    finally:
        if lock_conn is not None:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
            lock_conn.close()


def _seed_dados_iniciais():
    db = SessionLocal()

    try:
        # --- Usuário admin (acesso administrativo/testes) ---
        email_admin = "admin@teste.com"
        senha_admin = os.environ.get("RYZER_ADMIN_SENHA", "ryzer123")
        admin = db.query(Usuario).filter(Usuario.email == email_admin).first()
        if not admin:
            print(f"-> Criando usuário admin: {email_admin}...")
            admin = Usuario(
                nome="Administrador",
                email=email_admin,
                senha_hash=gerar_senha_hash(senha_admin),
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
            print(f"✅ Admin criado (senha: {senha_admin}).")
        else:
            print("⚠️  O usuário admin já existe.")

        # --- Vendedor de demonstração, com produtos na vitrine ---
        email_demo = "vendedor@ryzer.demo"
        senha_demo = os.environ.get("RYZER_DEMO_SENHA", "demo12345")
        vendedor = db.query(Usuario).filter(Usuario.email == email_demo).first()
        if not vendedor:
            print(f"-> Criando vendedor de demonstração: {email_demo}...")
            vendedor = Usuario(
                nome="Loja Demo Ryzer",
                email=email_demo,
                senha_hash=gerar_senha_hash(senha_demo),
            )
            db.add(vendedor)
            db.commit()
            db.refresh(vendedor)
            print(f"✅ Vendedor demo criado (senha: {senha_demo}).")
        else:
            print("⚠️  O vendedor de demonstração já existe.")

        produtos_existentes = db.query(Projeto).filter(
            Projeto.vendedor_id == vendedor.id
        ).count()

        if produtos_existentes == 0:
            print(f"-> Publicando {len(PRODUTOS_DEMO)} produtos de demonstração...")
            for titulo, valor, categoria, conteudo in PRODUTOS_DEMO:
                db.add(Projeto(
                    titulo=titulo,
                    valor=valor,
                    categoria=categoria,
                    vendedor_id=vendedor.id,
                    conteudo_digital=conteudo,
                    status=StatusProjeto.ABERTO,
                ))
            db.commit()
            print("✅ Produtos de demonstração publicados!")
        else:
            print("⚠️  Já existem produtos do vendedor demo, não vou duplicar.")

    except Exception as e:
        print(f"❌ Erro: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    criar_usuario_inicial()
