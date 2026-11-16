// Фронтенд без фреймворков: fetch к нашему FastAPI и перерисовка блоков.

const $ = (sel, root = document) => root.querySelector(sel);

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(Array.isArray(d) ? d.map((e) => e.msg).join('; ') : d || res.statusText);
  }
  return data;
}

function say(el, text, isError = false) {
  el.textContent = text;
  el.classList.toggle('err', isError);
}

// ---------- вкладки ----------
document.querySelectorAll('.tab').forEach((btn) =>
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b === btn));
    $('#tab-create').hidden = btn.dataset.tab !== 'create';
    $('#tab-edit').hidden = btn.dataset.tab !== 'edit';
    if (btn.dataset.tab === 'edit') loadKnown();
  })
);

// ---------- поиск оффера (выпадающий список) ----------
function offerSearch(container, onPick) {
  const input = $('.offer-search', container);
  const list = $('.suggest', container);
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { list.innerHTML = ''; return; }
      const offers = await api('GET', `/api/offers?q=${encodeURIComponent(q)}`).catch(() => []);
      list.innerHTML = '';
      offers.forEach((o) => {
        const li = document.createElement('li');
        li.textContent = `[${o.id}] ${o.name}`;
        li.addEventListener('click', () => { list.innerHTML = ''; onPick(o, input); });
        list.append(li);
      });
    }, 250);
  });
  input.addEventListener('blur', () => setTimeout(() => (list.innerHTML = ''), 200));
}

// ---------- создаватор ----------
const form = $('#create-form');
const createMsg = $('#create-msg');

async function loadMeta() {
  try {
    const meta = await api('GET', '/api/meta');
    for (const [field, items] of [['domain_id', meta.domains], ['group_id', meta.groups], ['source_id', meta.sources]]) {
      form.elements[field].innerHTML = items.map((i) => `<option value="${i.id}">${escapeHtml(i.name)}</option>`).join('');
    }
    if (meta.prefix) form.elements.name.placeholder = `${meta.prefix}campaign1`;
  } catch (e) {
    say(createMsg, `Не удалось загрузить справочники: ${e.message}`, true);
  }
}

offerSearch(form, (offer, input) => {
  input.value = `[${offer.id}] ${offer.name}`;
  form.elements.offer_id.value = offer.id;
});

form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = form.elements;
  if (!f.offer_id.value) return say(createMsg, 'Выберите оффер из списка', true);
  const btn = $('button[type=submit]', form);
  btn.disabled = true;
  say(createMsg, 'Создаю…');
  try {
    const c = await api('POST', '/api/campaigns', {
      name: f.name.value,
      country: f.country.value,
      offer_id: Number(f.offer_id.value),
      domain_id: Number(f.domain_id.value),
      group_id: Number(f.group_id.value),
      source_id: Number(f.source_id.value),
    });
    say(createMsg, `Готово: кампания #${c.keitaro_id} «${c.name}». Её можно открыть в редакторе.`);
    form.reset();
  } catch (e) {
    say(createMsg, e.message, true);
  } finally {
    btn.disabled = false;
  }
});

// ---------- редактор ----------
const editMsg = $('#edit-msg');
const campaignBox = $('#campaign');

async function loadKnown() {
  const rows = await api('GET', '/api/campaigns').catch(() => []);
  $('#known-campaigns').innerHTML =
    '<option value="">— загруженные ранее —</option>' +
    rows.map((c) => `<option value="${c.keitaro_id}">#${c.keitaro_id} ${escapeHtml(c.name)}</option>`).join('');
}

$('#known-campaigns').addEventListener('change', async (ev) => {
  if (!ev.target.value) return;
  $('#campaign-id').value = ev.target.value;
  run(async () => renderCampaign(await api('GET', `/api/campaigns/${ev.target.value}`)));
});

$('#fetch-btn').addEventListener('click', () => {
  const id = Number($('#campaign-id').value);
  if (!id) return say(editMsg, 'Введите ID кампании', true);
  run(async () => {
    renderCampaign(await api('POST', '/api/campaigns/fetch', { keitaro_id: id }));
    loadKnown();
  }, 'Загружаю из Keitaro…');
});

async function run(fn, pending = '') {
  say(editMsg, pending);
  try {
    await fn();
    say(editMsg, '');
  } catch (e) {
    say(editMsg, e.message, true);
  }
}

function renderCampaign(c) {
  campaignBox.innerHTML = `<h2>#${c.keitaro_id} ${escapeHtml(c.name)}</h2>`;
  c.streams.forEach((s) => campaignBox.append(renderStream(s)));
}

const STATUS = {
  active: '',
  pending_add: 'добавлен, не опубликован',
  pending_remove: 'удалён, не опубликован',
  removed: 'в архиве',
};

function renderStream(s) {
  const el = $('#stream-tpl').content.firstElementChild.cloneNode(true);
  el.classList.toggle('dirty', s.dirty);
  $('.stream-name', el).textContent = s.name || `Поток ${s.position}`;
  $('.stream-id', el).textContent = `#${s.keitaro_id}`;

  const replace = (fresh) => el.replaceWith(renderStream(fresh));
  const act = (method, url, body) => run(async () => replace(await api(method, url, body)));

  if (!s.has_offers) {
    // Поток без офферов (например гео → Google): просто показываем, что он есть
    $('table', el).remove();
    $('.add-row', el).remove();
    $('.stream-actions', el).remove();
    el.insertAdjacentHTML('beforeend', '<p class="no-offers">Поток без офферов</p>');
    return el;
  }

  const tbody = $('tbody', el);
  s.offers.forEach((o) => {
    const tr = document.createElement('tr');
    const gone = o.status === 'removed' || o.status === 'pending_remove';
    tr.classList.toggle('gone', gone);
    const badge = STATUS[o.status] ? `<span class="badge">${STATUS[o.status]}</span>` : '';
    tr.innerHTML = `
      <td>[${o.offer_id}] ${escapeHtml(o.offer_name)}${badge}</td>
      <td>${o.share}%${o.pinned ? ' 📌' : ''}</td>
      <td class="muted">${o.status === 'pending_add' ? '—' : o.published_share + '%'}</td>
      <td></td>`;
    const cell = tr.lastElementChild;

    if (o.status === 'removed') {
      cell.append(button('Bring back', () => act('POST', `/api/stream-offers/${o.id}/bring-back`)));
    } else if (!gone) {
      if (o.pinned) {
        cell.append(button('Unpin', () => act('POST', `/api/stream-offers/${o.id}/pin`, { pinned: false })));
      } else {
        const inp = document.createElement('input');
        inp.type = 'number'; inp.min = 0; inp.max = 100; inp.value = o.share; inp.className = 'pin';
        cell.append(inp, button('Pin', () =>
          act('POST', `/api/stream-offers/${o.id}/pin`, { pinned: true, share: Number(inp.value) })));
      }
      cell.append(' ', button('Remove', () => act('POST', `/api/stream-offers/${o.id}/remove`)));
    }
    tbody.append(tr);
  });

  offerSearch($('.add-row', el), (offer) => act('POST', `/api/streams/${s.id}/offers`, { offer_id: offer.id }));
  $('.push', el).addEventListener('click', () => act('POST', `/api/streams/${s.id}/push`));
  $('.cancel', el).addEventListener('click', () => act('POST', `/api/streams/${s.id}/cancel`));
  return el;
}

function button(text, onClick) {
  const b = document.createElement('button');
  b.textContent = text;
  b.addEventListener('click', onClick);
  return b;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

loadMeta();
