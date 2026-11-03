/* =========================================================
   NAGe — séquence d'ouverture ("intro")
   Autonome, sans dépendance. IIFE + classe publiée.
   ---------------------------------------------------------
   initNageIntro({ root?, wrapSelector?, logoSvgSelector?,
                   durationMs?, reducedMotion?, ondone? })
   → { play, destroy, ended }
   Événement : window dispatchEvent(new CustomEvent('nage:introend'))
   Anti-répétition : sessionStorage["nage_intro_played"]
   ========================================================= */
(function (global) {
  'use strict';

  var FLAG = 'nage_intro_played';
  var EASE_SPLIT = 'cubic-bezier(.76,0,.24,1)'; // accel + décél maîtrisées

  function q(root, sel) {
    if (!sel) return null;
    var sc = (root && root.querySelector) ? root : document;
    return sc.querySelector(sel);
  }

  function resolve(root, sel, fallback) {
    var el = q(root, sel);
    if (el) return el;
    return q(root, fallback);
  }

  /**
   * Resolve les 3 <g> cibles du SVG logo :
   * priorité aux attributs data-*, fallback sur les ids du prototype.
   */
  function resolveParts(svg) {
    if (!svg) return { halfL: null, halfR: null, word: null };
    return {
      halfL: svg.querySelector('[data-half="L"]') || svg.querySelector('#halfL'),
      halfR: svg.querySelector('[data-half="R"]') || svg.querySelector('#halfR'),
      word:  svg.querySelector('[data-word]')     || svg.querySelector('#wordmark'),
    };
  }

  function prefersReduced(explicit) {
    if (explicit === true) return true;
    if (explicit === false) return false;
    try {
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) { return false; }
  }

  function fireEnd(detail) {
    try {
      window.dispatchEvent(new CustomEvent('nage:introend', { detail: detail || {} }));
    } catch (e) {
      var ev;
      try { ev = document.createEvent('CustomEvent'); }
      catch (e2) { ev = document.createEvent('Event'); }
      ev.initCustomEvent('nage:introend', false, false, detail || {});
      window.dispatchEvent(ev);
    }
  }

  /* ---------------- décision : jouer ou pas ---------------- */
  function shouldPlay(opts) {
    if (opts._force) return true;
    if (opts.reducedMotion === true) return false;
    if (prefersReduced(false)) return false;
    try {
      if (sessionStorage.getItem(FLAG)) return false;
    } catch (e) { /* storage bloqué : on joue, on ne peut pas mémoïser */ }
    return true;
  }

  function markPlayed() {
    try { sessionStorage.setItem(FLAG, '1'); } catch (e) {}
  }

  /* ---------------- classe ---------------- */
  function NageIntro(options) {
    options = options || {};
    this._opts = Object.assign({
      root: null,               // scope de recherche (ex: document)
      wrapSelector: '.nage-intro-ui',
      durationMs: 2200,
      reducedMotion: undefined, // 'true' → skip ; 'false' → force ; undefined → matchMedia
      ondone: null,
    }, options);
    this.ended = false;
    this._overlay = null;
    this._anims = [];
  }

  NageIntro.prototype._mount = function () {
    if (this._overlay) return this._overlay;
    var o = document.createElement('div');
    o.className = 'nage-intro';
    o.setAttribute('role', 'img');
    o.setAttribute('aria-label', 'NAGe');
    o.innerHTML =
      '<div class="nage-intro-logo">' +
      '  <div class="nage-intro-logo-wrap"><!-- le logo SVG est injecté ici --></div>' +
      '</div>';
    document.body.appendChild(o);
    this._overlay = o;
    return o;
  };

  /**
   * Cherche le logo à cloner :
   *   1) wrapSelector ? [data-half] contenu
   *   2) fallback : tout <svg> contenant [data-half] ou #halfL
   */
  NageIntro.prototype._findLogoSvg = function () {
    var root = this._opts.root || document;
    var scope = root.querySelector ? root : document;
    // Prototype : ids connus
    var svg = scope.querySelector('#logoSvg') ||
              scope.querySelector('svg:has(#halfL)') ||
              scope.querySelector('svg:has(#halfR)') ||
              scope.querySelector('svg:has([data-half="L"])') ||
              scope.querySelector('svg:has([data-half="R"])');
    if (!svg) {
      // dernier recours : parcourir (sélecteur :has pas partout)
      var all = scope.querySelectorAll('svg');
      for (var i = 0; i < all.length; i++) {
        if (all[i].querySelector('[data-half], #halfL, #halfR')) { svg = all[i]; break; }
      }
    }
    return svg;
  };

  NageIntro.prototype._lockScroll = function () {
    var prev = {
      overflow: document.body.style.overflow,
      position: document.body.style.position,
    };
    document.body.style.overflow = 'hidden';
    return function restore() {
      document.body.style.overflow = prev.overflow;
      document.body.style.position = prev.position;
    };
  };

  NageIntro.prototype.play = function () {
    var o = this._opts;
    var self = this;
    var D = Math.max(200, +o.durationMs || 2200);

    /* pas d'intro du tout : UI visible immédiatement, fin non-bloquante */
    if (!shouldPlay(o)) {
      this._finish({ skipped: true });
      return this;
    }

    var svg = this._findLogoSvg();
    var overlay = this._mount();
    var host = overlay.querySelector('.nage-intro-logo-wrap');
    var target;

    if (svg) {
      target = svg.cloneNode(true);
      host.appendChild(target);
    }

    var parts  = resolveParts(target);
    var wrapEl = q(o.root, o.wrapSelector) ||
                 q(o.root, '.nage-intro-ui') ||
                 q(o.root, '.nage-app-root') ||
                 document.querySelector(o.wrapSelector || '.nage-intro-ui');
    // un host doit exister ; sinon on le crée vide pour garder la mécanique
    if (!wrapEl) {
      wrapEl = document.createElement('div');
      wrapEl.className = 'nage-intro-ui';
      (o.root && o.root.appendChild ? o.root.appendChild(wrapEl)
                                   : document.body.appendChild(wrapEl));
    }

    // verrou scroll pendant l'intro (rétabli automatiquement)
    var unlock = this._lockScroll();

    var isSkipped = !svg || (!parts.halfL && !parts.halfR);
    var phiA0 = 0.06, phiA1 = 0.50,
        phiB0 = 0.50, phiB1 = 0.62,
        phiC0 = 0.55, phiC1 = 1.00;

    var t = function (p) { return Math.max(0, Math.min(1, p)); };
    var KF = {};
    this._anims = [];

    /* ---------- Phase A : apparition + éclat ---------- */
    KF.logoIn = target.animate([
      { opacity: 0, transform: 'scale(.955)', offset: 0 },
      { opacity: 1, transform: 'scale(1)',    offset: t(phiA1 * 0.56) },
      { opacity: 1, transform: 'scale(1)',    offset: 1 },
    ], { duration: D * (phiA1 - phiA0) * 1.6, fill: 'both', easing: 'ease-out' });
    this._anims.push(KF.logoIn);

    var sheen = overlay.querySelector('.nage-intro-logo');
    if (sheen) {
      KF.sheen = sheen.animate([
        { opacity: 0, filter: 'brightness(1)' },
        { opacity: 1, filter: 'brightness(1.35)', offset: 0.22 },
        { opacity: 0.35, filter: 'brightness(1.05)', offset: 0.62 },
        { opacity: 0, filter: 'brightness(1)' },
      ], { duration: D * phiA1 * 1.3, fill: 'both', easing: 'ease-in-out' });
      this._anims.push(KF.sheen);
    }

    /* ---------- Phase B : mot qui s'estompe ---------- */
    if (parts.word) {
      KF.word = parts.word.animate([
        { opacity: 1, offset: 0 },
        { opacity: 1, offset: t(phiC0) },
        { opacity: 0, offset: t(phiB1) },
      ], { duration: D, fill: 'both', easing: EASE_SPLIT });
      this._anims.push(KF.word);
    }

    /* ---------- Phase B/C : halves partent horizontalement ---------- */
    if (parts.halfL && parts.halfR) {
      var travel = -1, dir = 1;
      KF.halfL = parts.halfL.animate([
        { transform: 'translateX(0%)',  opacity: 1, offset: 0 },
        { transform: 'translateX(-24%)', opacity: 1, offset: 0.42 },
        { transform: 'translateX(-140%)', opacity: 0.75, offset: 0.78 },
        { transform: 'translateX(-190%)', opacity: 0, offset: 1 },
      ], { duration: D, fill: 'both', easing: EASE_SPLIT });
      KF.halfR = parts.halfR.animate([
        { transform: 'translateX(0%)',  opacity: 1, offset: 0 },
        { transform: 'translateX(24%)',  opacity: 1, offset: 0.42 },
        { transform: 'translateX(140%)', opacity: 0.75, offset: 0.78 },
        { transform: 'translateX(190%)', opacity: 0, offset: 1 },
      ], { duration: D, fill: 'both', easing: EASE_SPLIT });
      this._anims.push(KF.halfL, KF.halfR);
    }

    /* ---------- Phase C : l'interface apparaît ---------- */
    // à 55% l'overlay ne bloque plus les clics
    setTimeout(function () {
      overlay.style.pointerEvents = 'none';
    }, D * phiC0);

    KF.ui = wrapEl.animate([
      { opacity: 0, transform: 'scale(.98)' },
      { opacity: 1, transform: 'scale(1)' },
    ], {
      duration: D * (phiC1 - phiC0) * 1.5,
      delay: D * phiC0,
      fill: 'both',
      easing: 'cubic-bezier(.22,1,.36,1)',
    });
    this._anims.push(KF.ui);

    wrapEl.classList.add('nage-intro-ui-hold');

    /* ---------- Fin : promesse + événement ---------- */
    var cleanup = function () {
      if (self.ended) return;
      self.ended = true;
      wrapEl.classList.add('nage-intro-ui-hold--in');
      setTimeout(function () {
        unlock();
        overlay.classList.add('nage-intro--fade');
        setTimeout(function () {
          overlay.remove();
          self._overlay = null;
          markPlayed();
          fireEnd({ durationMs: D, skipped: false });
          if (typeof o.ondone === 'function') o.ondone({ durationMs: D });
        }, 320);
      }, D * (1 - phiC0) * 0 // fires with animation end below instead
      );
    };

    var done = Promise.all(this._anims.map(function (a) {
      return new Promise(function (res) {
        a.addEventListener('finish', res, { once: true });
        a.addEventListener('cancel', res, { once: true });
      });
    }), );

    done.then(cleanup);
    // filet de sécurité si une animation ne finit pas (onglet figé)
    setTimeout(cleanup, D + 700);

    return this;
  };

  NageIntro.prototype._finish = function (info) {
    var o = this._opts;
    if (this.ended) return this;
    this.ended = true;
    var wrapEl = q(o.root, o.wrapSelector) ||
                 q(o.root, '.nage-intro-ui') ||
                 q(o.root, '.nage-app-root');
    if (wrapEl) {
      wrapEl.style.opacity = '1';
      wrapEl.style.transform = 'none';
      wrapEl.classList && wrapEl.classList.remove('nage-intro-ui-hold');
    }
    if (this._overlay) { this._overlay.remove(); this._overlay = null; }
    // non-bloquant : événement diffusé tout de suite, sans attendre
    fireEnd(Object.assign({ skipped: true }, info || {}));
    if (typeof o.ondone === 'function') o.ondone({ skipped: true });
    return this;
  };

  NageIntro.prototype.destroy = function () {
    this._anims.forEach(function (a) { try { a.cancel(); } catch (e) {} });
    this._anims.length = 0;
    if (this._overlay) { this._overlay.remove(); this._overlay = null; }
    return this;
  };

  /* ---------------- usine ---------------- */
  function initNageIntro(options) {
    var inst = new NageIntro(options);
    // auto-play par défaut ; renvoie l'instance pour (re)jouer
    if (options && options.autoPlay === false) return inst;
    return inst.play();
  }

  /* hook DOMContentLoaded automatique :
     si root/wrapSelector présent dans la page, on lance. */
  function autoBoot() {
    if (document.querySelector('.nage-intro-auto')) {
      initNageIntro({ root: document });
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoBoot, { once: true });
  } else {
    autoBoot();
  }

  global.initNageIntro = initNageIntro;
  global.NageIntro = NageIntro;
})(typeof window !== 'undefined' ? window : this);
