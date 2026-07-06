/* ============================================================
   TSOK.SHOP — MAIN SCRIPT
   ============================================================ */

'use strict';

/* ============================================================
   CART STATE
   ============================================================ */
let cart = JSON.parse(localStorage.getItem('tsok_cart') || '[]');
let favorites = JSON.parse(localStorage.getItem('tsok_favs') || '[]');
let boxMeta = JSON.parse(localStorage.getItem('tsok_box_meta') || 'null');

/* Нормализация пути к картинке: data-img хранится как 'img/Pearl3.jpg',
   но в корзине/чекауте/конструкторе рендерится напрямую и без /static/ даёт 404. */
function tsokImg(path) {
    if (!path) return '';
    if (/^(https?:|data:|\/)/.test(path)) return path;
    return '/static/' + path.replace(/^\/+/, '');
}

function saveCart() {
    localStorage.setItem('tsok_cart', JSON.stringify(cart));
    updateCartUI();
    renderCheckoutSummary();
}
function saveFavs() {
    localStorage.setItem('tsok_favs', JSON.stringify(favorites));
    updateFavUI();
}

function clearBoxMeta() {
    boxMeta = null;
    localStorage.removeItem('tsok_box_meta');
    localStorage.removeItem('tsok_box_state');
}

function boxMetaMatchesCart() {
    if (!boxMeta) return false;
    if (boxMeta.plan === 'test-3m') {
        return cart.length === 1 && cart[0]?.id === 'tsok-test-subscription-box-3m' && Number(cart[0]?.qty || 0) === 1;
    }
    const savedBoxState = JSON.parse(localStorage.getItem('tsok_box_state') || 'null');
    if (!savedBoxState?.items || typeof savedBoxState.items !== 'object') return false;
    const expected = Object.entries(savedBoxState.items)
        .filter(([, qty]) => Number(qty) > 0)
        .map(([id, qty]) => [id, Number(qty)])
        .sort(([a], [b]) => a.localeCompare(b));
    const actual = cart
        .filter(item => Number(item.qty || 0) > 0)
        .map(item => [item.id, Number(item.qty)])
        .sort(([a], [b]) => a.localeCompare(b));
    return expected.length === actual.length && expected.every(([id, qty], idx) => actual[idx]?.[0] === id && actual[idx]?.[1] === qty);
}

function ensureFreshBoxMeta() {
    if (boxMeta && !boxMetaMatchesCart()) clearBoxMeta();
}

function addToCart(id, name, price, size, brand, img) {
    clearBoxMeta();
    const existing = cart.find(i => i.id === id);
    if (existing) {
        existing.qty += 1;
    } else {
        cart.push({ id, name, price, size, brand, img, qty: 1 });
    }
    saveCart();
    showToast(`«${name}» добавлен в корзину`, 'cart');
}

function addTsokTestSubscriptionBox() {
    const testBox = {
        id: 'tsok-test-subscription-box-3m',
        name: 'TSOK TEST BOX 3M',
        price: 1,
        size: '3 месяца · тест оплаты',
        brand: 'TSOK BOX',
        img: '',
        qty: 1
    };
    cart = cart.filter(item => item.id !== testBox.id);
    cart.push(testBox);
    boxMeta = {
        plan: 'test-3m',
        plan_label: 'Тестовая подписка 3 месяца',
        item_count: 1,
        base_total: 3,
        total: 1,
        discount_percent: 0,
        delivery: 'Бесплатно',
        coins: '',
        bnpl: '',
        vip_gift: '',
        gift_note: '',
        bnpl_required: false,
        checkout_note: 'Тестовая TSOK BOX · 3 месяца · 1 ₽ сейчас, затем 1 ₽/мес · всего 3 ₽',
        constructor_url: 'subscription#constructor',
        is_test_subscription_box: true
    };
    localStorage.setItem('tsok_box_meta', JSON.stringify(boxMeta));
    localStorage.setItem('tsok_box_state', JSON.stringify({
        items: { [testBox.id]: 1 },
        plan: 'test-3m',
        vip_gift: '',
        updated_at: new Date().toISOString(),
        is_test_subscription_box: true
    }));
    saveCart();
    openCart();
    showToast('Тестовая подписка-бокс добавлена в корзину', 'cart');
}

window.addTsokTestSubscriptionBox = addTsokTestSubscriptionBox;

function removeFromCart(id) {
    cart = cart.filter(i => i.id !== id);
    saveCart();
    renderCartItems();
    renderCheckoutSummary();
}

