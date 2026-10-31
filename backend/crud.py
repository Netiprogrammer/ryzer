import base64
import random
import secrets
import uuid
from io import BytesIO

import qrcode
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import models, schemas, security

# USUÁRIOS
def get_usuario_by_email(db: Session, email: str):
    return db.query(models.Usuario).filter(models.Usuario.email == email).first()

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
    projeto.codigo_verificacao = str(random.randint(100000, 999999))
    db.commit()
    db.refresh(projeto)
    return projeto

def validar_entrega_e_liberar(db: Session, projeto_id: int, codigo: str):
    stmt = select(models.Projeto).where(models.Projeto.id == projeto_id).with_for_update()
    projeto = db.execute(stmt).scalar_one_or_none()

    if (
        projeto
        and projeto.codigo_verificacao == codigo
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
    projetos = db.query(models.Projeto).filter(
        models.Projeto.vendedor_id == vendedor_id,
        models.Projeto.status == models.StatusProjeto.FINALIZADO
    ).all()
    return sum(p.valor for p in projetos)
