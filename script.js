/* ============================================================
   TSOK.SHOP — MAIN SCRIPT
   ============================================================ */

'use strict';

/* ============================================================
   CART STATE
   ============================================================ */
let cart = JSON.parse(localStorage.getItem('tsok_cart') || '[]');
let favorites = JSON.parse(localStorage.getItem('tsok_favs') || '[]');

function saveCart() {
    localStorage.setItem('tsok_cart', JSON.stringify(cart));
    updateCartUI();
}
function saveFavs() {
    localStorage.setItem('tsok_favs', JSON.stringify(favorites));
    updateFavUI();
}

function addToCart(id, name, price, size, brand, img) {
    const existing = cart.find(i => i.id === id);
    if (existing) {
        existing.qty += 1;
    } else {
        cart.push({ id, name, price, size, brand, img, qty: 1 });
    }
    saveCart();
    showToast(`«${name}» добавлен в корзину`, 'cart');
}

function removeFromCart(id) {
    cart = cart.filter(i => i.id !== id);
    saveCart();
    renderCartItems();
}

function updateQty(id, delta) {
    const item = cart.find(i => i.id === id);
    if (!item) return;
    item.qty = Math.max(1, item.qty + delta);
    saveCart();
    renderCartItems();
}

function toggleFavorite(id, name) {
    const idx = favorites.indexOf(id);
    if (idx === -1) {
        favorites.push(id);
        showToast(`«${name}» сохранён`, 'heart');
    } else {
        favorites.splice(idx, 1);
    }
    saveFavs();
    updateBookmarkBtns();
}

function updateCartUI() {
    const total = cart.reduce((s, i) => s + i.qty, 0);
    document.querySelectorAll('.cart-count').forEach(el => el.textContent = total);
    document.querySelectorAll('#cartTotalSum').forEach(el => {
        const sum = cart.reduce((s, i) => s + i.qty * i.price, 0);
        el.textContent = sum.toFixed(0) + ' BYN';
    });
}

function updateFavUI() {
    const total = favorites.length;
    document.querySelectorAll('.fav-count').forEach(el => el.textContent = total);
}

function updateBookmarkBtns() {
    document.querySelectorAll('.js-bookmark[data-id]').forEach(btn => {
        const id = btn.dataset.id;
        btn.classList.toggle('is-saved', favorites.includes(id));
    });
}

function renderCartItems() {
    const container = document.getElementById('cartItemsContainer');
    const emptyMsg  = document.getElementById('emptyCartMessage');
    if (!container) return;

    const items = container.querySelectorAll('.cart-item');
    items.forEach(el => el.remove());

    if (cart.length === 0) {
        if (emptyMsg) emptyMsg.style.display = '';
    } else {
        if (emptyMsg) emptyMsg.style.display = 'none';
        cart.forEach(item => {
            const el = document.createElement('div');
            el.className = 'cart-item';
            el.innerHTML = `
                <div class="cart-item__img">
                    ${item.img ? `<img src="${item.img}" alt="${item.name}">` : ''}
                </div>
                <div class="cart-item__info">
                    <div class="cart-item__top">
                        <h4>${item.name}</h4>
                        <span class="cart-item__price">${(item.price * item.qty).toFixed(0)} BYN</span>
                    </div>
                    <span class="cart-item__size">${item.size || ''}</span>
                    <div class="cart-item__controls">
                        <div class="quantity-selector">
                            <button onclick="updateQty('${item.id}', -1)">−</button>
                            <span>${item.qty}</span>
                            <button onclick="updateQty('${item.id}', +1)">+</button>
                        </div>
                        <button class="cart-item__remove" onclick="removeFromCart('${item.id}')">Удалить</button>
                    </div>
                </div>`;
            container.insertBefore(el, emptyMsg);
        });
    }
    updateCartUI();
}

/* ============================================================
   CART DRAWER
   ============================================================ */
function openCart() {
    document.getElementById('cartDrawer')?.classList.add('is-active');
    document.getElementById('globalOverlay')?.classList.add('is-active');
    renderCartItems();
}
function closeCart() {
    document.getElementById('cartDrawer')?.classList.remove('is-active');
    document.getElementById('globalOverlay')?.classList.remove('is-active');
}

/* ============================================================
   MOBILE MENU
   ============================================================ */
function openMenu() {
    document.getElementById('mobileMenu')?.classList.add('is-active');
    document.getElementById('globalOverlay')?.classList.add('is-active');
}
function closeMenu() {
    document.getElementById('mobileMenu')?.classList.remove('is-active');
    document.getElementById('globalOverlay')?.classList.remove('is-active');
}

