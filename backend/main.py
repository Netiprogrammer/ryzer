import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pathlib import Path
from typing import List

from backend import crud, database, models, schemas, security
from backend.database import engine, Base, get_db

# --- CONFIGURAÇÃO DE CAMINHOS ABSOLUTOS ---
# Isso garante que o sistema ache as pastas static e templates na raiz
BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Garante que o banco tenha as tabelas certas (e dados de demonstração)
    toda vez que a aplicação sobe, sem depender de nenhum passo manual
    (ex.: rodar um script via shell no servidor). Isso é essencial em
    produção: a primeira vez que o serviço sobe contra um banco novo
    (como um Postgres recém-criado), as tabelas ainda não existem.

    Tudo aqui é seguro de rodar repetidas vezes: 'create_all' não recria
    tabelas que já existem, e 'criar_usuario_inicial' já confere se o
    admin/vendedor demo existem antes de inserir.
    """
    from backend.criar_usuario import criar_usuario_inicial
    try:
        criar_usuario_inicial()
    except Exception as e:
        # Não deixamos uma falha aqui derrubar a aplicação inteira — só
        # registramos no log pra investigar. Sem isso, um erro transitório
        # de conexão no boot tiraria o site do ar por completo.
        print(f"⚠️  Falha ao preparar o banco de dados no startup: {e}")
    yield


app = FastAPI(title="Ryzer Marketplace", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Monta os arquivos estáticos e templates usando o caminho completo
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# --- ROTAS DE PÁGINAS ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# --- ROTAS DE API ---

@app.post("/login/", tags=["Usuários"])
def login(dados: schemas.UsuarioLogin, db: Session = Depends(get_db)):
    usuario = crud.get_usuario_by_email(db, email=dados.email)
    if not usuario or not security.verificar_senha(dados.senha, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")

    token = security.criar_token_acesso(dados={"sub": str(usuario.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario_id": usuario.id,
        "nome": usuario.nome
    }

@app.post("/usuarios/", response_model=schemas.Usuario, tags=["Usuários"])
def cadastrar_usuario(usuario: schemas.UsuarioCreate, db: Session = Depends(get_db)):
    db_usuario = crud.get_usuario_by_email(db, email=usuario.email)
    if db_usuario:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado.")
    return crud.create_usuario(db=db, usuario=usuario)

@app.get("/usuarios/{usuario_id}/pedidos", response_model=List[schemas.Projeto], tags=["Usuários"])
def listar_meus_pedidos(
    usuario_id: int,
    current_user: models.Usuario = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.id != usuario_id:
        raise HTTPException(status_code=403, detail="Você só pode ver os seus próprios pedidos.")
    return crud.get_projetos_por_cliente(db, usuario_id)

@app.get("/vendedor/{vendedor_id}/total-vendas", tags=["Usuários"])
def total_vendas_vendedor(
    vendedor_id: int,
    current_user: models.Usuario = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.id != vendedor_id:
        raise HTTPException(status_code=403, detail="Você só pode ver as suas próprias vendas.")
    return {
        "total_vendas_concluidas": crud.somar_vendas_vendedor(db, vendedor_id),
        "itens_vendidos": crud.contar_vendas_vendedor(db, vendedor_id),
    }

@app.post("/projetos/", response_model=schemas.Projeto, tags=["Projetos"])
def criar_anuncio(
    projeto: schemas.ProjetoCreate,
    current_user: models.Usuario = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    # vendedor_id é sempre o usuário autenticado, nunca algo vindo do corpo
    # da requisição — isso impedia (antes dessa correção) qualquer pessoa
    # de publicar um anúncio em nome de outro vendedor.
    return crud.create_projeto(db=db, projeto=projeto, vendedor_id=current_user.id)

@app.get("/projetos/", response_model=List[schemas.Projeto], tags=["Projetos"])
def listar_anuncios(db: Session = Depends(get_db)):
    return crud.get_projetos(db)

@app.post("/projetos/{projeto_id}/checkout/pix/", response_model=schemas.PixCobranca, tags=["Escrow / Pix"])
def iniciar_checkout_pix(
    projeto_id: int,
    current_user: models.Usuario = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Gera uma cobrança Pix SIMULADA para o projeto (QR code + copia-e-cola).
    Nenhum pagamento real acontece aqui — é só para demonstrar o fluxo.
    """
    resultado = crud.criar_cobranca_pix(db, projeto_id=projeto_id, cliente_id=current_user.id)
    if not resultado:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou não está mais disponível.")

    projeto = resultado["projeto"]
    return schemas.PixCobranca(
        projeto_id=projeto.id,
        valor=projeto.valor,
        pix_txid=projeto.pix_txid,
        pix_copia_cola=projeto.pix_copia_cola,
        qr_code_base64=resultado["qr_code_base64"],
        status=projeto.status,
    )

@app.post("/projetos/{projeto_id}/pix/confirmar", tags=["Escrow / Pix"])
def confirmar_pagamento_pix(
    projeto_id: int,
    current_user: models.Usuario = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Botão "Já paguei" do frontend: simula o webhook que um gateway de
    pagamento de verdade mandaria quando o Pix fosse compensado.
    """
    projeto = crud.confirmar_pagamento_pix(db, projeto_id=projeto_id, cliente_id=current_user.id)
    if not projeto:
        raise HTTPException(
            status_code=404,
            detail="Cobrança Pix não encontrada, já paga, ou não pertence a você.",
        )
    return {
        "status": "pagamento_retido",
        "codigo_verificacao": projeto.codigo_verificacao,
        "mensagem": f"PAGAMENTO RETIDO: Use o código {projeto.codigo_verificacao} para liberar após receber o produto.",
    }

@app.post("/projetos/{projeto_id}/liberar/", response_model=schemas.ProjetoLiberado, tags=["Escrow / Pix"])
def liberar_pagamento(
    projeto_id: int,
    dados: schemas.ValidarCodigo,
    current_user: models.Usuario = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    """
    O comprador confirma que recebeu o produto/serviço digitando o código
    de verificação. Só o comprador do projeto pode liberar o pagamento
    retido para o vendedor.
    """
    projeto = crud.get_projeto_by_id(db, projeto_id)
    if not projeto:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    if projeto.cliente_id != current_user.id:
        raise HTTPException(status_code=403, detail="Só o comprador pode liberar este pagamento.")

    projeto_liberado = crud.validar_entrega_e_liberar(db, projeto_id=projeto_id, codigo=dados.codigo)
    if not projeto_liberado:
        raise HTTPException(status_code=400, detail="Código de verificação inválido.")
    return projeto_liberado

@app.get("/health")
def healthcheck():
    return {"status": "Online"}
