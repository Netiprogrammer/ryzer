import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pathlib import Path
from typing import List, Literal, Optional
from fastapi import Query

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

# --- ERROS DE VALIDAÇÃO ---
# O erro 422 padrão do FastAPI devolve, junto de cada problema, o valor que o
# cliente enviou ("input"). Isso tem dois problemas: (1) com NaN/Infinity o
# próprio JSON de resposta não consegue ser gerado e a requisição vira 500;
# (2) ecoa de volta o que foi digitado, inclusive senhas. Aqui devolvemos só
# uma mensagem legível em português, sem repetir a entrada do usuário.
_NOMES_CAMPOS = {
    "titulo": "Título", "valor": "Valor", "categoria": "Categoria",
    "conteudo_digital": "Conteúdo a entregar", "preco_min": "Preço mínimo", "preco_max": "Preço máximo", "pagina": "Página", "por_pagina": "Itens por página", "ordem": "Ordenação", "q": "Busca", "nome": "Nome",
    "email": "E-mail", "senha": "Senha", "codigo": "Código",
}


def _mensagem_amigavel(erro: dict) -> str:
    campo = _NOMES_CAMPOS.get(str(erro["loc"][-1]), str(erro["loc"][-1]))
    tipo, ctx = erro["type"], erro.get("ctx", {})
    if tipo == "missing":
        return f"{campo} é obrigatório."
    if tipo == "string_too_short":
        return f"{campo}: mínimo de {ctx.get('min_length')} caracteres."
    if tipo == "string_too_long":
        return f"{campo}: máximo de {ctx.get('max_length')} caracteres."
    if tipo == "greater_than":
        return f"{campo} deve ser maior que {ctx.get('gt'):g}."
    if tipo == "less_than_equal":
        return f"{campo} deve ser no máximo {ctx.get('le'):g}."
    if tipo in ("finite_number", "float_parsing", "float_type"):
        return f"{campo} deve ser um número válido."
    if tipo == "literal_error":
        return f"{campo} tem um valor que não é aceito."
    if tipo == "value_error":
        # Mensagens que nós mesmos escrevemos nos validators (já em português).
        return str(erro["msg"]).removeprefix("Value error, ")
    return f"{campo} é inválido."


@app.exception_handler(RequestValidationError)
async def tratar_erro_de_validacao(request: Request, exc: RequestValidationError):
    mensagens = [_mensagem_amigavel(e) for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": " ".join(mensagens)})

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

@app.get("/usuarios/{usuario_id}/pedidos", response_model=List[schemas.PedidoComprador], tags=["Usuários"])
def listar_meus_pedidos(
    usuario_id: int,
    current_user: models.Usuario = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.id != usuario_id:
        raise HTTPException(status_code=403, detail="Você só pode ver os seus próprios pedidos.")

    pedidos = [
        schemas.PedidoComprador.model_validate(p)
        for p in crud.get_projetos_por_cliente(db, usuario_id)
    ]
    # O conteúdo digital só é entregue depois que o comprador libera o
    # pagamento. Antes disso (aguardando Pix / pagamento retido) ele não sai
    # nem pra quem comprou — senão o escrow não faria sentido.
    for pedido in pedidos:
        if pedido.status != schemas.StatusProjetoSchema.FINALIZADO:
            pedido.conteudo_digital = None
    return pedidos

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

@app.get("/projetos/busca", response_model=schemas.ResultadoBusca, tags=["Projetos"])
def buscar_anuncios(
    q: Optional[str] = Query(None, max_length=80),
    categoria: Optional[schemas.Categoria] = None,
    preco_min: Optional[float] = Query(None, ge=0, le=schemas.VALOR_MAX, allow_inf_nan=False),
    preco_max: Optional[float] = Query(None, ge=0, le=schemas.VALOR_MAX, allow_inf_nan=False),
    ordem: Literal["recentes", "menor_preco", "maior_preco", "titulo"] = "recentes",
    pagina: int = Query(1, ge=1, le=10_000),
    por_pagina: int = Query(12),
    db: Session = Depends(get_db),
):
    """Vitrine pública com busca, filtros, ordenação e paginação."""
    if por_pagina not in (12, 24, 48):
        raise HTTPException(status_code=422, detail="Itens por página: use 12, 24 ou 48.")
    if preco_min is not None and preco_max is not None and preco_min > preco_max:
        raise HTTPException(status_code=422, detail="O preço mínimo não pode ser maior que o máximo.")
    return crud.buscar_projetos(
        db, q=q, categoria=categoria, preco_min=preco_min, preco_max=preco_max,
        ordem=ordem, pagina=pagina, por_pagina=por_pagina,
    )

@app.get("/projetos/por-ids", response_model=List[schemas.ProjetoVitrine], tags=["Projetos"])
def anuncios_por_ids(ids: str = Query("", max_length=400), db: Session = Depends(get_db)):
    """Carrinho: devolve os anúncios ainda abertos entre os ids informados (ex.: ?ids=1,2,3)."""
    try:
        lista = [int(i) for i in ids.split(",") if i.strip()][:50]
    except ValueError:
        raise HTTPException(status_code=422, detail="Ids inválidos.")
    return crud.get_vitrine_por_ids(db, lista)

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
    # Ninguém compra o próprio anúncio (senão dava pra "vender" pra si mesmo
    # e inflar o saldo/itens vendidos sem comprador de verdade).
    anuncio = crud.get_projeto_by_id(db, projeto_id)
    if anuncio and anuncio.vendedor_id == current_user.id:
        raise HTTPException(status_code=400, detail="Você não pode comprar o seu próprio anúncio.")

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