/* ============================================================
   HEADER SCROLL BEHAVIOR — hide all sticky on scroll down
   ============================================================ */
function initHeaderScroll() {
    const siteTop = document.getElementById('siteTop');
    const hg = document.getElementById('headerGroup');
    if (!siteTop && !hg) return;
    const el = siteTop || hg;

    // Collect ALL sticky elements that should hide with the header
    function getStickyEls() {
        return [
            document.getElementById('productStickyBar'),
            ...document.querySelectorAll('.product-sticky-bar, .catalog-toolbar[style*="sticky"]')
        ].filter(Boolean);
    }

    let lastY = 0, ticking = false;

    window.addEventListener('scroll', () => {
        if (!ticking) {
            requestAnimationFrame(() => {
                const y = window.scrollY;
                if (hg) hg.classList.toggle('is-solid', y > 20);

                // Hide everything when scrolling down, show on scroll up
                const goingDown = y > lastY + 4 && y > 120;
                const goingUp   = y < lastY - 4;

                if (goingDown) {
                    el.classList.add('is-hidden');
                    // Also hide product sticky bar
                    getStickyEls().forEach(s => {
                        s.style.transition = 'transform 0.3s ease, opacity 0.3s ease';
                        s.style.transform  = 'translateY(-120%)';
                        s.style.opacity    = '0';
                    });
                } else if (goingUp || y < 80) {
                    el.classList.remove('is-hidden');
                    getStickyEls().forEach(s => {
                        s.style.transform = '';
                        s.style.opacity   = '';
                    });
                }

                lastY = y;
                ticking = false;
            });
            ticking = true;
        }
    }, { passive: true });
}

/* ============================================================
   ACCORDIONS
   ============================================================ */
function initAccordions() {
    document.querySelectorAll('.accordion__btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const expanded = btn.getAttribute('aria-expanded') === 'true';
            btn.setAttribute('aria-expanded', String(!expanded));
            const content = btn.nextElementSibling;
            if (content) content.classList.toggle('is-open', !expanded);
        });
    });
}

/* ============================================================
   SCROLL-REVEAL ANIMATIONS
   ============================================================ */
function initScrollReveal() {
    if (!('IntersectionObserver' in window)) {
        document.querySelectorAll('.anim-fade-up').forEach(el => el.classList.add('is-visible'));
        return;
    }
    const obs = new IntersectionObserver((entries) => {
        entries.forEach(e => {
            if (e.isIntersecting) {
                e.target.classList.add('is-visible');
                obs.unobserve(e.target);
            }
        });
    }, { threshold: 0.12 });
    document.querySelectorAll('.anim-fade-up').forEach(el => obs.observe(el));
}

/* ============================================================
   CAROUSEL NAV
   ============================================================ */
function initCarousels() {
    document.querySelectorAll('[data-carousel]').forEach(section => {
        const track = section.querySelector('.carousel');
        const prev  = section.querySelector('[data-carousel-prev]');
        const next  = section.querySelector('[data-carousel-next]');
        if (!track) return;

        const scrollAmount = () => {
            const card = track.querySelector('.product-card');
            return card ? card.offsetWidth + 20 : 320;
        };
        prev?.addEventListener('click', () => track.scrollBy({ left: -scrollAmount(), behavior: 'smooth' }));
        next?.addEventListener('click', () => track.scrollBy({ left:  scrollAmount(), behavior: 'smooth' }));
    });
}

/* ============================================================
   CATALOG FILTER
   ============================================================ */
function initCatalogFilter() {
    const btns  = document.querySelectorAll('.filter-btn[data-filter]');
    const cards = document.querySelectorAll('.catalog-grid .product-card[data-category]');
    const countEl = document.querySelector('.catalog-count');
    if (!btns.length) return;

    function applyFilter(filter) {
        let visible = 0;
        cards.forEach(card => {
            const cat = card.dataset.category;
            const isNew = card.dataset.badge === 'new' || card.querySelector('.product-card__badge');
            const show = filter === 'all'
                || cat === filter
                || (filter === 'new' && isNew);

            if (show) {
                card.style.display = '';
                card.style.opacity = '0';
                card.style.transform = 'translateY(12px)';
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        card.style.transition = 'opacity 0.35s ease, transform 0.35s ease';
                        card.style.opacity = '1';
                        card.style.transform = 'translateY(0)';
                    });
                });
                visible++;
            } else {
                card.style.transition = 'opacity 0.2s ease';
                card.style.opacity = '0';
                setTimeout(() => { card.style.display = 'none'; }, 200);
            }
        });
        if (countEl) countEl.textContent = visible + ' продуктов';
    }

    btns.forEach(btn => {
        btn.addEventListener('click', () => {
            btns.forEach(b => b.classList.remove('is-active'));
            btn.classList.add('is-active');
            applyFilter(btn.dataset.filter);
        });
    });

    // Price range filter
    const priceRange = document.querySelector('input[type=range]');
    const priceLabel = document.getElementById('priceMax');
    if (priceRange) {
        priceRange.addEventListener('input', () => {
            const max = parseInt(priceRange.value);
            if (priceLabel) priceLabel.textContent = max + ' BYN';
            cards.forEach(card => {
                const priceEl = card.querySelector('.product-card__price');
                if (!priceEl) return;
                const price = parseInt(priceEl.textContent);
                const currentFilter = document.querySelector('.filter-btn.is-active')?.dataset.filter || 'all';
                const catMatch = currentFilter === 'all' || card.dataset.category === currentFilter;
                const show = catMatch && price <= max;
                card.style.display = show ? '' : 'none';
            });
        });
    }

    // Apply initial filter
    applyFilter('all');
}

