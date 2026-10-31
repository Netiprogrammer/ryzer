import sys
import os

# Adiciona o diretório atual ao path para achar o pacote backend
sys.path.append(os.getcwd())

from backend.database import SessionLocal, engine
from backend.models import Usuario, Projeto, StatusProjeto, Base
from backend.security import gerar_senha_hash

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
    Base.metadata.create_all(bind=engine)
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
