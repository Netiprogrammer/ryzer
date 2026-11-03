import base64
import secrets
import uuid
from io import BytesIO

import qrcode
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend import models, schemas, security

# USUÁRIOS
def get_usuario_by_email(db: Session, email: str):
    # Comparação sem diferenciar maiúsculas/minúsculas: contas antigas que
    # foram salvas com letras maiúsculas continuam achando o login, e novas
    # contas não conseguem duplicar o mesmo e-mail só mudando a caixa.
    return db.query(models.Usuario).filter(
        func.lower(models.Usuario.email) == email.strip().lower()
    ).first()

def get_usuario_by_id(db: Session, usuario_id: int):
    return db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()

def create_usuario(db: Session, usuario: schemas.UsuarioCreate):
    senha_protegida = security.gerar_senha_hash(usuario.senha)
    db_usuario = models.Usuario(
        nome=usuario.nome,
        email=usuario.email,
        senha_hash=senha_protegida
    )
    db.add(db_usuario)
    db.commit()
    db.refresh(db_usuario)
    return db_usuario

# PROJETOS / ANÚNCIOS
def create_projeto(db: Session, projeto: schemas.ProjetoCreate, vendedor_id: int):
    """
    vendedor_id vem sempre do usuário autenticado (nunca de um campo que o
    cliente poderia forjar no corpo da requisição) — é a rota em main.py
    quem garante isso antes de chamar essa função.
    """
    db_projeto = models.Projeto(
        titulo=projeto.titulo,
        valor=projeto.valor,
        categoria=projeto.categoria,
        vendedor_id=vendedor_id,
        conteudo_digital=projeto.conteudo_digital,
        cliente_id=None,
        status=models.StatusProjeto.ABERTO
    )
    db.add(db_projeto)
    db.commit()
    db.refresh(db_projeto)
    return db_projeto

def get_projetos(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Projeto).offset(skip).limit(limit).all()

ORDENS_BUSCA = ("recentes", "menor_preco", "maior_preco", "titulo")


def _escapar_like(termo: str) -> str:
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def buscar_projetos(
    db: Session,
    q: str | None = None,
    categoria: str | None = None,
    preco_min: float | None = None,
    preco_max: float | None = None,
    ordem: str = "recentes",
    pagina: int = 1,
    por_pagina: int = 12,
) -> dict:
    """
    Vitrine pública: só anúncios ABERTOS, com busca por texto, filtro de
    categoria e faixa de preço, ordenação e paginação — tudo feito no banco.
    """
    P = models.Projeto
    base = db.query(P).filter(P.status == models.StatusProjeto.ABERTO)
    if q and q.strip():
        base = base.filter(P.titulo.ilike(f"%{_escapar_like(q.strip())}%", escape="\\"))
    if preco_min is not None:
        base = base.filter(P.valor >= preco_min)
    if preco_max is not None:
        base = base.filter(P.valor <= preco_max)

    # Contagem por categoria ignora o filtro de categoria (como os filtros
    # de loja: você vê quantos itens existiriam se trocasse de categoria).
    contagem = dict(
        base.with_entities(P.categoria, func.count(P.id)).group_by(P.categoria).all()
    )

    consulta = base.filter(P.categoria == categoria) if categoria else base
    total = consulta.count()
    faixa = consulta.with_entities(func.min(P.valor), func.max(P.valor)).one()

    ordenacao = {
        "menor_preco": (P.valor.asc(), P.id.desc()),
        "maior_preco": (P.valor.desc(), P.id.desc()),
        "titulo": (func.lower(P.titulo).asc(), P.id.desc()),
    }.get(ordem, (P.id.desc(),))
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(1, pagina), paginas)
    itens = (
        consulta.options(joinedload(P.vendedor))
        .order_by(*ordenacao)
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
        .all()
    )
    return {
        "itens": [
            schemas.ProjetoVitrine(
                id=p.id, titulo=p.titulo, valor=p.valor, categoria=p.categoria,
                vendedor_id=p.vendedor_id, vendedor_nome=p.vendedor.nome,
                data_criacao=p.data_criacao,
            )
            for p in itens
        ],
        "total": total, "pagina": pagina, "paginas": paginas, "por_pagina": por_pagina,
        "categorias": contagem,
        "preco_min": faixa[0], "preco_max": faixa[1],
    }


def get_vitrine_por_ids(db: Session, ids: list[int]):
    """Anúncios abertos pelos ids (usado pelo carrinho)."""
    P = models.Projeto
    if not ids:
        return []
    projetos = (
        db.query(P).options(joinedload(P.vendedor))
        .filter(P.id.in_(ids), P.status == models.StatusProjeto.ABERTO).all()
    )
    return [
        schemas.ProjetoVitrine(
            id=p.id, titulo=p.titulo, valor=p.valor, categoria=p.categoria,
            vendedor_id=p.vendedor_id, vendedor_nome=p.vendedor.nome,
            data_criacao=p.data_criacao,
        )
        for p in projetos
    ]


