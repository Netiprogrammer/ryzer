import re
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from enum import Enum
from typing import Optional, List, Literal

# Categorias que a vitrine conhece (o front tem um ícone por categoria).
# "geral" é o valor padrão antigo, mantido pra não quebrar anúncios existentes.
Categoria = Literal["hardware", "perifericos", "computadores", "software", "geral"]

# Validação simples de e-mail (sem dependência extra): algo@dominio.tld.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# O bcrypt só considera os primeiros 72 bytes da senha; limitar o tamanho
# evita senhas "truncadas em silêncio" e entradas absurdamente grandes.
SENHA_MIN, SENHA_MAX = 6, 72

# Teto de preço: evita valores como 1e308 que estouram a formatação/contas.
VALOR_MAX = 1_000_000

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

def normalizar_email(valor: str) -> str:
    """Tira espaços e põe em minúsculas, pra 'Ana@x.com' e 'ana@x.com' serem a mesma conta."""
    return valor.strip().lower()


class UsuarioBase(BaseModel):
    # O básico que todo usuário tem que ter
    nome: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=254)

    @field_validator("nome")
    @classmethod
    def _nome_sem_espacos_nas_pontas(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("O nome não pode ficar em branco.")
        return v

    @field_validator("email")
    @classmethod
    def _email_valido(cls, v: str) -> str:
        v = normalizar_email(v)
        if not _EMAIL_RE.match(v):
            raise ValueError("E-mail inválido.")
        return v

class UsuarioCreate(UsuarioBase):
    # Na hora de criar, eu exijo a senha em texto puro (depois o CRUD faz o hash)
    senha: str = Field(min_length=SENHA_MIN, max_length=SENHA_MAX)

class UsuarioLogin(BaseModel):
    # O que o cara digita na tela de login. Aqui não exigimos o tamanho mínimo
    # da senha (contas antigas/de demonstração podem ter regras diferentes),
    # só normalizamos o e-mail e limitamos o tamanho.
    email: str = Field(max_length=254)
    senha: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _email_normalizado(cls, v: str) -> str:
        return normalizar_email(v)

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
    # Aqui (base, que também é usada nas RESPOSTAS) fica tudo permissivo de
    # propósito: se um anúncio antigo do banco tiver, por exemplo, uma
    # categoria que não existe mais, a vitrine não pode quebrar por isso.
    # As regras estritas valem só na ENTRADA, em ProjetoCreate.
    titulo: str
    valor: float
    categoria: str = "geral"

class ProjetoCreate(ProjetoBase):
    # Quando o vendedor cria o anúncio, ele já define o que vai ser entregue (link/curso).
    # Não peço mais vendedor_id aqui: quem cria o anúncio é sempre o usuário
    # autenticado (pego do token), nunca um valor que o cliente poderia forjar.
    titulo: str = Field(min_length=3, max_length=120)
    # allow_inf_nan=False barra NaN/Infinity (o JSON do Python aceita esses
    # literais); gt=0 barra preço zero/negativo; le=VALOR_MAX barra 1e308.
    valor: float = Field(gt=0, le=VALOR_MAX, allow_inf_nan=False)
    categoria: Categoria = "geral"
    conteudo_digital: str = Field(min_length=1, max_length=2000)

    @field_validator("titulo", "conteudo_digital")
    @classmethod
    def _sem_espacos_nas_pontas(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Campo não pode ficar em branco.")
        return v

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

    O 'conteudo_digital' (o que o comprador de fato comprou) também só sai
    aqui, e só depois que o pagamento é liberado (status "finalizado") — a
    rota em main.py zera o campo nos outros status. Sem isso, o comprador
    só via o conteúdo uma única vez, na resposta de "/liberar/", e perdia
    o acesso se fechasse a tela.
    """
    codigo_verificacao: Optional[str] = None
    conteudo_digital: Optional[str] = None

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
    codigo: str = Field(min_length=1, max_length=32)

# --- VITRINE PÚBLICA -------------------------------------------------------
# O que qualquer visitante pode ver de um anúncio aberto. De propósito não
# inclui cliente_id, conteúdo digital nem código (nada de dado privado).
class ProjetoVitrine(BaseModel):
    id: int
    titulo: str
    valor: float
    categoria: str
    vendedor_id: int
    vendedor_nome: str
    data_criacao: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ResultadoBusca(BaseModel):
    itens: List[ProjetoVitrine]
    total: int
    pagina: int
    paginas: int
    por_pagina: int
    # Contagem por categoria (respeita busca e faixa de preço, mas não o filtro
    # de categoria) — alimenta os números ao lado de cada filtro.
    categorias: dict[str, int]
    preco_min: Optional[float] = None
    preco_max: Optional[float] = None
