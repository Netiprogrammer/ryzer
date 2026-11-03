/**
 * RYZER ENTERPRISE - JAVASCRIPT CORE v8.0
 * Integração: FastAPI (same-origin) + SweetAlert2 (Visual Pro) + JWT Auth + Pix simulado
 */

// String vazia = mesma origem que serviu essa página. Funciona local
// (uvicorn/127.0.0.1) e em qualquer deploy, sem precisar editar isso aqui.
const API_BASE = '';

function authHeaders() {
    const token = localStorage.getItem('access_token');
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

const Toast = Swal.mixin({
    toast: true,
    position: 'top-end',
    showConfirmButton: false,
    timer: 3000,
    timerProgressBar: true,
    didOpen: (toast) => {
        toast.addEventListener('mouseenter', Swal.stopTimer)
        toast.addEventListener('mouseleave', Swal.resumeTimer)
    }
});

function formatMoney(value) {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
}

// Escapa texto vindo do servidor/usuário antes de colocá-lo num template de
// innerHTML. Sem isso, um anúncio com título tipo <img onerror=...> executava
// script no navegador de quem abrisse a vitrine (XSS armazenado), com acesso
// ao token de login. REGRA: todo dado que não é número/constante nossa e vai
// dentro de uma string HTML tem que passar por esc().
function esc(valor) {
    return String(valor ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

// Mensagem de erro vinda da API (o backend devolve "detail" como texto).
function msgErro(data, padrao) {
    return (data && typeof data.detail === 'string' && data.detail) || padrao;
}

// Ícones próprios por categoria (SVG inline, sem depender de CDN de
// terceiros nem de fotos de marca que não são do projeto). Cada categoria
// tem seu próprio ícone Font Awesome + cor, renderizados num fundo
// uniforme — não é uma foto real do produto, é só uma identidade visual.
const CATEGORIA_ICONE = {
    hardware:     { icon: 'fa-microchip',     cor: '#00bf63' },
    perifericos:  { icon: 'fa-keyboard',      cor: '#ff6500' },
    computadores: { icon: 'fa-desktop',       cor: '#3b82f6' },
    software:     { icon: 'fa-graduation-cap', cor: '#a855f7' },
};

function getImagemProduto(categoria, tamanho = 72) {
    const conf = CATEGORIA_ICONE[categoria] || { icon: 'fa-box', cor: '#a8a8b3' };
    return `<i class="fas ${conf.icon}" style="font-size: ${tamanho}px; color: ${conf.cor};" aria-hidden="true"></i>`;
}

function router(tela) {
    document.querySelectorAll('section').forEach(s => s.classList.add('hidden'));
    const target = document.getElementById(`sec-${tela}`);
    
    if (target) {
        target.classList.remove('hidden');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    const uid = localStorage.getItem('usuario_id');
    const nav = document.getElementById('navbar');
    const footer = document.getElementById('footer');

    if (uid) {
        if(nav) nav.classList.remove('hidden');
        if(footer) footer.classList.remove('hidden');
        updateCartBadge();
        
        document.getElementById('user-name-display').innerText = localStorage.getItem('usuario_nome') || 'Cliente';

        if(tela === 'loja') carregarLoja();
        if(tela === 'carrinho') renderCarrinho();
        if(tela === 'dashboard') carregarDashboard();
        if(tela === 'meus-pedidos') carregarPedidos('grid-pedidos-page');
        if(tela === 'login' || tela === 'cadastro') router('loja');
    } else {
        if(nav) nav.classList.add('hidden');
        if(footer) footer.classList.add('hidden');
        if(tela !== 'login' && tela !== 'cadastro') router('login');
    }
}

window.onload = () => localStorage.getItem('usuario_id') ? router('loja') : router('login');

function toggleMenu() {
    document.getElementById('mobile-drawer').classList.toggle('hidden');
    document.getElementById('mobile-drawer-overlay').classList.toggle('hidden');
}

async function fazerLogin() {
    const email = document.getElementById('login-email').value;
    const senha = document.getElementById('login-senha').value;

    if (!email || !senha) return Toast.fire({ icon: 'warning', title: 'Preencha todos os campos' });

    Swal.fire({
        title: 'Conectando...',
        didOpen: () => { Swal.showLoading() }
    });

    try {
        const res = await fetch(`${API_BASE}/login/`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email, senha})
        });
        const data = await res.json();

        if (res.ok) {
            localStorage.setItem('usuario_id', data.usuario_id);
            localStorage.setItem('usuario_nome', data.nome);
            // ARQUITETURA DE SEGURANÇA: Persistir o token JWT
            localStorage.setItem('access_token', data.access_token); 
            Swal.close();
            
            Toast.fire({ icon: 'success', title: `Bem-vindo, ${esc(data.nome)}!` });
            router('loja');
        } else {
            Swal.fire({
                icon: 'error',
                title: 'Acesso Negado',
                text: msgErro(data, 'E-mail ou senha incorretos'),
                confirmButtonColor: '#ff3b30'
            });
        }
    } catch (e) {
        Swal.fire({ icon: 'error', title: 'Erro de Conexão', text: 'O servidor parece estar offline.' });
    }
}

async function cadastrar() {
    const nome = document.getElementById('cad-nome').value;
    const email = document.getElementById('cad-email').value;
    const senha = document.getElementById('cad-senha').value;
    
    if (!nome || !email || !senha) return Toast.fire({ icon: 'warning', title: 'Preencha todos os campos' });

    Swal.showLoading();

    try {
        const res = await fetch(`${API_BASE}/usuarios/`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({nome, email, senha})
        });
        if (res.ok) {
            Swal.fire({
                icon: 'success',
                title: 'Conta Criada!',
                text: 'Faça login para começar a comprar e vender.',
                confirmButtonColor: '#00bf63'
            }).then(() => router('login'));
        } else { 
            const err = await res.json();
            Swal.fire({ icon: 'error', title: 'Não foi possível criar a conta', text: msgErro(err, 'Verifique os dados e tente novamente.') });
        }
    } catch (e) {
        Swal.fire({ icon: 'error', title: 'Erro de Conexão', text: 'Tente novamente mais tarde.' });
    }
}

