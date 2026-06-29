/* ═══════════════════════════════════════════════════════════════
   TSOK — animations.js
   Только визуальные эффекты: reveal на скролле (ПК + телефон),
   авто-каскад по соседям, мягкий параллакс на ключевых фото.
   Функционал (корзина/чекаут/фильтры) НЕ затрагивается.
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var REDUCE = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var SEL = '[data-reveal], .anim-fade-up, .anim-scale-up';

  function show(el) { el.classList.add('in', 'is-visible'); }

  /* каскад: соседние плашки появляются по очереди */
  function stagger() {
    document.querySelectorAll(SEL).forEach(function (el) {
      if (!el.parentNode) return;
      var sibs = Array.prototype.filter.call(el.parentNode.children, function (c) {
        return c.matches && c.matches(SEL);
      });
      var i = sibs.indexOf(el);
      if (i > 0) el.style.transitionDelay = Math.min(i * 80, 520) + 'ms';
    });
  }

  function reveal() {
    var nodes = document.querySelectorAll(SEL);
    if (REDUCE || !('IntersectionObserver' in window)) {
      Array.prototype.forEach.call(nodes, show);
      return;
    }
    stagger();
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { show(e.target); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });
    Array.prototype.forEach.call(nodes, function (n) { io.observe(n); });

    /* подстраховка: всё, что около экрана и не показалось — показать */
    window.addEventListener('load', function () {
      setTimeout(function () {
        document.querySelectorAll(SEL).forEach(function (el) {
          if (el.classList.contains('in') || el.classList.contains('is-visible')) return;
          if (el.getBoundingClientRect().top < window.innerHeight * 1.25) show(el);
        });
      }, 1600);
    });
  }

  /* мягкий параллакс — только десктоп, только ключевые изображения */
  function parallax() {
    if (REDUCE || window.innerWidth < 861) return;
    var sel = '.hero__frame img, .room__media img, .gift__media img, .founder-grid__img img, .ingredients__media img, .media-box img';
    var items = Array.prototype.slice.call(document.querySelectorAll(sel));
    if (!items.length) return;
    items.forEach(function (el) {
      el.style.willChange = 'transform';
      el.style.transition = 'transform .12s linear';
    });
    var ticking = false;
    function update() {
      var vh = window.innerHeight;
      items.forEach(function (el) {
        var r = el.getBoundingClientRect();
        var p = (r.top + r.height / 2 - vh / 2) / vh; // ~ -0.5 .. 0.5
        el.style.transform = 'translate3d(0,' + (p * -22).toFixed(1) + 'px,0) scale(1.06)';
      });
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { requestAnimationFrame(update); ticking = true; }
    }, { passive: true });
    update();
  }

  function init() { reveal(); parallax(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
