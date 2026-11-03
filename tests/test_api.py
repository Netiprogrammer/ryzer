from tests.conftest import cadastrar_e_logar, auth_header


# ---------------------------------------------------------------------------
# Usuários / autenticação
# ---------------------------------------------------------------------------

def test_cadastro_e_login(client):
    res = client.post("/usuarios/", json={
        "nome": "Ana", "email": "ana@exemplo.com", "senha": "123456"
    })
    assert res.status_code == 200, res.text
    assert res.json()["email"] == "ana@exemplo.com"

    res = client.post("/login/", json={"email": "ana@exemplo.com", "senha": "123456"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["nome"] == "Ana"


def test_cadastro_email_duplicado(client):
    client.post("/usuarios/", json={"nome": "Ana", "email": "ana@exemplo.com", "senha": "123456"})
    res = client.post("/usuarios/", json={"nome": "Outra Ana", "email": "ana@exemplo.com", "senha": "outrasenha"})
    assert res.status_code == 400


def test_login_senha_errada(client):
    client.post("/usuarios/", json={"nome": "Ana", "email": "ana@exemplo.com", "senha": "123456"})
    res = client.post("/login/", json={"email": "ana@exemplo.com", "senha": "errada"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Anúncios: exigem autenticação e não confiam em vendedor_id do cliente
# ---------------------------------------------------------------------------

def test_criar_anuncio_exige_autenticacao(client):
    res = client.post("/projetos/", json={
        "titulo": "Mouse Gamer", "valor": 100.0, "conteudo_digital": "link-secreto"
    })
    assert res.status_code == 401


def test_criar_anuncio_usa_usuario_autenticado_como_vendedor(client):
    uid_vendedor, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    _, _ = cadastrar_e_logar(client, email="outro@exemplo.com")

    # Mesmo tentando forjar um vendedor_id diferente no corpo, o backend
    # tem que usar o id do usuário autenticado pelo token.
    res = client.post(
        "/projetos/",
        json={
            "titulo": "Mouse Gamer", "valor": 100.0,
            "conteudo_digital": "link-secreto", "vendedor_id": 99999,
        },
        headers=auth_header(token_vendedor),
    )
    assert res.status_code == 200, res.text
    assert res.json()["vendedor_id"] == uid_vendedor


def test_listar_anuncios_e_publico(client):
    _, token = cadastrar_e_logar(client)
    client.post(
        "/projetos/",
        json={"titulo": "SSD 1TB", "valor": 399.9, "categoria": "hardware", "conteudo_digital": "codigo"},
        headers=auth_header(token),
    )
    res = client.get("/projetos/")
    assert res.status_code == 200
    titulos = [p["titulo"] for p in res.json()]
    assert "SSD 1TB" in titulos


# ---------------------------------------------------------------------------
# Fluxo completo de escrow com Pix simulado
# ---------------------------------------------------------------------------

def _publicar_produto(client, token_vendedor, valor=250.0):
    res = client.post(
        "/projetos/",
        json={"titulo": "Curso de Python", "valor": valor, "categoria": "software", "conteudo_digital": "link-curso-secreto"},
        headers=auth_header(token_vendedor),
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_fluxo_completo_pix_ate_liberacao(client):
    _, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    uid_comprador, token_comprador = cadastrar_e_logar(client, email="comprador@exemplo.com")

    projeto_id = _publicar_produto(client, token_vendedor)

    # 1. Checkout Pix
    res = client.post(f"/projetos/{projeto_id}/checkout/pix/", headers=auth_header(token_comprador))
    assert res.status_code == 200, res.text
    cobranca = res.json()
    assert cobranca["status"] == "aguardando_pagamento"
    assert cobranca["pix_copia_cola"]
    assert cobranca["qr_code_base64"]  # imagem do QR em base64

    # Produto some da vitrine pública enquanto aguarda pagamento
    abertos = [p["titulo"] for p in client.get("/projetos/").json()]
    # (a rota pública lista todos os status; quem filtra "aberto" é o frontend,
    # então aqui só garantimos que o status mudou de verdade)
    projeto_atual = next(p for p in client.get("/projetos/").json() if p["id"] == projeto_id)
    assert projeto_atual["status"] == "aguardando_pagamento"

    # 2. Confirmar pagamento (simula o webhook do gateway)
    res = client.post(f"/projetos/{projeto_id}/pix/confirmar", headers=auth_header(token_comprador))
    assert res.status_code == 200, res.text
    codigo = res.json()["codigo_verificacao"]
    assert len(codigo) == 6

    projeto_atual = next(p for p in client.get("/projetos/").json() if p["id"] == projeto_id)
    assert projeto_atual["status"] == "pagamento_retido"
    assert projeto_atual["valor_no_escrow"] == 250.0

    # 3. Liberar com código errado falha
    res = client.post(
        f"/projetos/{projeto_id}/liberar/",
        json={"codigo": "000000"},
        headers=auth_header(token_comprador),
    )
    assert res.status_code == 400

    # 4. Liberar com código certo funciona e devolve o conteúdo digital
    res = client.post(
        f"/projetos/{projeto_id}/liberar/",
        json={"codigo": codigo},
        headers=auth_header(token_comprador),
    )
    assert res.status_code == 200, res.text
    liberado = res.json()
    assert liberado["status"] == "finalizado"
    assert liberado["conteudo_digital"] == "link-curso-secreto"


def test_apenas_comprador_pode_liberar_pagamento(client):
    _, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    _, token_comprador = cadastrar_e_logar(client, email="comprador@exemplo.com")
    _, token_terceiro = cadastrar_e_logar(client, email="terceiro@exemplo.com")

    projeto_id = _publicar_produto(client, token_vendedor)
    client.post(f"/projetos/{projeto_id}/checkout/pix/", headers=auth_header(token_comprador))
    res = client.post(f"/projetos/{projeto_id}/pix/confirmar", headers=auth_header(token_comprador))
    codigo = res.json()["codigo_verificacao"]

    # Um terceiro (nem comprador nem vendedor) não pode liberar, mesmo com o código certo
    res = client.post(
        f"/projetos/{projeto_id}/liberar/",
        json={"codigo": codigo},
        headers=auth_header(token_terceiro),
    )
    assert res.status_code == 403


def test_codigo_verificacao_aparece_em_meus_pedidos_mas_nao_na_vitrine_publica(client):
    # Bug real que achei no front: "Meus Pedidos" mostrava "undefined" no
    # lugar do código de liberação, porque o schema público "Projeto" não
    # tinha esse campo. Aqui garanto que (a) o comprador vê o código em
    # "/usuarios/{id}/pedidos" depois de confirmar o Pix, e (b) a vitrine
    # pública ("/projetos/") continua SEM esse campo — ele não pode vazar
    # pra qualquer pessoa que não é parte da transação.
    _, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    uid_comprador, token_comprador = cadastrar_e_logar(client, email="comprador@exemplo.com")

    projeto_id = _publicar_produto(client, token_vendedor)
    client.post(f"/projetos/{projeto_id}/checkout/pix/", headers=auth_header(token_comprador))
    res = client.post(f"/projetos/{projeto_id}/pix/confirmar", headers=auth_header(token_comprador))
    codigo = res.json()["codigo_verificacao"]

    pedidos = client.get(f"/usuarios/{uid_comprador}/pedidos", headers=auth_header(token_comprador)).json()
    pedido = next(p for p in pedidos if p["id"] == projeto_id)
    assert pedido["codigo_verificacao"] == codigo

    vitrine = client.get("/projetos/").json()
    produto_na_vitrine = next(p for p in vitrine if p["id"] == projeto_id)
    assert "codigo_verificacao" not in produto_na_vitrine


def test_nao_pode_pagar_projeto_que_nao_esta_aberto(client):
    _, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    _, token_comprador1 = cadastrar_e_logar(client, email="comprador1@exemplo.com")
    _, token_comprador2 = cadastrar_e_logar(client, email="comprador2@exemplo.com")

    projeto_id = _publicar_produto(client, token_vendedor)
    client.post(f"/projetos/{projeto_id}/checkout/pix/", headers=auth_header(token_comprador1))

    # Outro comprador tenta gerar Pix pro mesmo projeto, que já não está mais ABERTO
    res = client.post(f"/projetos/{projeto_id}/checkout/pix/", headers=auth_header(token_comprador2))
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Autorização: cada um só vê os próprios dados
# ---------------------------------------------------------------------------

def test_usuario_nao_pode_ver_pedidos_de_outro(client):
    uid1, token1 = cadastrar_e_logar(client, email="user1@exemplo.com")
    uid2, token2 = cadastrar_e_logar(client, email="user2@exemplo.com")

    res = client.get(f"/usuarios/{uid2}/pedidos", headers=auth_header(token1))
    assert res.status_code == 403

    res = client.get(f"/usuarios/{uid1}/pedidos", headers=auth_header(token1))
    assert res.status_code == 200


def test_usuario_nao_pode_ver_vendas_de_outro(client):
    uid1, token1 = cadastrar_e_logar(client, email="user1@exemplo.com")
    uid2, token2 = cadastrar_e_logar(client, email="user2@exemplo.com")

    res = client.get(f"/vendedor/{uid2}/total-vendas", headers=auth_header(token1))
    assert res.status_code == 403


def test_rotas_protegidas_exigem_token_valido(client):
    res = client.get("/usuarios/1/pedidos", headers={"Authorization": "Bearer token-invalido"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Saúde da aplicação
# ---------------------------------------------------------------------------

def test_healthcheck(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "Online"}


def test_home_page_carrega(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


# ---------------------------------------------------------------------------
# Validação de entrada (achados da auditoria: preço negativo/NaN, senha de
# 1 caractere, e-mail sem validar, anúncio com título de 100 KB...)
# ---------------------------------------------------------------------------

import pytest

JSON = {"Content-Type": "application/json"}


@pytest.mark.parametrize("valor_json", ["-50", "0", "NaN", "Infinity", "1e308"])
def test_anuncio_rejeita_valor_invalido(client, valor_json):
    _, token = cadastrar_e_logar(client)
    corpo = '{"titulo": "Produto X", "valor": %s, "conteudo_digital": "x"}' % valor_json
    res = client.post("/projetos/", content=corpo, headers={**JSON, **auth_header(token)})
    assert res.status_code == 422, res.text


@pytest.mark.parametrize("campos", [
    {"titulo": "ab"},                      # curto demais
    {"titulo": "A" * 5000},                # longo demais
    {"titulo": "   "},                     # só espaços
    {"categoria": "categoria-inexistente"},
    {"conteudo_digital": "   "},
    {"conteudo_digital": "x" * 5000},
])
def test_anuncio_rejeita_campos_invalidos(client, campos):
    _, token = cadastrar_e_logar(client)
    corpo = {"titulo": "Produto X", "valor": 10.0, "categoria": "hardware", "conteudo_digital": "x", **campos}
    res = client.post("/projetos/", json=corpo, headers=auth_header(token))
    assert res.status_code == 422, res.text


def test_erro_de_validacao_nao_ecoa_a_entrada_do_usuario(client):
    # O 422 padrão devolvia o que foi digitado (inclusive a senha) em "input".
    res = client.post("/usuarios/", json={"nome": "Ana", "email": "ana@exemplo.com", "senha": "senha-curta-secreta"[:5]})
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], str)       # mensagem legível pro front
    assert "input" not in res.text and "senh" not in res.text.replace("Senha", "")


@pytest.mark.parametrize("corpo", [
    {"nome": "Ana", "email": "ana@exemplo.com", "senha": "123"},          # senha curta
    {"nome": "Ana", "email": "ana@exemplo.com", "senha": "x" * 100},      # acima do limite do bcrypt
    {"nome": "Ana", "email": "isso-nao-e-email", "senha": "123456"},
    {"nome": "   ", "email": "ana@exemplo.com", "senha": "123456"},
])
def test_cadastro_rejeita_dados_invalidos(client, corpo):
    assert client.post("/usuarios/", json=corpo).status_code == 422


def test_email_nao_diferencia_maiusculas_de_minusculas(client):
    assert client.post("/usuarios/", json={"nome": "Ana", "email": "Ana@Exemplo.com", "senha": "123456"}).status_code == 200
    # Mesmo e-mail com outra caixa/espaços não pode virar uma segunda conta...
    res = client.post("/usuarios/", json={"nome": "Outra", "email": "  ana@exemplo.com ", "senha": "123456"})
    assert res.status_code == 400
    # ...e o login funciona independentemente da caixa.
    res = client.post("/login/", json={"email": "ANA@EXEMPLO.COM", "senha": "123456"})
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Regras de negócio
# ---------------------------------------------------------------------------

def test_vendedor_nao_pode_comprar_o_proprio_anuncio(client):
    _, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    projeto_id = _publicar_produto(client, token_vendedor)

    res = client.post(f"/projetos/{projeto_id}/checkout/pix/", headers=auth_header(token_vendedor))
    assert res.status_code == 400

    # O anúncio continua à venda (não ficou preso em "aguardando pagamento").
    produto = next(p for p in client.get("/projetos/").json() if p["id"] == projeto_id)
    assert produto["status"] == "aberto"


def test_conteudo_digital_so_aparece_em_pedidos_depois_de_liberar(client):
    _, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    uid_comprador, token_comprador = cadastrar_e_logar(client, email="comprador@exemplo.com")
    projeto_id = _publicar_produto(client, token_vendedor)

    def meu_pedido():
        pedidos = client.get(f"/usuarios/{uid_comprador}/pedidos", headers=auth_header(token_comprador)).json()
        return next(p for p in pedidos if p["id"] == projeto_id)

    client.post(f"/projetos/{projeto_id}/checkout/pix/", headers=auth_header(token_comprador))
    assert meu_pedido()["conteudo_digital"] is None          # aguardando Pix

    codigo = client.post(f"/projetos/{projeto_id}/pix/confirmar", headers=auth_header(token_comprador)).json()["codigo_verificacao"]
    assert meu_pedido()["conteudo_digital"] is None          # pago, mas ainda em escrow

    client.post(f"/projetos/{projeto_id}/liberar/", json={"codigo": codigo}, headers=auth_header(token_comprador))
    # Depois de liberado, o comprador consegue rever o conteúdo quando quiser
    # (antes ele só vinha uma vez na resposta de "/liberar/" e se perdia).
    assert meu_pedido()["conteudo_digital"] == "link-curso-secreto"

    # E a vitrine pública continua sem expor o conteúdo.
    publico = next(p for p in client.get("/projetos/").json() if p["id"] == projeto_id)
    assert "conteudo_digital" not in publico


def test_liberar_com_codigo_nao_ascii_responde_400_e_nao_500(client):
    _, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    _, token_comprador = cadastrar_e_logar(client, email="comprador@exemplo.com")
    projeto_id = _publicar_produto(client, token_vendedor)
    client.post(f"/projetos/{projeto_id}/checkout/pix/", headers=auth_header(token_comprador))
    client.post(f"/projetos/{projeto_id}/pix/confirmar", headers=auth_header(token_comprador))

    res = client.post(f"/projetos/{projeto_id}/liberar/", json={"codigo": "códígo✓"}, headers=auth_header(token_comprador))
    assert res.status_code == 400


def test_total_de_vendas_soma_apenas_finalizados(client):
    uid_vendedor, token_vendedor = cadastrar_e_logar(client, email="vendedor@exemplo.com")
    _, token_comprador = cadastrar_e_logar(client, email="comprador@exemplo.com")

    vendido = _publicar_produto(client, token_vendedor, valor=250.0)
    _publicar_produto(client, token_vendedor, valor=999.0)  # continua aberto: não conta

    client.post(f"/projetos/{vendido}/checkout/pix/", headers=auth_header(token_comprador))
    codigo = client.post(f"/projetos/{vendido}/pix/confirmar", headers=auth_header(token_comprador)).json()["codigo_verificacao"]
    client.post(f"/projetos/{vendido}/liberar/", json={"codigo": codigo}, headers=auth_header(token_comprador))

    res = client.get(f"/vendedor/{uid_vendedor}/total-vendas", headers=auth_header(token_vendedor))
    assert res.json() == {"total_vendas_concluidas": 250.0, "itens_vendidos": 1}
