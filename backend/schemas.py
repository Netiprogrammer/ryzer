from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime
from enum import Enum
from typing import Optional, List

# =========================================================
# BLOCO 1: OPÇÕES PADRONIZADAS (ENUM)
# =========================================================

class StatusProjetoSchema(str, Enum):
    """
    Aqui eu travo as opções de status. Assim o sistema só aceita 
    esses 4 estados e a gente não corre o risco de ter erros de digitação.
    """
    ABERTO = "aberto"
    AGUARDANDO_PAGAMENTO = "aguardando_pagamento"
    PAGAMENTO_RETIDO = "pagamento_retido"
    FINALIZADO = "finalizado"
    CANCELADO = "cancelado"

# =========================================================
# BLOCO 2: CONTRATOS DE USUÁRIO
# =========================================================

class UsuarioBase(BaseModel):
    # O básico que todo usuário tem que ter
    nome: str
    email: str

class UsuarioCreate(UsuarioBase):
    # Na hora de criar, eu exijo a senha em texto puro (depois o CRUD faz o hash)
    senha: str

class UsuarioLogin(BaseModel):
    # O que o cara digita na tela de login
    email: str
    senha: str

class Usuario(UsuarioBase):
    # O que o sistema devolve: aqui eu já mando o ID do banco
    id: int

    # Isso aqui permite que o Pydantic leia os dados direto do SQLAlchemy (models)
    model_config = ConfigDict(from_attributes=True)

# =========================================================
# BLOCO 3: CONTRATOS DE PROJETOS E ESCROW
# =========================================================

class ProjetoBase(BaseModel):
    # Campos que aparecem tanto no anúncio quanto na venda
    titulo: str
    valor: float
    categoria: str = "geral"

class ProjetoCreate(ProjetoBase):
    # Quando o vendedor cria o anúncio, ele já define o que vai ser entregue (link/curso).
    # Não peço mais vendedor_id aqui: quem cria o anúncio é sempre o usuário
    # autenticado (pego do token), nunca um valor que o cliente poderia forjar.
    conteudo_digital: str

class Projeto(ProjetoBase):
    # Esse é o objeto completo que circula no sistema
    id: int
    vendedor_id: int
    status: StatusProjetoSchema
    # Ajustei o nome pra 'data_criacao' pra bater com o nosso banco de dados
    data_criacao: Optional[datetime] = None
    valor_no_escrow: float
    cliente_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class ProjetoLiberado(Projeto):
    # Só uso esse esquema quando o pagamento foi confirmado.
    # Aí eu libero o campo 'conteudo_digital' pro comprador ver.
    conteudo_digital: str

class PedidoComprador(Projeto):
    """
    Variante do Projeto usada SÓ na rota "/usuarios/{id}/pedidos" (que já
    confere que quem pergunta é o próprio dono do pedido). Expõe o código
    de liberação do escrow pro comprador conseguir ver de novo sempre que
    quiser, sem depender de ter guardado o toast do momento da confirmação.

    Importante: NUNCA usar esse esquema na listagem pública de projetos
    ("/projetos/") — lá o código vazaria pra qualquer pessoa.
    """
    codigo_verificacao: Optional[str] = None

# =========================================================
# BLOCO 3.1: PIX (SIMULADO)
# =========================================================

class PixCobranca(BaseModel):
    """
    O que devolvo quando o comprador inicia o checkout: os dados pra ele
    "pagar" (QR code + copia-e-cola). É tudo simulado — nenhum dinheiro
    real circula, não tem gateway de pagamento por trás.
    """
    projeto_id: int
    valor: float
    pix_txid: str
    pix_copia_cola: str
    qr_code_base64: str
    status: StatusProjetoSchema

# =========================================================
# BLOCO 4: VALIDAÇÃO DE SEGURANÇA
# =========================================================

class ValidarCodigo(BaseModel):
    """
    Esse é o contrato para a liberação: o vendedor precisa 
    enviar exatamente um campo chamado 'codigo' com os 6 dígitos.
    """
    codigo: str