function logout() {
    Swal.fire({
        title: 'Sair da conta?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#3085d6',
        confirmButtonText: 'Sim, sair'
    }).then((result) => {
        if (result.isConfirmed) {
            localStorage.clear();
            location.reload();
        }
    });
}

let produtosCache = [];
let categoriaAtual = 'todas';
let ordenacaoAtual = 'relevancia';

async function carregarLoja() {
    const grid = document.getElementById('grid-produtos');
    grid.innerHTML = '<div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div>';

    try {
        const res = await fetch(`${API_BASE}/projetos/`);
        const data = await res.json();
        produtosCache = data.filter(p => p.status === 'aberto');
        renderGrid(produtosCache);
    } catch (e) {
        grid.innerHTML = '<p class="text-center">Erro ao carregar loja.</p>';
    }
}

function renderGrid(lista) {
    const grid = document.getElementById('grid-produtos');
    const termo = document.getElementById('campo-busca').value.toLowerCase();
    grid.innerHTML = "";

    let filtrados = lista.filter(p => p.titulo.toLowerCase().includes(termo));

    if (categoriaAtual !== 'todas') {
        filtrados = filtrados.filter(p => p.categoria === categoriaAtual);
    }

    if (ordenacaoAtual === 'menor_preco') {
        filtrados = [...filtrados].sort((a, b) => a.valor - b.valor);
    } else if (ordenacaoAtual === 'maior_preco') {
        filtrados = [...filtrados].sort((a, b) => b.valor - a.valor);
    }

    if (filtrados.length === 0) {
        grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:50px; color:var(--text-muted);">Nenhum produto encontrado.</div>`;
        return;
    }

    filtrados.forEach(p => {
        grid.innerHTML += `
            <div class="product-card fade-in">
                <div class="prod-img-box" onclick="verDetalhes(${p.id})" style="cursor: pointer;">
                    ${getImagemProduto(p.categoria)}
                </div>
                <div class="prod-info">
                    <h3 title="${esc(p.titulo)}">${esc(p.titulo)}</h3>
                    <span class="prod-price">${formatMoney(p.valor)}</span>
                    <span class="payment-info">Pix simulado — pagamento retido em escrow</span>
                </div>
                <button onclick="addCart(${p.id})" class="btn-cart btn-buy-large">
                    <i class="fas fa-cart-plus"></i> COMPRAR
                </button>
            </div>`;
    });
}

function buscarProduto() { renderGrid(produtosCache); }

function filtrarCategoria(cat, evt) {
    categoriaAtual = cat;
    document.querySelectorAll('.category-bar .cat-link').forEach(b => b.classList.remove('active'));
    if (evt && evt.currentTarget) evt.currentTarget.classList.add('active');
    Toast.fire({ icon: 'info', title: `Filtrando por: ${cat.toUpperCase()}` });
    renderGrid(produtosCache);
}