/* ============================================================
   ADD TO CART — DATA ATTRS
   ============================================================ */
function initAddToCartBtns() {
    document.querySelectorAll('.js-add-to-cart').forEach(btn => {
        btn.addEventListener('click', () => {
            const id    = btn.dataset.id    || 'product-' + Math.random().toString(36).slice(2, 7);
            const name  = btn.dataset.name  || 'Продукт';
            const price = parseFloat(btn.dataset.price) || 0;
            const size  = btn.dataset.size  || '';
            const brand = btn.dataset.brand || '';
            const img   = btn.dataset.img   || '';
            addToCart(id, name, price, size, brand, img);
        });
    });
}

/* ============================================================
   BOOKMARK BUTTONS
   ============================================================ */
function initBookmarkBtns() {
    document.querySelectorAll('.js-bookmark').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const id   = btn.dataset.id   || 'fav-' + Math.random().toString(36).slice(2, 7);
            const name = btn.dataset.name || 'Продукт';
            toggleFavorite(id, name);
        });
    });
    updateBookmarkBtns();
}

/* ============================================================
   TOAST NOTIFICATIONS
   ============================================================ */
function showToast(message, type = 'cart') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const icons = {
        cart: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="5" y="8" width="14" height="13" rx="1"/><path d="M8 8V6C8 4.9 8.9 4 10 4h4c1.1 0 2 .9 2 2v2"/></svg>`,
        heart: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>`,
    };

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `<span class="toast__icon">${icons[type] || icons.cart}</span><span>${message}</span>`;
    container.appendChild(toast);

    requestAnimationFrame(() => {
        requestAnimationFrame(() => toast.classList.add('is-visible'));
    });

    setTimeout(() => {
        toast.classList.remove('is-visible');
        setTimeout(() => toast.remove(), 500);
    }, 3200);
}

/* ============================================================
   MARQUEE DUPLICATE (for seamless loop)
   ============================================================ */
function initMarquee() {
    document.querySelectorAll('.marquee-track').forEach(track => {
        // Clone children for seamless loop
        const items = Array.from(track.children);
        items.forEach(item => track.appendChild(item.cloneNode(true)));
    });
}

/* ============================================================
   SUBSCRIBE FORM
   ============================================================ */
function initSubscribeForms() {
    document.querySelectorAll('.subscribe-form').forEach(form => {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = form.querySelector('input');
            if (input && input.value.trim()) {
                showToast('Вы подписаны на новости!', 'heart');
                input.value = '';
            }
        });
    });
}

/* ============================================================
   BRAND SWITCHER (header)
   ============================================================ */
function initBrandSwitcher() {
    document.querySelectorAll('.brand-switcher__btn[data-href]').forEach(btn => {
        btn.addEventListener('click', () => {
            window.location.href = btn.dataset.href;
        });
    });
}

/* ============================================================
   PRODUCT PAGE — image zoom (optional tap)
   ============================================================ */
function initProductGallery() {
    const img = document.querySelector('.product-gallery__img');
    if (!img) return;
    let zoomed = false;
    img.addEventListener('click', () => {
        zoomed = !zoomed;
        img.style.objectFit = zoomed ? 'contain' : 'cover';
        img.style.cursor = zoomed ? 'zoom-out' : 'zoom-in';
    });
    img.style.cursor = 'zoom-in';
}

