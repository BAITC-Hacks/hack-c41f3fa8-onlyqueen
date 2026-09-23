const form = document.querySelector('#search-form');
const results = document.querySelector('#results');
const errorBox = document.querySelector('#error');
const template = document.querySelector('#card-template');
let meta;

const money = value => new Intl.NumberFormat('ru-RU').format(value);
const prettyDate = value => new Intl.DateTimeFormat('ru-RU', {day: 'numeric', month: 'long'}).format(new Date(`${value}T12:00:00`));

function fill(name, values) {
  form.elements[name].replaceChildren(...values.map(value => new Option(value, value)));
}

function renderCategories(city) {
  const select = form.elements.category;
  const previous = select.value;
  const available = new Set(meta.categories_by_city[city] || []);
  const present = document.createElement('optgroup');
  present.label = `Есть в городе (${available.size})`;
  const elsewhere = document.createElement('optgroup');
  elsewhere.label = 'Есть в других городах';
  meta.categories.forEach(category => {
    const option = new Option(category, category);
    (available.has(category) ? present : elsewhere).appendChild(option);
  });
  select.replaceChildren(present, elsewhere);
  if (meta.categories.includes(previous)) select.value = previous;
}

fetch('/api/meta').then(response => response.json()).then(data => {
  meta = data;
  fill('city', data.cities);
  fill('event_format', data.formats);
  fill('language', ['', ...data.languages]);
  form.elements.language.options[0].textContent = 'Любой';
  form.elements.city.value = data.default_city;
  renderCategories(data.default_city);
  for (const name of ['event_date', 'compare_date']) {
    form.elements[name].min = data.date_min;
    form.elements[name].max = data.date_max;
  }
  form.elements.event_date.value = data.date_min;
  document.querySelector('#range-note').textContent = `Даты в наборе: ${data.date_min} — ${data.date_max}`;
});

form.elements.city.addEventListener('change', event => renderCategories(event.target.value));
document.querySelectorAll('[data-budget]').forEach(button => button.addEventListener('click', () => {
  form.elements.budget_kzt.value = button.dataset.budget;
  form.elements.budget_kzt.focus();
}));

function rejectionText(item) {
  const r = item.rejections;
  return `Профилей в городе и категории: ${item.base_count}. Исключены по причинам: заняты — ${r.busy}, формат — ${r.format}, бюджет — ${r.budget}, язык — ${r.language}, длительность — ${r.duration}. Один профиль может учитываться в нескольких причинах.`;
}

function addActionControls(container, item) {
  const guidance = item.guidance;
  if (!guidance || item.outcome === 'found') return;
  const actions = document.createElement('div');
  actions.className = 'actions';
  (guidance.suggested_cities || []).forEach(suggestion => {
    const cityButton = document.createElement('button');
    cityButton.type = 'button';
    cityButton.className = 'secondary';
    cityButton.textContent = `Искать в городе ${suggestion.city} · ${suggestion.profile_count}`;
    cityButton.addEventListener('click', () => {
      form.elements.city.value = suggestion.city;
      renderCategories(suggestion.city);
      form.elements.category.value = item.request.category;
      form.requestSubmit();
    });
    actions.appendChild(cityButton);
  });
  if (guidance.lowest_price_kzt !== null) {
    const info = document.createElement('p');
    info.innerHTML = `Минимальная цена в этой категории и городе — <strong>от ${money(guidance.lowest_price_kzt)} ₸</strong>.`;
    actions.appendChild(info);
    if (guidance.suggested_budget_kzt !== null && Number(item.request.budget_kzt) < guidance.suggested_budget_kzt) {
      const budgetButton = document.createElement('button');
      budgetButton.type = 'button';
      budgetButton.className = 'secondary';
      budgetButton.textContent = `Поставить бюджет ${money(guidance.suggested_budget_kzt)} ₸`;
      budgetButton.addEventListener('click', () => {
        form.elements.budget_kzt.value = guidance.suggested_budget_kzt;
        form.requestSubmit();
      });
      actions.appendChild(budgetButton);
    }
  }
  if (guidance.suggested_dates.length) {
    const group = document.createElement('div');
    group.className = 'date-actions';
    const label = document.createElement('span');
    label.textContent = 'Попробовать дату:';
    group.appendChild(label);
    guidance.suggested_dates.forEach(suggestion => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary';
      button.textContent = `${prettyDate(suggestion.date)} · ${suggestion.eligible_count}`;
      button.addEventListener('click', () => {
        form.elements.event_date.value = suggestion.date;
        form.requestSubmit();
      });
      group.appendChild(button);
    });
    actions.appendChild(group);
  }
  guidance.removable_constraints.forEach(suggestion => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = `${suggestion.label} · ${suggestion.eligible_count}`;
    button.addEventListener('click', () => {
      form.elements[suggestion.key].value = '';
      form.requestSubmit();
    });
    actions.appendChild(button);
  });
  if (actions.children.length) container.appendChild(actions);
}