function mostrarTodasCategorias(evt) {
    categoriaAtual = 'todas';
    document.querySelectorAll('.category-bar .cat-link').forEach(b => b.classList.remove('active'));
    if (evt && evt.currentTarget) evt.currentTarget.classList.add('active');
    renderGrid(produtosCache);
}

function ordenarProdutos(valor) {
    ordenacaoAtual = valor;
    renderGrid(produtosCache);
}

function verDetalhes(id) {
    const p = produtosCache.find(i => i.id === id);
    if (!p) return;

    document.getElementById('det-img-container').innerHTML = getImagemProduto(p.categoria, 160);
    document.getElementById('det-titulo').innerText = p.titulo;
    document.getElementById('det-valor').innerText = formatMoney(p.valor);
    document.getElementById('bread-cat').innerText = p.categoria;
    document.getElementById('bread-nome').innerText = p.titulo;
    document.getElementById('det-desc').innerText = `Vendedor #${p.vendedor_id}\n\nO pagamento fica retido em escrow até você confirmar o recebimento com o código enviado após a compra.`;
    
    const btn = document.getElementById('btn-add-cart-detail');
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.onclick = () => { addCart(p.id); };

    router('detalhes');
}

function addCart(id) {
    let cart = JSON.parse(localStorage.getItem('ryzer_cart')) || [];
    if (!cart.includes(id)) {
        cart.push(id);
        localStorage.setItem('ryzer_cart', JSON.stringify(cart));
        updateCartBadge();
        Toast.fire({ icon: 'success', title: 'Adicionado ao carrinho!' });
    } else {
        Toast.fire({ icon: 'warning', title: 'Item já está no carrinho' });
    }
}

function updateCartBadge() {
    const count = (JSON.parse(localStorage.getItem('ryzer_cart')) || []).length;
    document.getElementById('cart-badge').innerText = count;
}

function renderCarrinho() {
    const container = document.getElementById('lista-carrinho');
    const cartIds = JSON.parse(localStorage.getItem('ryzer_cart')) || [];
    container.innerHTML = "";
    let total = 0;

    if (cartIds.length === 0) {
        container.innerHTML = "<p style='text-align:center; padding:40px; color:var(--text-muted)'>O teu carrinho está vazio.</p>";
        document.getElementById('cart-total').innerText = "R$ 0,00";
        document.getElementById('cart-subtotal').innerText = "R$ 0,00";
        return;
    }

    if (produtosCache.length === 0) { carregarLoja().then(renderCarrinho); return; }

    cartIds.forEach((id, idx) => {
        const p = produtosCache.find(i => i.id === id);
        if (p) {
            total += p.valor;
            container.innerHTML += `
                <div class="cart-item fade-in">
                    <div class="cart-item-icon">${getImagemProduto(p.categoria)}</div>
                    <div style="flex:1">
                        <strong>${esc(p.titulo)}</strong><br>
                        <small style="color:var(--text-muted)">Vendedor #${p.vendedor_id}</small>
                    </div>
                    <div class="text-right">
                        <div style="color:var(--primary); font-weight:bold;">${formatMoney(p.valor)}</div>
                        <button onclick="removeCart(${idx})" style="color:#ff3b30; font-size:12px; margin-top:5px; text-decoration:underline; background:none; border:none; cursor:pointer;">Remover</button>
                    </div>
                </div>`;
        }
    });

    document.getElementById('cart-subtotal').innerText = formatMoney(total);
    document.getElementById('cart-total').innerText = formatMoney(total);
}

function removeCart(idx) {
    let cart = JSON.parse(localStorage.getItem('ryzer_cart'));
    cart.splice(idx, 1);
    localStorage.setItem('ryzer_cart', JSON.stringify(cart));
    renderCarrinho();
    updateCartBadge();
}