def get_projeto_by_id(db: Session, projeto_id: int):
    return db.query(models.Projeto).filter(models.Projeto.id == projeto_id).first()

# PIX (SIMULADO)
def _gerar_copia_cola_pix(valor: float, txid: str) -> str:
    """
    Gera uma string no estilo "copia e cola" só para fins de demonstração
    visual. De propósito NÃO imita o formato EMV/BR Code de um Pix de
    verdade, pra não ter risco de alguém confundir com um código real:
    isso aqui não está ligado a nenhuma instituição financeira e nenhum
    pagamento de fato acontece.
    """
    return (
        f"PIX-SIMULADO|txid={txid}|valor={valor:.2f}|"
        f"chave=ryzer-demo@exemplo.com|{secrets.token_hex(6)}"
    )

def _gerar_qr_code_base64(payload: str) -> str:
    img = qrcode.make(payload)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")

def criar_cobranca_pix(db: Session, projeto_id: int, cliente_id: int):
    """
    Início do checkout: trava o projeto como ABERTO -> AGUARDANDO_PAGAMENTO
    e gera o Pix simulado (txid + copia-e-cola + QR code).
    """
    stmt = select(models.Projeto).where(models.Projeto.id == projeto_id).with_for_update()
    projeto = db.execute(stmt).scalar_one_or_none()

    if not projeto or projeto.status != models.StatusProjeto.ABERTO:
        return None

    txid = uuid.uuid4().hex
    copia_cola = _gerar_copia_cola_pix(projeto.valor, txid)

    projeto.status = models.StatusProjeto.AGUARDANDO_PAGAMENTO
    projeto.cliente_id = cliente_id
    projeto.pix_txid = txid
    projeto.pix_copia_cola = copia_cola
    db.commit()
    db.refresh(projeto)

    return {
        "projeto": projeto,
        "qr_code_base64": _gerar_qr_code_base64(copia_cola),
    }

def confirmar_pagamento_pix(db: Session, projeto_id: int, cliente_id: int):
    """
    Simula a confirmação do gateway de pagamento (o "Já paguei" do
    frontend). Só confirma se quem está pagando é o mesmo usuário que
    gerou a cobrança, e só se o projeto ainda estiver aguardando.
    """
    stmt = select(models.Projeto).where(models.Projeto.id == projeto_id).with_for_update()
    projeto = db.execute(stmt).scalar_one_or_none()

    if (
        not projeto
        or projeto.status != models.StatusProjeto.AGUARDANDO_PAGAMENTO
        or projeto.cliente_id != cliente_id
    ):
        return None

    projeto.status = models.StatusProjeto.PAGAMENTO_RETIDO
    projeto.valor_no_escrow = projeto.valor
    # secrets (e não random): o código é um segredo, então precisa vir de um
    # gerador criptograficamente seguro, não de um previsível.
    projeto.codigo_verificacao = f"{secrets.randbelow(900000) + 100000}"
    db.commit()
    db.refresh(projeto)
    return projeto

def validar_entrega_e_liberar(db: Session, projeto_id: int, codigo: str):
    stmt = select(models.Projeto).where(models.Projeto.id == projeto_id).with_for_update()
    projeto = db.execute(stmt).scalar_one_or_none()

    if (
        projeto
        and projeto.codigo_verificacao
        # compare_digest: comparação em tempo constante (não vaza, pelo
        # tempo de resposta, quantos caracteres do código estavam certos).
        # (em bytes: compare_digest recusa texto com caracteres não-ASCII)
        and secrets.compare_digest(
            projeto.codigo_verificacao.encode("utf-8"), codigo.strip().encode("utf-8")
        )
        and projeto.status == models.StatusProjeto.PAGAMENTO_RETIDO
    ):
        projeto.status = models.StatusProjeto.FINALIZADO
        db.commit()
        db.refresh(projeto)
        return projeto
    return None

# FILTROS / CONSULTAS
def get_projetos_por_cliente(db: Session, cliente_id: int):
    return db.query(models.Projeto).filter(models.Projeto.cliente_id == cliente_id).all()

def contar_vendas_vendedor(db: Session, vendedor_id: int):
    return db.query(models.Projeto).filter(
        models.Projeto.vendedor_id == vendedor_id,
        models.Projeto.status == models.StatusProjeto.FINALIZADO
    ).count()

def somar_vendas_vendedor(db: Session, vendedor_id: int) -> float:
    # SUM feito no banco (em vez de carregar todas as linhas pro Python).
    total = db.query(func.coalesce(func.sum(models.Projeto.valor), 0.0)).filter(
        models.Projeto.vendedor_id == vendedor_id,
        models.Projeto.status == models.StatusProjeto.FINALIZADO
    ).scalar()
    return float(total or 0.0)