function updateQty(id, delta) {
    const item = cart.find(i => i.id === id);
    if (!item) return;
    item.qty = Math.max(1, item.qty + delta);
    saveCart();
    renderCartItems();
    renderCheckoutSummary();
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
        el.textContent = sum.toFixed(0) + ' ₽';
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
                    ${item.img ? `<img src="${tsokImg(item.img)}" alt="${item.name}">` : ''}
                </div>
                <div class="cart-item__info">
                    <div class="cart-item__top">
                        <h4 class="cart-item__name">${item.name}</h4>
                        <span class="cart-item__price">${(item.price * item.qty).toFixed(0)} ₽</span>
                    </div>
                    <span class="cart-item__size">${item.size || ''}</span>
                    <div class="cart-item__controls">
                        <div class="qty-control">
                            <button onclick="updateQty('${item.id}', -1)" aria-label="Уменьшить">−</button>
                            <span class="cart-item__qty-val">${item.qty}</span>
                            <button onclick="updateQty('${item.id}', +1)" aria-label="Увеличить">+</button>
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
    renderCheckoutSummary();
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
    const revealEls = document.querySelectorAll('.anim-fade-up, .anim-scale-up');
    if (!revealEls.length) return;

    if (!('IntersectionObserver' in window)) {
        revealEls.forEach(el => el.classList.add('is-visible'));
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
    revealEls.forEach(el => obs.observe(el));
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
            if (priceLabel) priceLabel.textContent = max + ' ₽';
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
   CHECKOUT PVZ POINTS — YANDEX MAPS
   ============================================================ */
const pvzProviders = {
    cdek: {
        label: 'СДЭК',
        searchQuery: 'СДЭК пункт выдачи заказов',
        preset: 'islands#greenDotIcon',
    },
    yandex: {
        label: 'Яндекс Маркет',
        searchQuery: 'Яндекс Маркет пункт выдачи заказов',
        preset: 'islands#yellowDotIcon',
    },
    post: {
        label: 'Почта России',
        searchQuery: 'Почта России отделение',
        preset: 'islands#blueDotIcon',
    },
};

const pvzMapState = {
    map: null,
    collection: null,
    activeProvider: 'cdek',
    activeRequestId: 0,
};

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function setPvzHint(message) {
    const hint = document.getElementById('checkoutMapHint');
    if (hint) hint.textContent = message;
}


function saveSelectedPvz(provider, name = '', address = '', coords = []) {
    const providerInput = document.getElementById('deliveryPvzProvider');
    const nameInput = document.getElementById('deliveryPvzName');
    const addressInput = document.getElementById('deliveryPvzAddress');
    const coordsInput = document.getElementById('deliveryPvzCoordinates');
    const deliveryAddressInput = document.getElementById('deliveryAddress');

    if (providerInput) providerInput.value = provider;
    if (nameInput) nameInput.value = name;
    if (addressInput) addressInput.value = address;
    if (coordsInput) coordsInput.value = Array.isArray(coords) && coords.length === 2 ? coords.join(',') : '';
    if (address && deliveryAddressInput) deliveryAddressInput.value = address;
}

function getGeoObjectText(geoObject, fallback = '') {
    const geocoderMeta = geoObject.properties.get('metaDataProperty.GeocoderMetaData') || {};
    return geoObject.properties.get('name')
        || geocoderMeta.name
        || geocoderMeta.text
        || fallback;
}

function getGeoObjectAddress(geoObject) {
    if (typeof geoObject.getAddressLine === 'function') return geoObject.getAddressLine();
    const geocoderMeta = geoObject.properties.get('metaDataProperty.GeocoderMetaData') || {};
    return geocoderMeta.text || geoObject.properties.get('description') || '';
}

function showPvzError(provider) {
    const providerLabel = pvzProviders[provider]?.label || 'выбранной службы';
    setPvzHint(`Не удалось загрузить ПВЗ ${providerLabel}. Проверьте ключ Yandex Maps API или передвиньте карту.`);
}

function isPointInsideBounds(coords, bounds) {
    if (!Array.isArray(coords) || coords.length !== 2 || !Array.isArray(bounds) || bounds.length !== 2) return false;

    const [lat, lon] = coords;
    const latMin = Math.min(bounds[0][0], bounds[1][0]);
    const latMax = Math.max(bounds[0][0], bounds[1][0]);
    const lonMin = Math.min(bounds[0][1], bounds[1][1]);
    const lonMax = Math.max(bounds[0][1], bounds[1][1]);

    return lat >= latMin && lat <= latMax && lon >= lonMin && lon <= lonMax;
}

async function runYandexOrganizationSearch(query, bounds) {
    const objects = [];
    const pageSize = 20;

    for (let skip = 0; skip < 60 && objects.length < 20; skip += pageSize) {
        const searchResult = await ymaps.search(query, {
            boundedBy: bounds,
            strictBounds: true,
            results: pageSize,
            skip,
        });
        const geoObjects = searchResult.geoObjects;
        const count = geoObjects.getLength();

        if (!count) break;

        for (let index = 0; index < count && objects.length < 20; index += 1) {
            const geoObject = geoObjects.get(index);
            const coords = geoObject?.geometry?.getCoordinates?.();
            if (isPointInsideBounds(coords, bounds)) objects.push(geoObject);
        }
    }

    return objects;
}

function renderPvzPoints(provider) {
    if (!pvzProviders[provider]) return;

    pvzMapState.activeProvider = provider;
    saveSelectedPvz(provider);

    if (!pvzMapState.map || !pvzMapState.collection || !window.ymaps) {
        setPvzHint('Карта Яндекса загружается. Точки ПВЗ появятся автоматически после инициализации API.');
        return;
    }

    const requestId = ++pvzMapState.activeRequestId;
    const providerData = pvzProviders[provider];
    const bounds = pvzMapState.map.getBounds();
    pvzMapState.collection.removeAll();
    setPvzHint(`Ищем 20 точек ПВЗ ${providerData.label} в текущей области карты через API Яндекс Карт…`);

    runYandexOrganizationSearch(providerData.searchQuery, bounds)
        .then((geoObjects) => {
            if (!geoObjects || requestId !== pvzMapState.activeRequestId) return;

            const points = geoObjects.map((geoObject) => {
                const coords = geoObject.geometry.getCoordinates();
                if (!Array.isArray(coords) || coords.length !== 2) return null;
                return {
                    coords,
                    name: getGeoObjectText(geoObject, `${providerData.label} ПВЗ`),
                    address: getGeoObjectAddress(geoObject),
                };
            }).filter(Boolean).slice(0, 20);

            points.forEach((point, index) => {
                const placemark = new ymaps.Placemark(point.coords, {
                    iconCaption: String(index + 1),
                    balloonContentHeader: escapeHtml(point.name),
                    balloonContentBody: escapeHtml(point.address),
                    hintContent: escapeHtml(`${providerData.label}: ${point.address || point.name}`),
                }, {
                    preset: providerData.preset,
                    openBalloonOnClick: true,
                });

                placemark.events.add('click', () => {
                    saveSelectedPvz(provider, point.name, point.address, point.coords);
                    setPvzHint(`Выбран ПВЗ ${providerData.label}: ${point.address || point.name}.`);
                });

                pvzMapState.collection.add(placemark);
            });

            if (points.length) {
                setPvzHint(`Показано ${points.length} из 20 точек ПВЗ ${providerData.label} в текущей области карты. Нажмите на метку, чтобы выбрать пункт.`);
            } else {
                setPvzHint(`API Яндекс Карт не нашёл ПВЗ ${providerData.label} в текущей области карты. Передвиньте карту или измените масштаб.`);
            }
        })
        .catch(() => showPvzError(provider));
}

function initYandexPvzMap() {
    const mapContainer = document.getElementById('checkoutYandexMap');
    if (!mapContainer) return;

    if (!window.ymaps) {
        setPvzHint('Для загрузки карты укажите YANDEX_MAPS_API_KEY: сейчас API Яндекс Карт не подключён.');
        return;
    }

    ymaps.ready(() => {
        pvzMapState.map = new ymaps.Map(mapContainer, {
            center: [55.755864, 37.617698],
            zoom: 11,
            controls: ['zoomControl', 'geolocationControl', 'fullscreenControl'],
        });
        pvzMapState.collection = new ymaps.GeoObjectCollection();
        pvzMapState.map.geoObjects.add(pvzMapState.collection);
        renderPvzPoints(pvzMapState.activeProvider);
    });
}

function initPvzSelector() {
    const buttons = document.querySelectorAll('[data-pvz-provider]');
    if (!buttons.length) return;

    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(item => item.classList.toggle('is-active', item === btn));
            renderPvzPoints(btn.dataset.pvzProvider);
        });
    });

    const activeProvider = document.querySelector('[data-pvz-provider].is-active')?.dataset.pvzProvider || buttons[0].dataset.pvzProvider;
    pvzMapState.activeProvider = activeProvider;
    initYandexPvzMap();
}

