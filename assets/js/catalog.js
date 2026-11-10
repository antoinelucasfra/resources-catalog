// Client-side renderer for the resources catalog. index.qmd writes
// catalog-index.json at render time; this file fetches it and renders one page
// of cards at a time. Kept dependency-free on purpose: no build step, no npm.
(function () {
  'use strict';

  const root = document.getElementById('catalog');
  if (!root) return;

  const DATA_NODE_ID = 'catalog-data';
  const PAGE_SIZE = parseInt(root.dataset.pageSize, 10) || 24;
  const SORT_DEFAULT_DIR = { date: 'desc', title: 'asc' };

  const els = {
    search: document.getElementById('catalog-search'),
    type: document.getElementById('catalog-type'),
    topic: document.getElementById('catalog-topic'),
    language: document.getElementById('catalog-language'),
    sort: document.getElementById('catalog-sort'),
    direction: document.getElementById('catalog-direction'),
    viewGrid: document.getElementById('catalog-view-grid'),
    viewList: document.getElementById('catalog-view-list'),
    results: document.getElementById('catalog-results'),
    empty: document.getElementById('catalog-empty'),
    counter: document.getElementById('catalog-counter'),
    loadMore: document.getElementById('catalog-load-more'),
    clear: document.getElementById('catalog-clear'),
    emptyClear: document.getElementById('catalog-empty-clear'),
    dialog: document.getElementById('catalog-dialog'),
    dialogTitle: document.getElementById('catalog-dialog-title'),
    dialogBody: document.getElementById('catalog-dialog-body')
  };

  let items = [];
  const byUrl = new Map();
  let visible = [];

  const state = {
    query: '',
    states: new Set(),
    type: '',
    topic: '',
    language: '',
    sort: 'date',
    dir: 'desc',
    view: 'grid',
    page: 1
  };

  // ------------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------------

  const escapeHtml = (value) => String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

  // Same escaping scripts/utils.py applies when writing resources.txt, so the
  // snippet in the Cite dialog can be pasted straight into a pull request.
  const yamlEscape = (value) => String(value == null ? '' : value)
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"');

  const debounce = (fn, wait) => {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  };

  const countBy = (values) => {
    const counts = new Map();
    values.forEach((value) => {
      if (!value) return;
      counts.set(value, (counts.get(value) || 0) + 1);
    });
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  };

  // ------------------------------------------------------------------------
  // URL state: every filter is deep-linkable and back/forward works.
  // ------------------------------------------------------------------------

  const readStateFromUrl = () => {
    const params = new URLSearchParams(window.location.search);
    state.query = params.get('q') || '';
    state.states = new Set((params.get('status') || '').split(',').filter(Boolean));
    state.type = params.get('type') || '';
    state.topic = params.get('topic') || '';
    state.language = params.get('lang') || '';
    state.sort = ['date', 'title'].includes(params.get('sort')) ? params.get('sort') : 'date';
    state.dir = params.get('dir') === 'asc' ? 'asc' : params.get('dir') === 'desc' ? 'desc' : SORT_DEFAULT_DIR[state.sort];
    state.view = params.get('view') === 'list' ? 'list' : 'grid';
    state.page = 1;
  };

  const writeStateToUrl = (push) => {
    const params = new URLSearchParams();
    if (state.query) params.set('q', state.query);
    if (state.states.size) params.set('status', Array.from(state.states).join(','));
    if (state.type) params.set('type', state.type);
    if (state.topic) params.set('topic', state.topic);
    if (state.language) params.set('lang', state.language);
    if (state.sort !== 'date') params.set('sort', state.sort);
    if (state.dir !== SORT_DEFAULT_DIR[state.sort]) params.set('dir', state.dir);
    if (state.view !== 'grid') params.set('view', state.view);
    const query = params.toString();
    const url = `${window.location.pathname}${query ? `?${query}` : ''}`;
    if (push) window.history.pushState(null, '', url);
    else window.history.replaceState(null, '', url);
  };

  // ------------------------------------------------------------------------
  // Filtering and sorting
  // ------------------------------------------------------------------------

  const matches = (item) => {
    if (state.query && !item.haystack.includes(state.query)) return false;
    if (state.states.size && !state.states.has(item.status)) return false;
    if (state.type && item.type !== state.type) return false;
    if (state.topic && !item.topics.includes(state.topic)) return false;
    if (state.language && !item.languages.includes(state.language)) return false;
    return true;
  };

  const applyFilters = () => {
    state.query = state.query.trim().toLowerCase();
    visible = items.filter(matches);
    const sign = state.dir === 'asc' ? 1 : -1;
    visible.sort((a, b) => {
      if (state.sort === 'title') return a.title.localeCompare(b.title) * sign;
      // Undated entries have no position on a date scale: keep them last in
      // both directions instead of letting them float with the epoch value.
      if (!a.date !== !b.date) return a.date ? -1 : 1;
      return String(a.date).localeCompare(String(b.date)) * sign;
    });
  };

  // ------------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------------

  const badge = (text, cls) => `<span class="badge ${cls}">${escapeHtml(text)}</span>`;

  const statusBanner = (item) => {
    if (item.status !== 'dead') return '';
    const when = item.checked ? ` (checked ${escapeHtml(item.checked)})` : '';
    return `<p class="catalog-banner text-danger border-start border-3 border-danger ps-2 py-1 mb-2" role="note">
      <i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
      Possibly dead link${when}</p>`;
  };

  const cardMarkup = (item) => {
    // datetext is the raw resources.txt value, so a month-precision date shows
    // as 2021-04 instead of the 2021-04-01 anchor used for sorting.
    const shownDate = item.datetext || item.date;
    const date = shownDate
      ? `<time datetime="${escapeHtml(item.date || shownDate)}">${escapeHtml(shownDate)}</time>`
      : '';
    const topics = item.topics
      .map((topic) => `<button type="button" class="badge bg-body-secondary text-body border-0 catalog-topic" data-topic="${escapeHtml(topic)}">${escapeHtml(topic)}</button>`)
      .join('');
    const languages = item.languages
      .map((language) => `<button type="button" class="badge bg-body-secondary text-body border-0 catalog-topic" data-language="${escapeHtml(language)}">${escapeHtml(language)}</button>`)
      .join('');

    return `<div class="g-col-12 g-col-md-6 g-col-xl-4 catalog-cell" role="listitem">
  <article class="card catalog-card h-100">
    <div class="card-body d-flex flex-column">
      ${statusBanner(item)}
      <h3 class="h6 card-title catalog-title no-anchor mb-1">
        <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
      </h3>
      <p class="small text-muted mb-2 catalog-meta">
        ${item.type ? badge(item.type, 'text-bg-primary') : ''}
        <span class="catalog-host">${escapeHtml(item.host)}</span>
        ${date}
      </p>
      ${item.description ? `<p class="card-text catalog-description flex-grow-1">${escapeHtml(item.description)}</p>` : '<p class="card-text flex-grow-1"></p>'}
      ${topics || languages ? `<div class="d-flex flex-wrap gap-1 mb-2">${topics}${languages}</div>` : ''}
    </div>
    <div class="card-footer bg-transparent d-flex gap-2">
      <a class="btn btn-primary btn-sm flex-fill" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
        <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i> Open
      </a>
      <button type="button" class="btn btn-outline-secondary btn-sm flex-fill" data-cite="${escapeHtml(item.url)}"
        aria-label="Cite or copy ${escapeHtml(item.title)}">
        <i class="bi bi-clipboard" aria-hidden="true"></i> Cite
      </button>
    </div>
  </article>
</div>`;
  };

  const render = () => {
    const shown = Math.min(state.page * PAGE_SIZE, visible.length);
    const holder = document.createElement('div');
    holder.innerHTML = visible.slice(0, shown).map(cardMarkup).join('');
    const fragment = document.createDocumentFragment();
    while (holder.firstElementChild) fragment.appendChild(holder.firstElementChild);

    els.results.replaceChildren(fragment);
    els.results.classList.toggle('catalog-list-mode', state.view === 'list');
    els.empty.classList.toggle('d-none', visible.length > 0);
    els.loadMore.classList.toggle('d-none', shown >= visible.length);
    els.loadMore.textContent = `Load more (${visible.length - shown} remaining)`;

    // Report what is on screen, not what matched: "all 1266" beside 24 cards
    // reads as a rendering failure.
    if (visible.length === 0) {
      els.counter.innerHTML = '';
      return;
    }
    const head = shown < visible.length ? `Showing ${shown} of ${visible.length}` : `Showing all ${visible.length}`;
    const tail = visible.length === items.length ? ' resources' : ` matching resources, out of ${items.length}`;
    els.counter.innerHTML = `<em>${head}${tail}</em>`;
  };

  const refresh = ({ resetPage = true, push = false } = {}) => {
    if (resetPage) state.page = 1;
    applyFilters();
    render();
    writeStateToUrl(push);
  };

  // ------------------------------------------------------------------------
  // Cite / copy dialog (native <dialog>: focus trap and Esc for free)
  // ------------------------------------------------------------------------

  const codeBlock = (code) => `<div class="d-flex align-items-start gap-2">
    <pre class="flex-grow-1 mb-0"><code>${escapeHtml(code)}</code></pre>
    <button type="button" class="btn btn-outline-secondary btn-sm catalog-copy" data-copy="${escapeHtml(code)}"
      aria-label="Copy to clipboard"><i class="bi bi-clipboard" aria-hidden="true"></i></button>
  </div>`;

  const citationFor = (item) => {
    const year = item.date ? item.date.slice(0, 4) : 'n.d.';
    const today = new Date().toISOString().slice(0, 10);
    return `${item.title} (${year}). ${item.type}. ${item.url}. Accessed ${today}.`;
  };

  const entryFor = (item) => {
    const fields = [
      ['title', item.title],
      ['type', item.type],
      ['link', item.url],
      ['language', item.languages.join(';')],
      ['category', item.topics.join(';')],
      ['description', item.description],
      ['date', item.date || '']
    ];
    return ['---', ...fields.map(([key, value]) => `${key}: "${yamlEscape(value)}"`), '---'].join('\n');
  };

  const openCite = (url) => {
    const item = byUrl.get(url);
    if (!item || !els.dialog) return;
    els.dialogTitle.textContent = item.title;
    els.dialogBody.innerHTML = `<dl class="mb-0">
      <dt>Link</dt><dd>${codeBlock(item.url)}</dd>
      <dt>Citation</dt><dd>${codeBlock(citationFor(item))}</dd>
      <dt>Catalog entry <span class="text-muted fw-normal">(paste-ready for a pull request)</span></dt>
      <dd class="mb-0">${codeBlock(entryFor(item))}</dd>
    </dl>`;
    els.dialog.showModal();
  };

  // ------------------------------------------------------------------------
  // Facet controls
  // ------------------------------------------------------------------------

  const fillSelect = (select, label, values, selected) => {
    const options = [`<option value="">${escapeHtml(label)}</option>`].concat(
      values.map(([value, count]) => `<option value="${escapeHtml(value)}">${escapeHtml(value)} (${count})</option>`)
    );
    select.innerHTML = options.join('');
    select.value = selected;
  };

  const populateFacets = () => {
    fillSelect(
      els.type,
      'All types',
      countBy(items.map((item) => item.type)),
      state.type
    );
    fillSelect(
      els.topic,
      'All topics',
      countBy(items.flatMap((item) => item.topics)),
      state.topic
    );
    fillSelect(
      els.language,
      'All languages',
      countBy(items.flatMap((item) => item.languages)),
      state.language
    );

    const statusCounts = new Map([['ok', 0], ['dead', 0], ['unknown', 0]]);
    items.forEach((item) => statusCounts.set(item.status, (statusCounts.get(item.status) || 0) + 1));
    root.querySelectorAll('.filter-chip').forEach((chip) => {
      const count = statusCounts.get(chip.dataset.state) || 0;
      chip.querySelector('.chip-count').textContent = count ? `(${count})` : '';
      chip.disabled = count === 0;
    });

    els.search.placeholder = `Search ${items.length.toLocaleString()} resources, topics, languages…`;
  };

  const syncControls = () => {
    els.search.value = state.query;
    els.type.value = state.type;
    els.topic.value = state.topic;
    els.language.value = state.language;
    els.sort.value = state.sort;
    els.viewGrid.checked = state.view === 'grid';
    els.viewList.checked = state.view === 'list';
    const descending = state.dir === 'desc';
    els.direction.dataset.direction = state.dir;
    els.direction.setAttribute('aria-label', descending ? 'Sort descending' : 'Sort ascending');
    els.direction.querySelector('i').className = descending ? 'bi bi-sort-down' : 'bi bi-sort-up';
    root.querySelectorAll('.filter-chip').forEach((chip) => {
      const active = state.states.has(chip.dataset.state);
      chip.classList.toggle('active', active);
      chip.setAttribute('aria-pressed', String(active));
    });
  };

  // ------------------------------------------------------------------------
  // Events
  // ------------------------------------------------------------------------

  els.search.addEventListener('input', debounce(() => {
    state.query = els.search.value;
    refresh();
  }, 200));

  els.type.addEventListener('change', () => {
    state.type = els.type.value;
    refresh({ push: true });
  });

  els.topic.addEventListener('change', () => {
    state.topic = els.topic.value;
    refresh({ push: true });
  });

  els.language.addEventListener('change', () => {
    state.language = els.language.value;
    refresh({ push: true });
  });

  els.sort.addEventListener('change', () => {
    state.sort = els.sort.value;
    state.dir = SORT_DEFAULT_DIR[state.sort];
    syncControls();
    refresh({ push: true });
  });

  els.direction.addEventListener('click', () => {
    state.dir = state.dir === 'desc' ? 'asc' : 'desc';
    syncControls();
    refresh({ push: true });
  });

  els.loadMore.addEventListener('click', () => {
    state.page += 1;
    render();
  });

  [els.clear, els.emptyClear].forEach((button) => button.addEventListener('click', () => {
    state.query = '';
    state.states.clear();
    state.type = '';
    state.topic = '';
    state.language = '';
    state.sort = 'date';
    state.dir = SORT_DEFAULT_DIR.date;
    els.search.value = '';
    syncControls();
    refresh({ push: true });
  }));

  els.viewGrid.addEventListener('change', () => {
    if (!els.viewGrid.checked) return;
    state.view = 'grid';
    refresh({ resetPage: false });
  });

  els.viewList.addEventListener('change', () => {
    if (!els.viewList.checked) return;
    state.view = 'list';
    refresh({ resetPage: false });
  });

  root.addEventListener('click', (event) => {
    const chip = event.target.closest('.filter-chip');
    if (chip) {
      const value = chip.dataset.state;
      if (state.states.has(value)) state.states.delete(value);
      else state.states.add(value);
      syncControls();
      refresh({ push: true });
      return;
    }

    const topic = event.target.closest('.catalog-topic');
    if (topic) {
      if (topic.dataset.topic) {
        state.topic = state.topic === topic.dataset.topic ? '' : topic.dataset.topic;
        els.topic.value = state.topic;
      } else if (topic.dataset.language) {
        state.language = state.language === topic.dataset.language ? '' : topic.dataset.language;
        els.language.value = state.language;
      }
      refresh({ push: true });
      return;
    }

    const cite = event.target.closest('[data-cite]');
    if (cite) openCite(cite.dataset.cite);
  });

  els.dialogBody.addEventListener('click', (event) => {
    const button = event.target.closest('.catalog-copy');
    if (!button) return;
    navigator.clipboard.writeText(button.dataset.copy).then(() => {
      const icon = button.querySelector('i');
      icon.className = 'bi bi-clipboard-check';
      setTimeout(() => { icon.className = 'bi bi-clipboard'; }, 1500);
    }).catch(() => {
      button.setAttribute('title', 'Copy failed; select the text manually');
    });
  });

  // `/` focuses search, the convention on documentation sites, unless the
  // visitor is already typing somewhere.
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    event.preventDefault();
    els.search.focus();
  });

  window.addEventListener('popstate', () => {
    readStateFromUrl();
    syncControls();
    applyFilters();
    render();
  });

  // ------------------------------------------------------------------------
  // Boot
  // ------------------------------------------------------------------------

  const prepare = (raw) => raw.map((item) => {
    const url = item.url || '';
    let host = '';
    try {
      host = new URL(url).hostname.replace(/^www\./, '');
    } catch (error) {
      host = '';
    }
    const languages = item.languages || [];
    const topics = item.topics || [];
    return Object.assign({}, item, {
      url,
      host,
      type: item.type || '',
      description: item.description || '',
      date: item.date || null,
      datetext: item.datetext || '',
      languages,
      topics,
      status: item.status || 'unknown',
      haystack: [item.title, item.description, item.type, languages.join(' '), topics.join(' '), host]
        .join(' ').toLowerCase()
    });
  });

  // The index is inlined by index.qmd's R chunk as <script type="application/json">:
  // no extra request, and no build-order dependency between the chunk that
  // writes the data and a copy step that would have to publish it.
  try {
    const node = document.getElementById(DATA_NODE_ID);
    if (!node) throw new Error(`#${DATA_NODE_ID} is missing from the page`);
    items = prepare(JSON.parse(node.textContent));
    items.forEach((item) => byUrl.set(item.url, item));
    readStateFromUrl();
    populateFacets();
    // A stale deep link can name a facet value that no longer exists; drop it
    // instead of filtering everything out with no visible control for it.
    [['type', els.type], ['topic', els.topic], ['language', els.language]].forEach(([key, select]) => {
      if (state[key] && select.value !== state[key]) {
        state[key] = '';
        select.value = '';
      }
    });
    syncControls();
    applyFilters();
    render();
  } catch (error) {
    els.counter.innerHTML = '<span class="text-danger">The catalog data failed to load. Please reload the page.</span>';
    console.error('Failed to load the catalog index:', error);
  }
})();