function renderCard(rec) {
  const card = template.content.cloneNode(true);
  card.querySelector('h3').textContent = rec.name;
  card.querySelector('.category').textContent = rec.matching_category;
  card.querySelector('.city').textContent = rec.city;
  card.querySelector('.card-price').textContent = `от ${money(rec.price_from_kzt)} ₸`;
  card.querySelector('.score').textContent = `Дополнительные совпадения: ${rec.relevance_score} из 100`;
  card.querySelector('.explanation').textContent = rec.explanation;
  const detailHost = card.querySelector('.score-details');
  const detail = document.createElement('details');
  detail.innerHTML = `<summary>Дополнительные совпадения: ${rec.relevance_score} из 100 — показать расчёт</summary><div class="breakdown"></div>`;
  const breakdown = detail.querySelector('.breakdown');
  rec.score_breakdown.forEach(component => {
    const row = document.createElement('div');
    row.className = 'breakdown-row';
    row.innerHTML = `<div><strong>${component.kind === 'wishes_description' ? 'Пожелания' : component.kind === 'format_description' ? 'Формат' : component.kind === 'language' ? 'Язык' : 'Длительность'}</strong><span>${component.label}</span></div><b>+${component.points}</b>`;
    if (component.source_fragment) {
      const quote = document.createElement('blockquote');
      quote.textContent = `«${component.source_fragment}»`;
      row.appendChild(quote);
    }
    breakdown.appendChild(row);
  });
  const note = document.createElement('p');
  note.className = 'score-note';
  note.textContent = 'Это не вероятность и не оценка выполнения обязательных условий: они уже проверены отдельно. Баллы показывают только дополнительные совпадения; цена и ID используются при равенстве.';
  breakdown.appendChild(note);
  detailHost.appendChild(detail);
  const badges = card.querySelector('.badges');
  [rec.synthetic && 'Синтетический', rec.city_imputed && 'Город восстановлен', rec.price_imputed && 'Цена восстановлена']
    .filter(Boolean).forEach(label => {
      const badge = document.createElement('span'); badge.textContent = label; badges.appendChild(badge);
    });
  return card;
}

function renderSet(item, heading) {
  const section = document.createElement('section');
  section.className = `result-set ${item.outcome}`;
  const title = item.outcome === 'found' ? item.summary : item.outcome === 'no_city_category' ? 'В этой категории пока нет профилей' : 'Подходящих вариантов пока нет';
  section.innerHTML = `<div class="result-heading"><div><p class="eyebrow">${heading}</p><h2>${title}</h2><p class="plain-reason"></p></div></div>`;
  section.querySelector('.plain-reason').textContent = item.guidance.plain_reason;
  addActionControls(section, item);
  const details = document.createElement('details');
  details.className = 'why';
  details.innerHTML = `<summary>Почему такой результат?</summary><p>${rejectionText(item)}</p>`;
  section.appendChild(details);
  if (item.recommendations.length) {
    const grid = document.createElement('div'); grid.className = 'cards';
    item.recommendations.forEach(rec => grid.appendChild(renderCard(rec)));
    section.appendChild(grid);
  }
  return section;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  errorBox.hidden = true;
  results.innerHTML = '<p class="loading">Проверяем условия и календари…</p>';
  const payload = Object.fromEntries(new FormData(form));
  ['duration_hours', 'language', 'compare_date', 'wishes'].forEach(key => { if (!payload[key]) delete payload[key]; });
  try {
    const response = await fetch('/api/recommend', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось получить рекомендации');
    results.innerHTML = '';
    results.appendChild(renderSet(data.primary, `Результат на ${prettyDate(data.primary.request.event_date)}`));
    if (data.comparison) {
      const change = document.createElement('aside'); change.className = 'change';
      change.innerHTML = `<strong>Что изменила дата</strong><p>${data.availability_changes.text}</p>`;
      results.appendChild(change);
      results.appendChild(renderSet(data.comparison, `Сравнение на ${prettyDate(data.comparison.request.event_date)}`));
    }
  } catch (error) {
    results.innerHTML = ''; errorBox.textContent = error.message; errorBox.hidden = false;
  }
});