async function finalizarCompra() {
    const cart = JSON.parse(localStorage.getItem('ryzer_cart')) || [];
    if (cart.length === 0) return Toast.fire({ icon: 'warning', title: 'Carrinho vazio' });

    const result = await Swal.fire({
        title: 'Confirmar Compra?',
        text: `Estás a comprar ${cart.length} ${cart.length > 1 ? 'itens' : 'item'}. Vamos gerar um Pix (simulado) pra cada um.`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#00bf63',
        cancelButtonColor: '#d33',
        confirmButtonText: 'Gerar Pix',
        background: '#202024',
        color: '#e1e1e6'
    });

    if (!result.isConfirmed) return;

    Swal.fire({ title: 'Gerando cobrança Pix...', didOpen: () => Swal.showLoading(), background: '#202024', color: '#e1e1e6' });

    // Gera uma cobrança Pix (simulada) para cada item do carrinho
    const cobrancas = [];
    for (const id of cart) {
        try {
            const res = await fetch(`${API_BASE}/projetos/${id}/checkout/pix/`, {
                method: 'POST',
                headers: authHeaders()
            });
            if (res.ok) {
                cobrancas.push(await res.json());
            }
        } catch (e) { console.error(e); }
    }

    if (cobrancas.length === 0) {
        Swal.fire({ icon: 'error', title: 'Erro', text: 'Não foi possível gerar o Pix. Sessão expirada?', background: '#202024', color: '#e1e1e6' });
        return;
    }

    await mostrarModalPix(cobrancas);
}

async function mostrarModalPix(cobrancas) {
    const total = cobrancas.reduce((soma, c) => soma + c.valor, 0);
    const primeiraCobranca = cobrancas[0];

    const html = `
        <p style="margin-bottom:10px; color:var(--text-muted)">
            ${cobrancas.length > 1 ? `${cobrancas.length} cobranças Pix geradas — total ` : 'Total '}
            <strong style="color:var(--primary)">${formatMoney(total)}</strong>
        </p>
        <img src="data:image/png;base64,${primeiraCobranca.qr_code_base64}" style="width:200px; height:200px; margin:10px auto; display:block; background:white; padding:8px; border-radius:8px;">
        <p style="font-size:12px; color:var(--text-muted); margin-bottom:6px;">Pix copia e cola (simulado):</p>
        <textarea readonly style="width:100%; height:60px; font-size:11px; padding:8px; border-radius:4px; border:1px solid var(--border); background:var(--dark); color:var(--text-main); resize:none;">${esc(primeiraCobranca.pix_copia_cola)}</textarea>
        <p style="font-size:12px; color:var(--text-muted); margin-top:10px;">
            <i class="fas fa-info-circle"></i> Isso é uma simulação para fins de demonstração — nenhum pagamento real é processado.
        </p>
    `;

    const result = await Swal.fire({
        title: 'Pague com Pix',
        html,
        showCancelButton: true,
        confirmButtonText: 'Já paguei (simular)',
        cancelButtonText: 'Cancelar',
        confirmButtonColor: '#00bf63',
        cancelButtonColor: '#d33',
        background: '#202024',
        color: '#e1e1e6'
    });

    if (!result.isConfirmed) {
        Toast.fire({ icon: 'info', title: 'Pix pendente — finalize o pagamento em "Meus Pedidos" quando quiser.' });
        localStorage.setItem('ryzer_cart', JSON.stringify([]));
        updateCartBadge();
        return;
    }

    Swal.fire({ title: 'Confirmando pagamento...', didOpen: () => Swal.showLoading(), background: '#202024', color: '#e1e1e6' });

    const codigos = [];
    for (const cobranca of cobrancas) {
        try {
            const res = await fetch(`${API_BASE}/projetos/${cobranca.projeto_id}/pix/confirmar`, {
                method: 'POST',
                headers: authHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                codigos.push(data.codigo_verificacao);
            }
        } catch (e) { console.error(e); }
    }

    localStorage.setItem('ryzer_cart', JSON.stringify([]));
    updateCartBadge();

    if (codigos.length > 0) {
        Swal.fire({
            icon: 'success',
            title: 'Pagamento Confirmado!',
            html: `O dinheiro fica retido com segurança até você confirmar o recebimento.<br><br>Os teus códigos de liberação:<br><b style="color:var(--primary)">${codigos.map(esc).join('<br>')}</b><br><br>Eles também ficam salvos em "Meus Pedidos".`,
            confirmButtonColor: '#00bf63',
            background: '#202024',
            color: '#e1e1e6'
        }).then(() => router('meus-pedidos'));
    } else {
        Swal.fire({ icon: 'error', title: 'Erro', text: 'Não foi possível confirmar o pagamento.', background: '#202024', color: '#e1e1e6' });
    }
}

async function carregarDashboard() {
    const uid = localStorage.getItem('usuario_id');
    try {
        const resTotal = await fetch(`${API_BASE}/vendedor/${uid}/total-vendas`, { headers: authHeaders() });
        if(resTotal.ok) {
            const dataTotal = await resTotal.json();
            document.getElementById('dash-total').innerText = formatMoney(dataTotal.total_vendas_concluidas || 0);
            // "Itens vendidos" vem do servidor (só conta vendas finalizadas).
            // Antes isso era o nº de anúncios do usuário, o que mostrava
            // "6 vendidos" com saldo R$ 0,00.
            document.getElementById('dash-count').innerText = dataTotal.itens_vendidos ?? 0;
        }

        const resProjs = await fetch(`${API_BASE}/projetos/`);
        const todos = await resProjs.json();
        // Esta aba é só do vendedor (anúncios e vendas). As compras ficam em
        // "Minhas Compras", onde também está o botão de confirmar recebimento.
        const meus = todos.filter(p => p.vendedor_id == uid);

        const tbody = document.getElementById('lista-vendas-table');
        tbody.innerHTML = "";

        if (meus.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--text-muted)">Você ainda não publicou nenhum anúncio.</td></tr>';
            return;
        }

        const STATUS_VENDEDOR = {
            aberto:               { texto: 'À venda',          cor: 'var(--text-muted)' },
            aguardando_pagamento: { texto: 'Aguardando Pix',   cor: '#ffc107' },
            pagamento_retido:     { texto: 'Pago (em escrow)', cor: '#ffc107' },
            finalizado:           { texto: 'Vendido',          cor: 'var(--primary)' },
            cancelado:            { texto: 'Cancelado',        cor: '#ff5555' },
        };

        meus.forEach(p => {
            const st = STATUS_VENDEDOR[p.status] || { texto: p.status, cor: 'var(--text-muted)' };
            tbody.innerHTML += `
                <tr>
                    <td>${esc(p.titulo)}</td>
                    <td style="font-weight:bold; color:var(--primary)">${formatMoney(p.valor)}</td>
                    <td><span class="status-badge" style="color:${st.cor}">${esc(st.texto)}</span></td>
                </tr>`;
        });
    } catch (e) {
        document.getElementById('lista-vendas-table').innerHTML =
            '<tr><td colspan="3" class="text-center" style="color:#ff5555">Não foi possível carregar o painel. Tente novamente.</td></tr>';
    }
}

