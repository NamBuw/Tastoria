(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var ASSET_VER = 'editorial-v24';

  var motionMql = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

  function prefersReducedMotion() {
    return Boolean(motionMql && motionMql.matches);
  }

  // 1. Light-Only Vintage Broadsheet Device Screenshot Sync
  var themeMeta = document.getElementById('theme-color-meta');
  var previewImg = document.getElementById('device-preview-img');

  function syncDeviceImg() {
    if (!previewImg) return;
    var screen = previewImg.getAttribute('data-screen') || 'quet';
    previewImg.setAttribute('src', '/gioi-thieu/img/' + screen + '-light.webp?v=' + ASSET_VER);
  }

  if (themeMeta) themeMeta.setAttribute('content', '#E3CFA6');
  syncDeviceImg();

  // 2. Sticky Editorial Masthead & Mobile Drawer
  var headerEl = document.getElementById('site-header');
  var sentinelEl = document.getElementById('top-sentinel');
  if (headerEl && sentinelEl && 'IntersectionObserver' in window) {
    var headerObs = new IntersectionObserver(function (entries) {
      headerEl.classList.toggle('is-scrolled', !entries[0].isIntersecting);
    });
    headerObs.observe(sentinelEl);
  }

  var menuToggle = document.getElementById('mobile-menu-toggle');
  var drawer = document.getElementById('mobile-drawer');
  var drawerCloseTimer = null;

  function setDrawerOpen(open) {
    if (!menuToggle || !drawer) return;
    if (drawerCloseTimer !== null) {
      window.clearTimeout(drawerCloseTimer);
      drawerCloseTimer = null;
    }

    menuToggle.setAttribute('aria-expanded', String(open));
    menuToggle.setAttribute('aria-label', open ? 'Đóng mục lục điều hướng' : 'Mở mục lục điều hướng');
    menuToggle.classList.toggle('is-open', open);

    if (open) {
      drawer.removeAttribute('hidden');
      document.body.classList.add('no-scroll');
      if (prefersReducedMotion()) {
        drawer.classList.add('is-open');
      } else {
        window.requestAnimationFrame(function () {
          window.requestAnimationFrame(function () {
            drawer.classList.add('is-open');
          });
        });
      }
    } else {
      drawer.classList.remove('is-open');
      document.body.classList.remove('no-scroll');
      if (prefersReducedMotion()) {
        drawer.setAttribute('hidden', '');
      } else {
        drawerCloseTimer = window.setTimeout(function () {
          if (menuToggle.getAttribute('aria-expanded') !== 'true') {
            drawer.setAttribute('hidden', '');
          }
          drawerCloseTimer = null;
        }, 360);
      }
    }
  }

  if (menuToggle && drawer) {
    menuToggle.addEventListener('click', function () {
      setDrawerOpen(menuToggle.getAttribute('aria-expanded') !== 'true');
    });
    drawer.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        setDrawerOpen(false);
      });
    });
    drawer.querySelectorAll('[data-drawer-close]').forEach(function (closeBtn) {
      closeBtn.addEventListener('click', function () {
        setDrawerOpen(false);
        menuToggle.focus();
      });
    });
    document.addEventListener('keydown', function (evt) {
      if (evt.key === 'Escape' && menuToggle.getAttribute('aria-expanded') === 'true') {
        setDrawerOpen(false);
        menuToggle.focus();
      }
    });
  }

  // 3. Section Scroll Reveals (IntersectionObserver, single pass)
  var revealNodes = Array.from(document.querySelectorAll('[data-reveal]'));
  function revealAllImmediately() {
    revealNodes.forEach(function (el) {
      el.classList.add('is-visible');
    });
  }

  if (revealNodes.length > 0) {
    if (prefersReducedMotion() || !('IntersectionObserver' in window)) {
      revealAllImmediately();
    } else {
      var revealObs = new IntersectionObserver(function (entries, observer) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.1, rootMargin: '0px 0px -32px 0px' });

      revealNodes.forEach(function (node) {
        revealObs.observe(node);
      });
    }
  }

  // 4. Tagline Word-by-Word Scroll Reveal
  var taglineRoot = document.getElementById('tagline-reveal');
  var taglineWords = [];
  var maxRevealedWordIdx = -1;

  function activateAllTaglineWords() {
    taglineWords.forEach(function (wordSpan) {
      wordSpan.classList.add('is-active');
    });
    maxRevealedWordIdx = taglineWords.length - 1;
  }

  if (taglineRoot) {
    var lineEls = Array.from(taglineRoot.querySelectorAll('[data-tagline-line]'));
    lineEls.forEach(function (lineEl) {
      var raw = (lineEl.textContent || '').trim();
      if (!raw) return;
      var parts = raw.split(/\s+/);
      var frag = document.createDocumentFragment();
      parts.forEach(function (word, idx) {
        if (idx > 0) frag.appendChild(document.createTextNode(' '));
        var span = document.createElement('span');
        span.className = 'tagline-word';
        span.textContent = word;
        taglineWords.push(span);
        frag.appendChild(span);
      });
      lineEl.replaceChildren(frag);
    });

    if (taglineWords.length > 0) {
      if (prefersReducedMotion() || !('IntersectionObserver' in window)) {
        activateAllTaglineWords();
      } else {
        var taglineTicking = false;
        var taglineScrollBound = false;

        function updateTaglineReveal() {
          taglineTicking = false;
          if (!taglineRoot) return;
          var rect = taglineRoot.getBoundingClientRect();
          var vh = window.innerHeight || document.documentElement.clientHeight || 800;
          var progress = (vh * 0.85 - rect.top) / Math.max(1, rect.height * 0.72);
          if (progress < 0) progress = 0;
          if (progress > 1) progress = 1;
          var targetIdx = Math.floor(progress * taglineWords.length) - 1;
          if (rect.top <= vh * 0.35) targetIdx = taglineWords.length - 1;
          if (targetIdx > maxRevealedWordIdx) {
            maxRevealedWordIdx = Math.min(targetIdx, taglineWords.length - 1);
            for (var i = 0; i <= maxRevealedWordIdx; i += 1) {
              taglineWords[i].classList.add('is-active');
            }
          }
          if (maxRevealedWordIdx >= taglineWords.length - 1 && taglineScrollBound) {
            window.removeEventListener('scroll', onTaglineScroll);
            taglineScrollBound = false;
          }
        }

        function onTaglineScroll() {
          if (!taglineTicking) {
            taglineTicking = true;
            window.requestAnimationFrame(updateTaglineReveal);
          }
        }

        var taglineObs = new IntersectionObserver(function (entries) {
          var entry = entries[0];
          if (!entry) return;
          if (entry.isIntersecting) {
            updateTaglineReveal();
            if (!taglineScrollBound && maxRevealedWordIdx < taglineWords.length - 1) {
              window.addEventListener('scroll', onTaglineScroll, { passive: true });
              taglineScrollBound = true;
            }
          } else if (taglineScrollBound) {
            window.removeEventListener('scroll', onTaglineScroll);
            taglineScrollBound = false;
          }
        }, { threshold: 0.05 });

        taglineObs.observe(taglineRoot);
      }
    }
  }

  if (motionMql && typeof motionMql.addEventListener === 'function') {
    motionMql.addEventListener('change', function () {
      if (prefersReducedMotion()) {
        revealAllImmediately();
        activateAllTaglineWords();
      }
    });
  }

  // 5. Dual-Mode Interactive Workbench (#can-bep)
  var wbTabs = Array.from(document.querySelectorAll('[data-wb-mode]'));
  var wbCalPanel = document.getElementById('wb-panel-calorie');
  var wbTrayPanel = document.getElementById('wb-panel-tray');

  function selectWorkbenchMode(modeKey, moveFocus) {
    wbTabs.forEach(function (tab) {
      var active = tab.getAttribute('data-wb-mode') === modeKey;
      tab.setAttribute('aria-selected', String(active));
      tab.setAttribute('tabindex', active ? '0' : '-1');
      if (active && moveFocus) tab.focus();
    });
    if (wbCalPanel) {
      if (modeKey === 'calorie') wbCalPanel.removeAttribute('hidden');
      else wbCalPanel.setAttribute('hidden', '');
    }
    if (wbTrayPanel) {
      if (modeKey === 'tray') wbTrayPanel.removeAttribute('hidden');
      else wbTrayPanel.setAttribute('hidden', '');
    }
  }

  wbTabs.forEach(function (tab, idx) {
    tab.addEventListener('click', function () {
      selectWorkbenchMode(tab.getAttribute('data-wb-mode'), false);
    });
    tab.addEventListener('keydown', function (evt) {
      var next = idx;
      if (evt.key === 'ArrowRight' || evt.key === 'ArrowDown') next = (idx + 1) % wbTabs.length;
      else if (evt.key === 'ArrowLeft' || evt.key === 'ArrowUp') next = (idx - 1 + wbTabs.length) % wbTabs.length;
      else if (evt.key === 'Home') next = 0;
      else if (evt.key === 'End') next = wbTabs.length - 1;
      else return;
      evt.preventDefault();
      selectWorkbenchMode(wbTabs[next].getAttribute('data-wb-mode'), true);
    });
  });

  // 5A. Tab 1: Vietnamese Dish Calorie, Macro Pie Chart & Nutrition Facts Ledger
  var CALC_PORTIONS = {
    nho: { scale: 0.75, label: 'Phần nhỏ (0.75×)', word: 'nhỏ' },
    vua: { scale: 1.0, label: 'Phần vừa (1.0×)', word: 'vừa' },
    lon: { scale: 1.35, label: 'Phần lớn (1.35×)', word: 'lớn' }
  };

  var CALC_MODIFIERS = {
    mo_hanh: { label: 'Thêm mỡ hành (+80 kcal)', kcal: 80, protein_g: 0.1, carbs_g: 0.2, fat_g: 9.0, fiber_g: 0.0, grams: 15 },
    nuoc_mam: { label: 'Chan nước mắm pha (+45 kcal)', kcal: 45, protein_g: 0.8, carbs_g: 10.0, fat_g: 0.0, fiber_g: 0.0, grams: 45 },
    it_tinh_bot: { label: 'Ít cơm hoặc ít bún (giảm 95 kcal)', kcal: -95, protein_g: -1.7, carbs_g: -22.0, fat_g: -0.2, fiber_g: -0.3, grams: -75 }
  };

  var CALC_DISHES = {
    bun_thit_nuong: {
      id: 'bun_thit_nuong',
      name: 'Bún thịt nướng chả giò',
      servingUnit: '1 tô',
      servingGrams: 420,
      kcal: 467,
      protein_g: 25.0,
      carbs_g: 58.0,
      fat_g: 15.0,
      fiber_g: 3.2,
      hw: 0.20,
      provenance: 'Tham chiếu Viện Dinh dưỡng Quốc gia',
      photo: '/gioi-thieu/img/bun-thit-nuong.webp?v=' + ASSET_VER,
      alt: 'Tô bún thịt nướng chả giò kèm rau tía tô, dưa leo và đồ chua',
      allowedMods: ['mo_hanh', 'nuoc_mam', 'it_tinh_bot'],
      note: 'Chén nước mắm pha ngọt và mỡ hành tăng thêm 125 kcal nếu chan hết vào tô.'
    },
    pho: {
      id: 'pho',
      name: 'Phở bò tái nạm',
      servingUnit: '1 tô',
      servingGrams: 520,
      kcal: 444,
      protein_g: 26.0,
      carbs_g: 58.0,
      fat_g: 12.0,
      fiber_g: 1.8,
      hw: 0.20,
      provenance: 'Tham chiếu Viện Dinh dưỡng Quốc gia',
      photo: '/gioi-thieu/img/beef-pho.webp?v=' + ASSET_VER,
      alt: 'Tô phở bò tái nạm với nước dùng trong, bò viên, giá đỗ và hành lá',
      allowedMods: ['mo_hanh', 'it_tinh_bot'],
      note: 'Chọn cỡ tô và giảm bánh phở giúp kiểm soát nhanh lượng tinh bột trong bữa sáng.'
    },
    dau_phu_non: {
      id: 'dau_phu_non',
      name: 'Đậu phụ non chần hành gừng',
      servingUnit: '1 phần',
      servingGrams: 150,
      kcal: 95,
      protein_g: 8.5,
      carbs_g: 2.2,
      fat_g: 5.5,
      fiber_g: 0.4,
      hw: 0.20,
      provenance: 'Tham chiếu USDA và Viện Dinh dưỡng Quốc gia',
      photo: '/gioi-thieu/img/silken-tofu.webp?v=' + ASSET_VER,
      alt: 'Đậu phụ non chần rưới sốt xì dầu, hành lá và mè rang',
      allowedMods: ['mo_hanh', 'nuoc_mam'],
      note: 'Đậu phụ non chần chỉ khoảng 95 kcal; thêm mỡ hành và nước chấm có thể tăng hơn gấp đôi.'
    },
    ca_kho_to: {
      id: 'ca_kho_to',
      name: 'Cá kho tộ',
      servingUnit: '1 phần',
      servingGrams: 140,
      kcal: 152,
      protein_g: 17.3,
      carbs_g: 7.7,
      fat_g: 5.8,
      fiber_g: 0.3,
      hw: 0.20,
      provenance: 'Tham chiếu bảng thực phẩm Việt Nam',
      photo: '/gioi-thieu/img/caramel-trout.webp?v=' + ASSET_VER,
      alt: 'Đĩa cá kho tộ màu cánh gián rắc hành lá và ngò rí',
      allowedMods: ['mo_hanh', 'nuoc_mam'],
      note: 'Món kho đậm đạm ít béo; ăn kèm đĩa rau luộc để bù chất xơ cho bữa cơm gia đình.'
    }
  };

  var calState = {
    dishId: 'bun_thit_nuong',
    portionKey: 'vua',
    activeMods: new Set()
  };

  var calDishBtns = Array.from(document.querySelectorAll('[data-cal-dish]'));
  var calScaleBtns = Array.from(document.querySelectorAll('[data-cal-scale]'));
  var calModBtns = Array.from(document.querySelectorAll('[data-cal-mod]'));

  function largestRemainderPercentages(values) {
    var total = values.reduce(function (acc, v) { return acc + Math.max(0, v); }, 0);
    if (total <= 0) return values.map(function (_, idx) { return idx === 0 ? 100 : 0; });
    var exact = values.map(function (v) { return (Math.max(0, v) / total) * 100; });
    var floors = exact.map(function (x) { return Math.floor(x); });
    var remainders = exact.map(function (x, i) { return { i: i, r: x - floors[i] }; });
    var left = 100 - floors.reduce(function (a, b) { return a + b; }, 0);
    remainders.sort(function (a, b) { return b.r - a.r; });
    for (var k = 0; k < left; k += 1) {
      floors[remainders[k].i] += 1;
    }
    return floors;
  }

  function renderMacroPieSvg(svgEl, segments, totalKcal) {
    if (!svgEl) return;
    var r = 42;
    var c = 2 * Math.PI * r;
    var nonZeroCount = segments.filter(function (s) { return s.pct > 0; }).length;
    var gap = nonZeroCount > 1 ? 1.5 : 0;
    var nodes = [];

    var outerRing = document.createElementNS(SVG_NS, 'circle');
    outerRing.setAttribute('class', 'pie-hairline-ring');
    outerRing.setAttribute('cx', '60');
    outerRing.setAttribute('cy', '60');
    outerRing.setAttribute('r', '52');
    nodes.push(outerRing);

    var trackRing = document.createElementNS(SVG_NS, 'circle');
    trackRing.setAttribute('class', 'pie-track-ring');
    trackRing.setAttribute('cx', '60');
    trackRing.setAttribute('cy', '60');
    trackRing.setAttribute('r', String(r));
    nodes.push(trackRing);

    var cumulative = 0;
    segments.forEach(function (seg) {
      if (seg.pct <= 0) return;
      var rawLen = (seg.pct / 100) * c;
      var drawLen = Math.max(0.5, rawLen - gap);
      var circle = document.createElementNS(SVG_NS, 'circle');
      circle.setAttribute('class', seg.className);
      circle.setAttribute('cx', '60');
      circle.setAttribute('cy', '60');
      circle.setAttribute('r', String(r));
      circle.setAttribute('stroke-dasharray', drawLen.toFixed(2) + ' ' + c.toFixed(2));
      circle.setAttribute('stroke-dashoffset', (-cumulative).toFixed(2));
      circle.setAttribute('transform', 'rotate(-90 60 60)');
      nodes.push(circle);
      cumulative += rawLen;
    });

    var innerRing = document.createElementNS(SVG_NS, 'circle');
    innerRing.setAttribute('class', 'pie-hairline-ring');
    innerRing.setAttribute('cx', '60');
    innerRing.setAttribute('cy', '60');
    innerRing.setAttribute('r', '32');
    nodes.push(innerRing);

    var valText = document.createElementNS(SVG_NS, 'text');
    valText.setAttribute('class', 'pie-center-kcal');
    valText.setAttribute('x', '60');
    valText.setAttribute('y', '58');
    valText.setAttribute('text-anchor', 'middle');
    valText.textContent = String(totalKcal);
    nodes.push(valText);

    var unitText = document.createElementNS(SVG_NS, 'text');
    unitText.setAttribute('class', 'pie-center-unit');
    unitText.setAttribute('x', '60');
    unitText.setAttribute('y', '72');
    unitText.setAttribute('text-anchor', 'middle');
    unitText.textContent = 'kcal';
    nodes.push(unitText);

    svgEl.replaceChildren.apply(svgEl, nodes);
  }

  function renderCalorieWorkbench() {
    var dish = CALC_DISHES[calState.dishId] || CALC_DISHES.bun_thit_nuong;
    var portion = CALC_PORTIONS[calState.portionKey] || CALC_PORTIONS.vua;
    if (!document.getElementById('cal-range-text')) return;

    calDishBtns.forEach(function (btn) {
      btn.setAttribute('aria-pressed', String(btn.getAttribute('data-cal-dish') === dish.id));
    });
    calScaleBtns.forEach(function (btn) {
      btn.setAttribute('aria-pressed', String(btn.getAttribute('data-cal-scale') === calState.portionKey));
    });

    var appliedLabels = [];
    var kcal = dish.kcal * portion.scale;
    var protein = dish.protein_g * portion.scale;
    var carbs = dish.carbs_g * portion.scale;
    var fat = dish.fat_g * portion.scale;
    var fiber = dish.fiber_g * portion.scale;
    var effectiveGrams = dish.servingGrams * portion.scale;

    calModBtns.forEach(function (btn) {
      var modKey = btn.getAttribute('data-cal-mod');
      var allowed = dish.allowedMods.indexOf(modKey) !== -1;
      if (!allowed) {
        calState.activeMods.delete(modKey);
        btn.disabled = true;
        btn.setAttribute('aria-pressed', 'false');
        return;
      }
      btn.disabled = false;
      var active = calState.activeMods.has(modKey);
      btn.setAttribute('aria-pressed', String(active));
      if (active && CALC_MODIFIERS[modKey]) {
        var mod = CALC_MODIFIERS[modKey];
        kcal += mod.kcal;
        protein += mod.protein_g;
        carbs += mod.carbs_g;
        fat += mod.fat_g;
        fiber += mod.fiber_g;
        effectiveGrams += mod.grams;
        appliedLabels.push(mod.label);
      }
    });

    kcal = Math.max(40, Math.round(kcal));
    protein = Math.max(0, protein);
    carbs = Math.max(0, carbs);
    fat = Math.max(0, fat);
    fiber = Math.max(0, fiber);
    effectiveGrams = Math.max(50, Math.round(effectiveGrams));

    var low = Math.round(Math.max(20, kcal * (1 - dish.hw)));
    var high = Math.round(kcal * (1 + dish.hw));
    var density = Math.round((kcal / effectiveGrams) * 100);
    var densityLabel = density < 120 ? 'Nhẹ bụng' : (density <= 200 ? 'Vừa năng lượng' : 'Đậm năng lượng');

    var cKcal = carbs * 4;
    var pKcal = protein * 4;
    var fKcal = fat * 9;
    var shares = largestRemainderPercentages([cKcal, pKcal, fKcal]);
    var cPct = shares[0];
    var pPct = shares[1];
    var fPct = shares[2];

    var fiberDvPct = Math.min(100, Math.round((fiber / 25) * 100));
    var amdrOk = (cPct >= 45 && cPct <= 65) && (pPct >= 15 && pPct <= 25) && (fPct >= 20 && fPct <= 30);
    var insight = '';
    if (fPct > 35) {
      insight = 'Chất béo chiếm ' + fPct + '% năng lượng; bỏ bớt mỡ hành hoặc phần da mỡ giúp giảm nhanh chất béo bão hòa.';
    } else if (fPct > 30) {
      insight = 'Chất béo ở mức ' + fPct + '% (nhỉnh hơn mức khuyến nghị 20 đến 30%); giảm nhẹ mỡ hành hoặc nước béo giúp bữa ăn nhẹ bụng hơn.';
    } else if (cPct > 65) {
      insight = 'Tinh bột chiếm ' + cPct + '% năng lượng; giảm bớt cơm hoặc bún và thêm rau luộc giúp giữ đường huyết ổn định.';
    } else if (cPct < 45 && pPct > 25) {
      insight = 'Món giàu đạm (' + pPct + '%) và ít tinh bột (' + cPct + '%); nên ăn kèm thêm cơm hoặc bún và rau xanh để đủ năng lượng.';
    } else if (cPct < 45) {
      insight = 'Tinh bột ở mức ' + cPct + '% (thấp hơn mức khuyến nghị 45 đến 65%); có thể thêm một chén cơm nhỏ hoặc bún cùng rau xanh để bền sức.';
    } else if (pPct > 25) {
      insight = 'Chất đạm chiếm ' + pPct + '% (cao hơn mức khuyến nghị 15 đến 25%); ăn kèm thêm rau xanh hoặc ít cơm giúp bữa ăn hài hòa hơn.';
    } else if (pPct < 15) {
      insight = 'Chất đạm chỉ đạt ' + pPct + '% (thấp hơn mức khuyến nghị 15 đến 25%); bổ sung thêm thịt nạc, cá, trứng hoặc đậu phụ để đủ đạm.';
    } else if (fPct < 20) {
      insight = 'Chất béo ở mức ' + fPct + '% (thấp hơn mức khuyến nghị 20 đến 30%); thêm một thìa dầu thực vật hoặc lạc rang giúp hấp thu vitamin tốt hơn.';
    } else if (fiber < 3.0) {
      insight = 'Tỷ lệ đạm và chất béo cân đối, nhưng chất xơ còn thấp (' + fiber.toFixed(1) + 'g); thêm đĩa rau xanh để đủ no lâu.';
    } else {
      insight = 'Tỷ lệ Tinh bột, Đạm và Béo nằm trong ngưỡng khuyến nghị của Viện Dinh dưỡng Quốc gia (45 đến 65%, 15 đến 25%, 20 đến 30%).';
    }

    var photoEl = document.getElementById('cal-dish-photo');
    var provEl = document.getElementById('cal-provenance');
    var servEl = document.getElementById('cal-serving-desc');
    var titleEl = document.getElementById('cal-dish-title');
    var rangeEl = document.getElementById('cal-range-text');
    var densityEl = document.getElementById('cal-density-text');
    var pointEl = document.getElementById('cal-point-text');
    var pieEl = document.getElementById('cal-macro-pie');

    var cEl = document.getElementById('cal-carbs');
    var cKcalEl = document.getElementById('cal-carbs-kcal');
    var cPctEl = document.getElementById('cal-carbs-pct');
    var pEl = document.getElementById('cal-protein');
    var pKcalEl = document.getElementById('cal-protein-kcal');
    var pPctEl = document.getElementById('cal-protein-pct');
    var fEl = document.getElementById('cal-fat');
    var fKcalEl = document.getElementById('cal-fat-kcal');
    var fPctEl = document.getElementById('cal-fat-pct');

    var fibEl = document.getElementById('cal-fiber');
    var fibDvEl = document.getElementById('cal-fiber-dv');
    var fibBarEl = document.getElementById('cal-fiber-bar');
    var fibNoteEl = document.getElementById('cal-fiber-note');
    var amdrStatusEl = document.getElementById('cal-amdr-status');
    var amdrInsightEl = document.getElementById('cal-amdr-insight');
    var modSumEl = document.getElementById('cal-mod-summary');
    var noteEl = document.getElementById('cal-disambig-note');

    if (photoEl) {
      photoEl.setAttribute('src', dish.photo);
      photoEl.setAttribute('alt', dish.alt);
    }
    if (provEl) provEl.textContent = dish.provenance;
    if (servEl) servEl.textContent = dish.servingUnit + ' ' + portion.word + ' (~' + effectiveGrams + 'g)';
    if (titleEl) titleEl.textContent = dish.name;
    if (rangeEl) rangeEl.textContent = low + ' đến ' + high + ' kcal';
    if (densityEl) densityEl.textContent = density + ' kcal/100g, ' + densityLabel.toLowerCase();
    if (pointEl) pointEl.textContent = 'Mức trung vị ' + kcal + ' kcal, đã tính ' + portion.label;

    if (cEl) cEl.textContent = carbs.toFixed(1) + 'g';
    if (cKcalEl) cKcalEl.textContent = Math.round(cKcal) + ' kcal';
    if (cPctEl) cPctEl.textContent = cPct + '%';

    if (pEl) pEl.textContent = protein.toFixed(1) + 'g';
    if (pKcalEl) pKcalEl.textContent = Math.round(pKcal) + ' kcal';
    if (pPctEl) pPctEl.textContent = pPct + '%';

    if (fEl) fEl.textContent = fat.toFixed(1) + 'g';
    if (fKcalEl) fKcalEl.textContent = Math.round(fKcal) + ' kcal';
    if (fPctEl) fPctEl.textContent = fPct + '%';

    if (pieEl) {
      pieEl.setAttribute('aria-label', 'Phân bổ năng lượng: Tinh bột ' + cPct + '%, Chất đạm ' + pPct + '%, Chất béo ' + fPct + '%');
      renderMacroPieSvg(pieEl, [
        { className: 'pie-seg-carb', pct: cPct },
        { className: 'pie-seg-protein', pct: pPct },
        { className: 'pie-seg-lipid', pct: fPct }
      ], kcal);
    }

    if (fibEl) fibEl.textContent = fiber.toFixed(1) + 'g';
    if (fibDvEl) fibDvEl.textContent = fiberDvPct + '%';
    if (fibBarEl) fibBarEl.setAttribute('width', String(Math.max(2, fiberDvPct)));
    if (fibNoteEl) {
      if (fiber < 3.0) {
        fibNoteEl.setAttribute('data-status', 'warn');
        fibNoteEl.textContent = 'Chất xơ mới đạt ' + fiberDvPct + '% nhu cầu ngày (25g): nên kèm thêm rau luộc hoặc nộm.';
      } else {
        fibNoteEl.setAttribute('data-status', 'ok');
        fibNoteEl.textContent = 'Đạt ' + fiberDvPct + '% nhu cầu chất xơ cả ngày (25g); ăn kèm đủ rau sống sẽ giữ no lâu hơn.';
      }
    }

    if (amdrStatusEl) {
      amdrStatusEl.setAttribute('data-status', amdrOk ? 'ok' : 'warn');
      amdrStatusEl.textContent = amdrOk ? 'Đạt chuẩn cân đối' : 'Cần cân bằng thêm';
    }
    if (amdrInsightEl) amdrInsightEl.textContent = insight;

    if (modSumEl) {
      modSumEl.textContent = appliedLabels.length > 0
        ? ('Đã áp dụng: ' + appliedLabels.join(', ') + '.')
        : 'Chưa bật thêm gia vị kèm.';
    }
    if (noteEl) noteEl.textContent = dish.note;
  }

  calDishBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.getAttribute('data-cal-dish');
      if (!id || !CALC_DISHES[id]) return;
      calState.dishId = id;
      renderCalorieWorkbench();
    });
  });

  calScaleBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var scaleKey = btn.getAttribute('data-cal-scale');
      if (!scaleKey || !CALC_PORTIONS[scaleKey]) return;
      calState.portionKey = scaleKey;
      renderCalorieWorkbench();
    });
  });

  calModBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      var modKey = btn.getAttribute('data-cal-mod');
      if (!modKey || !CALC_MODIFIERS[modKey]) return;
      if (calState.activeMods.has(modKey)) calState.activeMods.delete(modKey);
      else calState.activeMods.add(modKey);
      renderCalorieWorkbench();
    });
  });

  renderCalorieWorkbench();

  // 5B. Tab 2: Fridge-to-3-Dish Tray Simulator + Parallel Schedule
  var kbRecipes = [];
  var snapshotEl = document.getElementById('kb-snapshot');
  if (snapshotEl && snapshotEl.textContent) {
    try {
      var parsedKb = JSON.parse(snapshotEl.textContent);
      if (Array.isArray(parsedKb)) kbRecipes = parsedKb;
    } catch (e) {
      kbRecipes = [];
    }
  }

  var URGENCY_KEYS = new Set(['egg', 'tofu', 'greens', 'fish']);
  var PROTEIN_KEYS = new Set(['egg', 'tofu', 'pork', 'fish']);
  var selectedIngs = new Set();
  var simServings = 2;
  var simMaxMinutes = 45;

  document.querySelectorAll('[data-ingredient]').forEach(function (btn) {
    if (btn.getAttribute('aria-pressed') === 'true') {
      selectedIngs.add(btn.getAttribute('data-ingredient'));
    }
    btn.addEventListener('click', function () {
      var k = btn.getAttribute('data-ingredient');
      if (!k) return;
      if (selectedIngs.has(k)) {
        selectedIngs.delete(k);
        btn.setAttribute('aria-pressed', 'false');
      } else {
        selectedIngs.add(k);
        btn.setAttribute('aria-pressed', 'true');
      }
      renderSim();
    });
  });

  document.querySelectorAll('[data-servings]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      simServings = Number(btn.getAttribute('data-servings')) || 2;
      document.querySelectorAll('[data-servings]').forEach(function (o) {
        o.setAttribute('aria-pressed', String(o === btn));
      });
      renderSim();
    });
  });

  document.querySelectorAll('[data-max-minutes]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      simMaxMinutes = Number(btn.getAttribute('data-max-minutes')) || 45;
      document.querySelectorAll('[data-max-minutes]').forEach(function (o) {
        o.setAttribute('aria-pressed', String(o === btn));
      });
      renderSim();
    });
  });

  function scoreDish(d) {
    var score = d.total_minutes <= simMaxMinutes ? 4 : -8;
    (d.keys || []).forEach(function (k) {
      if (selectedIngs.has(k)) score += URGENCY_KEYS.has(k) ? 14 : 9;
    });
    return score;
  }

  function pickSlot(slot, pref) {
    var list = kbRecipes.filter(function (r) { return r.slot === slot; });
    if (pref) {
      var exact = list.find(function (r) { return r.slug === pref; });
      if (exact) return exact;
    }
    list.sort(function (a, b) {
      return scoreDish(b) - scoreDish(a) || a.total_minutes - b.total_minutes;
    });
    return list[0] || null;
  }

  var simPhotoMap = {
    'dau-phu-non-sot-nam': '/gioi-thieu/img/silken-tofu.webp?v=' + ASSET_VER,
    'thit-kho-tieu': '/gioi-thieu/img/caramel-pork.webp?v=' + ASSET_VER,
    'trung-chien-hanh': '/gioi-thieu/img/omelette.webp?v=' + ASSET_VER,
    'trung-sot-ca-chua': '/gioi-thieu/img/tomato-egg.webp?v=' + ASSET_VER,
    'ca-kho-to': '/gioi-thieu/img/caramel-trout.webp?v=' + ASSET_VER,
    'bun_thit_nuong': '/gioi-thieu/img/bun-thit-nuong.webp?v=' + ASSET_VER
  };

  function makeScheduleItem(minuteLabel, stepText) {
    var li = document.createElement('li');
    li.className = 'body-6';
    var timeSpan = document.createElement('span');
    timeSpan.className = 'tabular-nums body-4 sim-step-time';
    timeSpan.textContent = minuteLabel;
    var textSpan = document.createElement('span');
    textSpan.textContent = stepText;
    li.appendChild(timeSpan);
    li.appendChild(textSpan);
    return li;
  }

  function renderSim() {
    var nameEl = document.getElementById('recipe-name');
    var descEl = document.getElementById('recipe-description');
    var manEl = document.getElementById('sim-slot-man');
    var rauEl = document.getElementById('sim-slot-rau');
    var canhEl = document.getElementById('sim-slot-canh');
    var riceEl = document.getElementById('sim-slot-rice');
    var minEl = document.getElementById('sim-minutes');
    var kcalEl = document.getElementById('sim-kcal');
    var urgEl = document.getElementById('sim-urgency');
    var hintEl = document.getElementById('sim-hint');
    var simPhotoEl = document.getElementById('sim-dish-photo');
    var schedWrap = document.getElementById('sim-schedule-wrap');
    var schedList = document.getElementById('sim-schedule');
    if (!nameEl || !descEl) return;

    if (kbRecipes.length === 0) {
      nameEl.textContent = 'Tạm chưa tải được kho công thức';
      descEl.textContent = 'Không đọc được danh sách món ăn mẫu từ trang.';
      if (manEl) manEl.textContent = 'Chưa có dữ liệu';
      if (rauEl) rauEl.textContent = 'Chưa có dữ liệu';
      if (canhEl) canhEl.textContent = 'Chưa có dữ liệu';
      if (riceEl) riceEl.textContent = 'Chưa tính';
      if (minEl) minEl.textContent = '0';
      if (kcalEl) kcalEl.textContent = '0';
      if (urgEl) urgEl.textContent = '0';
      if (schedList) schedList.replaceChildren();
      if (schedWrap) schedWrap.setAttribute('hidden', '');
      if (simPhotoEl) {
        simPhotoEl.setAttribute('src', '/gioi-thieu/img/vietnamese-table.jpg');
        simPhotoEl.setAttribute('alt', 'Mâm cơm gia đình Việt');
      }
      if (hintEl) {
        hintEl.textContent = 'Vui lòng tải lại trang hoặc mở thẳng ứng dụng Mỹ Vị.';
        hintEl.removeAttribute('hidden');
      }
      return;
    }

    if (selectedIngs.size === 0) {
      nameEl.textContent = 'Chọn ít nhất 1 nguyên liệu để gợi ý';
      descEl.textContent = 'Bấm chọn nguyên liệu đang có bên trái để xem mâm cơm 3 món và lịch nấu song song.';
      if (manEl) manEl.textContent = 'Chưa chọn';
      if (rauEl) rauEl.textContent = 'Chưa chọn';
      if (canhEl) canhEl.textContent = 'Chưa chọn';
      if (riceEl) riceEl.textContent = 'Cơm ' + Math.round(simServings * 1.5) + ' bát';
      if (minEl) minEl.textContent = '0';
      if (kcalEl) kcalEl.textContent = '0';
      if (urgEl) urgEl.textContent = '0';
      if (schedList) schedList.replaceChildren();
      if (schedWrap) schedWrap.setAttribute('hidden', '');
      if (simPhotoEl) {
        simPhotoEl.setAttribute('src', '/gioi-thieu/img/vietnamese-table.jpg');
        simPhotoEl.setAttribute('alt', 'Mâm cơm gia đình Việt');
      }
      if (hintEl) hintEl.setAttribute('hidden', '');
      return;
    }

    var prefMan = null;
    if (selectedIngs.has('pork') && simMaxMinutes >= 50) prefMan = 'thit-kho-tieu';
    else if (selectedIngs.has('egg') && selectedIngs.has('tomato')) prefMan = 'trung-sot-ca-chua';
    else if (selectedIngs.has('egg') && !selectedIngs.has('tofu') && !selectedIngs.has('fish')) prefMan = 'trung-chien-hanh';
    else if (selectedIngs.has('tofu')) prefMan = 'dau-phu-non-sot-nam';
    else if (selectedIngs.has('fish')) prefMan = 'ca-kho-to';
    else if (selectedIngs.has('pork')) prefMan = 'bun_thit_nuong';

    var man = pickSlot('man', prefMan);
    var rau = pickSlot('rau', null);
    var canh = pickSlot('canh', null);

    var hasProt = false;
    var urgentCnt = 0;
    selectedIngs.forEach(function (k) {
      if (PROTEIN_KEYS.has(k)) hasProt = true;
      if (URGENCY_KEYS.has(k)) urgentCnt += 1;
    });

    var manMin = man ? man.total_minutes : 20;
    var rauMin = rau ? rau.total_minutes : 12;
    var canhMin = canh ? canh.total_minutes : 15;
    var estMin = Math.max(15, Math.max(manMin, rauMin, canhMin) + 6);
    var kcal = (man ? man.kcal_per_serving : 0) + (rau ? rau.kcal_per_serving : 0) + (canh ? canh.kcal_per_serving : 0) + 195;

    nameEl.textContent = man ? man.name_vi : 'Mâm cơm gia đình';
    descEl.textContent = 'Ưu tiên ' + urgentCnt + ' món cần dùng sớm, ăn kèm ' + (rau ? rau.name_vi : 'rau xanh') + ' và ' + (canh ? canh.name_vi : 'canh thanh') + ' cho ' + simServings + ' người.';
    if (manEl && man) manEl.textContent = man.name_vi;
    if (rauEl && rau) rauEl.textContent = rau.name_vi;
    if (canhEl && canh) canhEl.textContent = canh.name_vi;
    if (riceEl) riceEl.textContent = 'Cơm ' + Math.round(simServings * 1.5) + ' bát';
    if (minEl) minEl.textContent = String(estMin);
    if (kcalEl) kcalEl.textContent = String(kcal);
    if (urgEl) urgEl.textContent = String(urgentCnt);

    if (schedList && schedWrap) {
      var canhStart = Math.max(2, estMin - canhMin);
      var rauStart = Math.max(4, estMin - rauMin);
      var items = [
        makeScheduleItem("00'", 'Cắm cơm và sơ chế, bật bếp món ' + (man ? man.name_vi : 'chính')),
        makeScheduleItem(String(canhStart).padStart(2, '0') + "'", 'Nấu ' + (canh ? canh.name_vi : 'canh') + ' trên bếp phụ'),
        makeScheduleItem(String(rauStart).padStart(2, '0') + "'", 'Xào hoặc trộn ' + (rau ? rau.name_vi : 'rau') + ' để dọn bàn nóng cùng lúc')
      ];
      schedList.replaceChildren.apply(schedList, items);
      schedWrap.removeAttribute('hidden');
    }

    if (simPhotoEl) {
      var mappedSrc = man && simPhotoMap[man.slug];
      simPhotoEl.setAttribute('src', mappedSrc || '/gioi-thieu/img/vietnamese-table.jpg');
      simPhotoEl.setAttribute('alt', mappedSrc ? ('Ảnh món ' + man.name_vi) : 'Mâm cơm gia đình Việt');
    }

    if (hintEl) {
      if (!hasProt) {
        hintEl.textContent = 'Gợi ý: Chọn thêm Trứng gà hoặc Đậu phụ để bữa cơm đủ đạm hơn.';
        hintEl.removeAttribute('hidden');
      } else if (estMin > simMaxMinutes) {
        hintEl.textContent = 'Gợi ý: Mâm này nấu lâu hơn ' + simMaxMinutes + ' phút; bạn có thể tăng mức thời gian.';
        hintEl.removeAttribute('hidden');
      } else {
        hintEl.setAttribute('hidden', '');
      }
    }
  }
  renderSim();

  // 6. Real App Walkthrough (4-tab preview)
  var SCREENS = {
    quet: {
      title: 'Nhận diện nguyên liệu từ ảnh chụp',
      desc: 'Khung chọn hiện trực tiếp trên ảnh chụp để bạn chạm đổi tên hoặc chỉnh số gam trước khi lưu.',
      metrics: [['Phân loại', 'Rau, thịt, cá, đậu, nấm'], ['Chỉnh sửa', 'Chạm sửa trực tiếp']],
      alt: 'Màn hình nhận diện nguyên liệu tủ lạnh trên ứng dụng Mỹ Vị'
    },
    kho: {
      title: 'Xem đồ nào cần nấu trước',
      desc: 'Chia rõ bốn mức Tươi, Nên dùng sớm, Dùng ngay hay Cần kiểm tra để tránh quên đồ góc tủ.',
      metrics: [['Nhắc nhở', 'Theo mức độ tươi'], ['Sắp xếp', 'Theo từng buổi chợ']],
      alt: 'Màn hình sắp xếp nguyên liệu theo hạn dùng trên Mỹ Vị'
    },
    mam: {
      title: 'Gợi ý mâm cơm và bỏ món dị ứng',
      desc: 'Loại trừ tuyệt đối món gây dị ứng gia đình, ưu tiên đồ gần hết hạn và đẩy đồ thiếu sang danh sách đi chợ.',
      metrics: [['Bữa cơm', 'Mặn, rau, canh, cơm'], ['Dị ứng', 'Tự động loại trừ']],
      alt: 'Màn hình gợi ý mâm cơm gia đình trên Mỹ Vị'
    },
    nau: {
      title: 'Xem thứ tự nấu từng bếp',
      desc: 'Chia rõ lúc rửa rau, lúc canh nồi kho để cả mâm cơm nóng dọn ra bàn cùng giờ ăn.',
      metrics: [['Số bếp', 'Từ 1 đến 4 bếp'], ['Lịch nấu', 'Song song từng bước']],
      alt: 'Màn hình lịch nấu song song từng bước trên Mỹ Vị'
    }
  };

  var screenTabs = Array.from(document.querySelectorAll('[data-screen-tab]'));
  function selectScreen(screenKey, moveFocus) {
    var info = SCREENS[screenKey];
    if (!info) return;
    screenTabs.forEach(function (tab) {
      var active = tab.getAttribute('data-screen-tab') === screenKey;
      tab.setAttribute('aria-selected', String(active));
      tab.setAttribute('tabindex', active ? '0' : '-1');
      if (active && moveFocus) tab.focus();
    });
    var titleEl = document.getElementById('device-title');
    var descEl = document.getElementById('device-desc');
    var metricsEl = document.getElementById('device-metrics');
    if (titleEl) titleEl.textContent = info.title;
    if (descEl) descEl.textContent = info.desc;
    if (metricsEl) {
      var nodes = info.metrics.map(function (pair) {
        var box = document.createElement('div');
        var dt = document.createElement('dt');
        dt.className = 'caption-4';
        dt.textContent = pair[0];
        var dd = document.createElement('dd');
        dd.className = 'body-4';
        dd.textContent = pair[1];
        box.appendChild(dt);
        box.appendChild(dd);
        return box;
      });
      metricsEl.replaceChildren.apply(metricsEl, nodes);
    }
    if (previewImg) {
      previewImg.setAttribute('data-screen', screenKey);
      previewImg.setAttribute('alt', info.alt);
      syncDeviceImg();
    }
  }

  screenTabs.forEach(function (tab, idx) {
    tab.addEventListener('click', function () {
      selectScreen(tab.getAttribute('data-screen-tab'), false);
    });
    tab.addEventListener('keydown', function (evt) {
      var next = idx;
      if (evt.key === 'ArrowRight' || evt.key === 'ArrowDown') next = (idx + 1) % screenTabs.length;
      else if (evt.key === 'ArrowLeft' || evt.key === 'ArrowUp') next = (idx - 1 + screenTabs.length) % screenTabs.length;
      else if (evt.key === 'Home') next = 0;
      else if (evt.key === 'End') next = screenTabs.length - 1;
      else return;
      evt.preventDefault();
      selectScreen(screenTabs[next].getAttribute('data-screen-tab'), true);
    });
  });

  // 7. APK Range Probe
  function makeDownloadSvg() {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('width', '18');
    svg.setAttribute('height', '18');
    svg.setAttribute('viewBox', '0 0 256 256');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '20');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    var path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', 'M128 40v128M72 112l56 56 56-56M48 208h160');
    svg.appendChild(path);
    return svg;
  }

  var downloadBtn = document.getElementById('android-download');
  if (downloadBtn) {
    var apkHref = downloadBtn.getAttribute('data-apk-href') || '/tai-ve/tastoria-0.1.4.apk';
    var apkLabel = downloadBtn.getAttribute('data-apk-label') || 'Tải bản Android (.apk)';
    fetch(apkHref, { method: 'GET', headers: { Range: 'bytes=0-15' } })
      .then(function (resp) {
        if (resp.ok || resp.status === 206) {
          downloadBtn.setAttribute('href', apkHref);
          downloadBtn.setAttribute('aria-disabled', 'false');
          var span = document.createElement('span');
          span.textContent = apkLabel;
          downloadBtn.replaceChildren(span, makeDownloadSvg());
        } else {
          downloadBtn.textContent = 'Bản Android đang cập nhật';
        }
      })
      .catch(function () {
        downloadBtn.textContent = 'Bản Android đang cập nhật';
      });
  }
})();