/* ============================================================
   INIT
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {
    // Header
    initHeaderScroll();

    // Cart open/close
    document.getElementById('cartOpenBtn')?.addEventListener('click', openCart);
    document.getElementById('cartCloseBtn')?.addEventListener('click', closeCart);

    // Mobile menu
    document.getElementById('burgerBtn')?.addEventListener('click', openMenu);
    document.getElementById('mobileMenuClose')?.addEventListener('click', closeMenu);

    // Overlay closes everything
    document.getElementById('globalOverlay')?.addEventListener('click', () => {
        closeCart();
        closeMenu();
    });

    // Features
    initAccordions();
    initScrollReveal();
    initCarousels();
    initCatalogFilter();
    initAddToCartBtns();
    initBookmarkBtns();
    initMarquee();
    initSubscribeForms();
    initBrandSwitcher();
    initProductGallery();

    // Initial UI sync
    updateCartUI();
    updateFavUI();
    renderCartItems();
    /* ============================================================
   ДИНАМИЧЕСКАЯ СТРАНИЦА ТОВАРА
   ============================================================ */
const productsDB = {
    "pearl-01": {
        name1: "Foam Mousse", name2: "Moisture",
        desc: "Увлажняющая пенка для лица. Бережное очищение без чувства стянутости.",
        price: 96, size: "150 мл", img: "img/Pearl1.jpg"
    },
    "pearl-02": {
        name1: "Face Tonic", name2: "Toning",
        desc: "Тоник для лица «Тонус». Устраняет следы усталости и освежает кожу.",
        price: 93, size: "150 мл", img: "img/Pearl2.jpg"
    },
    "pearl-03": {
        name1: "Tonic Youth", name2: "Restoring",
        desc: "Тоник-реставратор молодости. Восстанавливает pH-баланс после умывания и сужает поры. Первый шаг к живой коже.",
        price: 93, size: "150 мл", img: "img/Pearl3.jpg"
    },
    "pearl-04": {
        name1: "Foam Mousse", name2: "Cleansing",
        desc: "Пенка для умывания «Мягкое очищение». Идеально для чувствительной и реактивной кожи.",
        price: 96, size: "150 мл", img: "img/Pearl4.jpg"
    },
    "pearl-05": {
        name1: "Hair Tonic", name2: "Radiance",
        desc: "Тоник для волос «Укрепляющий». Стимулирует рост, укрепляет корни и придает блеск.",
        price: 88, size: "200 мл", img: "img/Pearl5.jpg"
    },
    "pearl-06": {
        name1: "Velvet Oil", name2: "Blend",
        desc: "Микс масел для волос. Глубокое питание и защита секущихся кончиков.",
        price: 69, size: "60 мл", img: "img/Pearl6.jpg"
    },
    "pearl-07": {
        name1: "Micellar Water", name2: "Extract Mix",
        desc: "Мицеллярная вода «С экстрактами». Легкий демакияж глаз и деликатное тонизирование.",
        price: 99, size: "200 мл", img: "img/Pearl7.jpg"
    }
};

function renderProductPage() {
    // Проверяем, находимся ли мы на странице товара (ищем элемент с ID)
    const titleEl = document.getElementById('prodMainTitle');
    if (!titleEl) return;

    // Получаем ID из URL (например: ?id=pearl-01)
    const params = new URLSearchParams(window.location.search);
    const productId = params.get('id') || 'pearl-03'; // Если ID нет, показываем тоник №3 по умолчанию

    const product = productsDB[productId];
    if (!product) return;

    // Меняем данные на странице
    document.getElementById('prodMainImg').src = product.img;
    document.getElementById('prodThumbImg').src = product.img;
    titleEl.innerHTML = `${product.name1}<br><em>${product.name2}</em>`;
    document.getElementById('prodMainDesc').textContent = product.desc;
    
    // Меняем цены и объемы
    document.querySelectorAll('.js-dyn-price').forEach(el => el.textContent = `${product.price} BYN`);
    document.querySelectorAll('.js-dyn-size').forEach(el => el.textContent = product.size);
    document.getElementById('prodStickyName').textContent = `${product.name1} ${product.name2}`;

    // Обновляем кнопки корзины и избранного, чтобы они добавляли правильный товар!
    document.querySelectorAll('.js-add-to-cart').forEach(btn => {
        btn.dataset.id = productId;
        btn.dataset.name = `${product.name1} ${product.name2}`;
        btn.dataset.price = product.price;
        btn.dataset.size = product.size;
    });
    
    document.querySelectorAll('.js-bookmark').forEach(btn => {
        btn.dataset.id = productId;
        btn.dataset.name = `${product.name1} ${product.name2}`;
    });
}

// Запускаем при загрузке
document.addEventListener('DOMContentLoaded', renderProductPage);
});