async function liberarPagamento(id) {
    const { value: codigo } = await Swal.fire({
        title: 'Liberar Pagamento',
        input: 'text',
        inputLabel: 'Digite o código de liberação do seu pedido',
        inputPlaceholder: 'Código de 6 dígitos',
        showCancelButton: true,
        confirmButtonColor: '#00bf63',
        background: '#202024',
        color: '#e1e1e6'
    });

    if (!codigo) return;

    try {
        const res = await fetch(`${API_BASE}/projetos/${id}/liberar/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({ codigo: codigo })
        });
        if (res.ok) {
            const liberado = await res.json();
            // O conteúdo comprado é o motivo da compra: mostramos aqui e ele
            // também fica disponível depois em "Meus Pedidos".
            Swal.fire({
                title: 'Pagamento liberado!',
                icon: 'success',
                html: `<p style="margin-bottom:10px; color:var(--text-muted)">Aqui está o que você comprou:</p>
                       <div class="conteudo-entregue">${esc(liberado.conteudo_digital)}</div>
                       <p style="font-size:12px; color:var(--text-muted); margin-top:10px;">Você pode rever isso a qualquer momento em "Meus Pedidos".</p>`,
                confirmButtonColor: '#00bf63',
                background: '#202024',
                color: '#e1e1e6'
            });
            // Atualiza as duas listas de pedidos (página e aba do painel).
            carregarPedidos('grid-pedidos-page');
            carregarPedidos('grid-meus-pedidos');
        } else {
            const err = await res.json().catch(() => ({}));
            Swal.fire({title: 'Não foi possível liberar', text: msgErro(err, 'Tente novamente.'), icon: 'error', background: '#202024', color: '#e1e1e6'});
        }
    } catch (e) { Swal.fire({title: 'Erro', text: 'Falha na conexão.', icon: 'error', background: '#202024', color: '#e1e1e6'}); }
}

async function publicarAnuncio() {
    const titulo = document.getElementById('anun-titulo').value;
    const valor = document.getElementById('anun-valor').value;
    const categoria = document.getElementById('anun-cat').value;
    const conteudo = document.getElementById('anun-conteudo').value;

    if (!titulo || !valor || !conteudo) return Toast.fire({ icon: 'warning', title: 'Preencha todos os campos' });
    if (!(parseFloat(valor) > 0)) return Toast.fire({ icon: 'warning', title: 'O valor precisa ser maior que zero' });

    Swal.showLoading();

    try {
        const res = await fetch(`${API_BASE}/projetos/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({
                titulo: titulo,
                valor: parseFloat(valor),
                categoria: categoria,
                conteudo_digital: conteudo
            })
        });
        if (res.ok) { 
            Swal.fire({
                icon: 'success',
                title: 'Anúncio Publicado!',
                confirmButtonColor: '#00bf63',
                background: '#202024',
                color: '#e1e1e6'
            }).then(() => router('dashboard'));
        } else { 
            const err = await res.json();
            Swal.fire({title: 'Não foi possível publicar', text: msgErro(err, 'Falha ao publicar'), icon: 'error', background: '#202024', color: '#e1e1e6'});
        }
    } catch (e) { Swal.fire({title: 'Erro', text: 'Conexão falhou', icon: 'error', background: '#202024', color: '#e1e1e6'}); }
}