/* ============================================================
   CHECKOUT PAGE
   ============================================================ */
function cartSubtotal() {
    return cart.reduce((sum, item) => sum + item.qty * item.price, 0);
}

function renderCheckoutSummary() {
    ensureFreshBoxMeta();
    const container = document.getElementById('checkoutSummaryItems');
    const totalEl = document.getElementById('checkoutSummaryTotal');
    const emptyEl = document.getElementById('checkoutEmptyMessage');
    const submitBtn = document.getElementById('checkoutSubmitBtn');
    if (!container && !totalEl && !submitBtn) return;

    const total = cartSubtotal();
    if (totalEl) totalEl.textContent = `${total.toFixed(0)} ₽`;
    const boxNote = document.getElementById('checkoutBoxNote');
    if (boxNote) {
        boxNote.hidden = true;
        boxNote.textContent = '';
    }
    if (submitBtn) {
        submitBtn.textContent = cart.length ? `Купить за ${total.toFixed(0)} ₽` : 'Купить';
        submitBtn.disabled = cart.length === 0;
    }
    if (!container) return;

    container.innerHTML = '';
    if (!cart.length) {
        if (emptyEl) emptyEl.style.display = '';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';
    cart.forEach(item => {
        const el = document.createElement('div');
        el.className = 'checkout-summary-item';
        el.innerHTML = `
            <div class="checkout-summary-item__img">${item.img ? `<img src="${tsokImg(item.img)}" alt="${item.name}">` : ''}</div>
            <div>
                <div class="checkout-summary-item__name">${item.name}</div>
                <span class="checkout-summary-item__meta">${item.brand || ''}${item.size ? ' · ' + item.size : ''} · ${item.qty} шт.</span>
            </div>
            <div class="checkout-summary-item__price">${(item.price * item.qty).toFixed(0)} ₽</div>`;
        container.appendChild(el);
    });
}

function initCheckoutPage() {
    const form = document.getElementById('checkoutForm');
    if (!form) return;

    const errorEl = document.getElementById('checkoutError');
    const submitBtn = document.getElementById('checkoutSubmitBtn');
    const editCartBtn = document.getElementById('checkoutEditCartBtn');
    const successNotice = document.getElementById('paymentSuccessNotice');

    const paymentSucceeded = successNotice && getComputedStyle(successNotice).display !== 'none' && successNotice.textContent.trim();
    if (paymentSucceeded) {
        cart = [];
        localStorage.removeItem('tsok_cart');
        localStorage.removeItem('tsok_box_meta');
        localStorage.removeItem('tsok_box_state');
        boxMeta = null;
        updateCartUI();
    }

    const savedCustomerProfile = JSON.parse(localStorage.getItem('tsok_customer_profile') || 'null');
    if (savedCustomerProfile) {
        const fioInput = document.getElementById('customerFio');
        const phoneInput = document.getElementById('customerPhone');
        const emailInput = document.getElementById('customerEmail');
        if (fioInput && !fioInput.value) fioInput.value = savedCustomerProfile.name || '';
        if (phoneInput && !phoneInput.value) phoneInput.value = savedCustomerProfile.phone || '';
        if (emailInput && !emailInput.value) emailInput.value = savedCustomerProfile.email || '';
    }

    ensureFreshBoxMeta();
    if (editCartBtn && boxMeta) editCartBtn.textContent = 'Редактировать бокс';

    editCartBtn?.addEventListener('click', () => {
        if (boxMeta) {
            window.location.href = boxMeta.constructor_url || 'subscription#constructor';
            return;
        }
        openCart();
    });
    renderCheckoutSummary();

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!cart.length) {
            openCart();
            return;
        }
        if (errorEl) errorEl.hidden = true;
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Создаём платёж…';
        }

        ensureFreshBoxMeta();

        const payload = {
            items: cart.map(item => ({ id: item.id, qty: item.qty })),
            box: boxMeta ? { plan: boxMeta.plan, vip_gift: boxMeta.vip_gift } : null,
            customer: {
                fio: document.getElementById('customerFio')?.value.trim() || '',
                phone: document.getElementById('customerPhone')?.value.trim() || '',
                email: document.getElementById('customerEmail')?.value.trim() || '',
            },
            delivery: {
                city: document.getElementById('deliveryCity')?.value.trim() || '',
                address: document.getElementById('deliveryAddress')?.value.trim() || '',
                comment: document.getElementById('deliveryComment')?.value.trim() || '',
                pvz_provider: document.getElementById('deliveryPvzProvider')?.value || '',
                pvz_name: document.getElementById('deliveryPvzName')?.value || '',
                pvz_address: document.getElementById('deliveryPvzAddress')?.value || '',
                pvz_coordinates: document.getElementById('deliveryPvzCoordinates')?.value || '',
            },
        };

        try {
            const response = await fetch('/api/yookassa/create-payment', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Не удалось создать платёж.');
            if (!data.confirmation_url) throw new Error('ЮKassa не вернула ссылку на оплату.');
            window.location.href = data.confirmation_url;
        } catch (error) {
            if (errorEl) {
                errorEl.textContent = error.message || 'Ошибка оформления заказа.';
                errorEl.hidden = false;
            }
            showToast(error.message || 'Ошибка оформления заказа');
            renderCheckoutSummary();
        }
    });
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
    initCheckoutPage();
    initPvzSelector();

    // Initial UI sync
    updateCartUI();
    updateFavUI();
    renderCartItems();
    renderCheckoutSummary();
});