function switchDashTab(tab, evt) {
    document.getElementById('tab-vendas').classList.add('hidden');
    document.getElementById('tab-compras').classList.add('hidden');
    document.getElementById(`tab-${tab}`).classList.remove('hidden');

    document.querySelectorAll('.dash-menu-btn').forEach(b => b.classList.remove('active'));
    // currentTarget (não target): clicar no ícone dentro do botão não deve
    // marcar o ícone como "ativo" em vez do botão.
    if (evt && evt.currentTarget) evt.currentTarget.classList.add('active');

    if(tab === 'compras') carregarPedidos('grid-meus-pedidos');
}

// Carrega a lista de pedidos do comprador dentro do container informado.
// Existem dois lugares que mostram a mesma lista: a página "Meus Pedidos"
// (#grid-pedidos-page) e a aba "Minhas Compras" do painel (#grid-meus-pedidos).
async function carregarPedidos(containerId = 'grid-pedidos-page') {
    const usuarioId = localStorage.getItem('usuario_id');

    if (!usuarioId) {
        router('login');
        return;
    }

    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '<div class="skeleton-card" style="height:160px"></div><div class="skeleton-card" style="height:160px"></div>';

    try {
        const response = await fetch(`${API_BASE}/usuarios/${usuarioId}/pedidos`, {
            method: 'GET',
            headers: authHeaders()
        });

        if (!response.ok) {
            container.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:50px; color:#ff5555;">Não foi possível carregar seus pedidos. Tente novamente.</div>';
            return;
        }

        const pedidos = await response.json();
        container.innerHTML = '';

        if (pedidos.length === 0) {
            container.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:50px; color:var(--text-muted);">Você ainda não fez nenhuma compra.</div>';
            return;
        }

        pedidos.forEach(pedido => {
            let detalhe;
            if (pedido.status === 'aguardando_pagamento') {
                detalhe = `<p class="pedido-status" style="color:#ffc107;">⏳ Aguardando confirmação do Pix</p>`;
            } else if (pedido.status === 'pagamento_retido') {
                detalhe = `
                    <p class="pedido-status" style="color:#ffc107;">🔑 Código de liberação: <strong style="font-size:16px">${esc(pedido.codigo_verificacao)}</strong></p>
                    <button class="btn-liberar" onclick="liberarPagamento(${Number(pedido.id)})">
                        <i class="fas fa-check"></i> Confirmar recebimento
                    </button>`;
            } else if (pedido.status === 'finalizado') {
                detalhe = `
                    <p class="pedido-status" style="color:var(--primary);">✅ Transação finalizada</p>
                    <div class="conteudo-entregue">${esc(pedido.conteudo_digital)}</div>`;
            } else {
                detalhe = `<p class="pedido-status" style="color:var(--text-muted);">${esc(pedido.status)}</p>`;
            }

            container.innerHTML += `
                <div class="product-card fade-in">
                    <div class="prod-info">
                        <h3>${esc(pedido.titulo)}</h3>
                        <span class="prod-price" style="font-size:20px">${formatMoney(pedido.valor)}</span>
                        ${detalhe}
                    </div>
                </div>`;
        });
    } catch (error) {
        container.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:50px; color:#ff5555;">Erro de conexão. Tente novamente.</div>';
    }
}
