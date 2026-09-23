const form = document.querySelector('#search-form');
const results = document.querySelector('#results');
const errorBox = document.querySelector('#error');
const template = document.querySelector('#card-template');
let meta;

const fill = (name, values) => {
  const select = form.elements[name];
  values.forEach(value => select.add(new Option(value, value)));
};

fetch('/api/meta').then(r => r.json()).then(data => {
  meta = data;
  fill('city', data.cities);
  fill('event_format', data.formats);
  fill('category', data.categories);
  fill('language', data.languages);
  for (const name of ['event_date', 'compare_date']) {
    form.elements[name].min = data.date_min;
    form.elements[name].max = data.date_max;
  }
  form.elements.event_date.value = data.date_min;
  document.querySelector('#range-note').textContent = `Доступный диапазон данных: ${data.date_min} — ${data.date_max}.`;
});

const money = value => new Intl.NumberFormat('ru-RU').format(value);

function rejectionText(item) {
  const r = item.rejections;
  return `Исходно в городе и категории: ${item.base_count}. Не прошли: заняты — ${r.busy}, формат — ${r.format}, бюджет — ${r.budget}, язык — ${r.language}, длительность — ${r.duration}. Причины могут пересекаться.`;
}

function renderSet(item, heading) {
  const section = document.createElement('section');
  section.className = 'result-set';
  section.innerHTML = `<p class="eyebrow">${heading}</p><h2>${item.summary}</h2><p class="counts">${rejectionText(item)}</p>`;
  const grid = document.createElement('div');
  grid.className = 'cards';
  item.recommendations.forEach(rec => {
    const card = template.content.cloneNode(true);
    card.querySelector('h3').textContent = rec.name;
    card.querySelector('.category').textContent = rec.matching_category;
    card.querySelector('.city').textContent = rec.city;
    card.querySelector('.price').textContent = `от ${money(rec.price_from_kzt)} ₸`;
    card.querySelector('.score').textContent = `${rec.relevance_score} баллов`;
    card.querySelector('.explanation').textContent = rec.explanation;
    const badges = card.querySelector('.badges');
    const labels = [
      rec.synthetic && 'Синтетический профиль',
      rec.city_imputed && 'Город восстановлен',
      rec.price_imputed && 'Цена восстановлена',
    ].filter(Boolean);
    labels.forEach(label => {
      const badge = document.createElement('span');
      badge.textContent = label;
      badges.appendChild(badge);
    });
    grid.appendChild(card);
  });
  section.appendChild(grid);
  return section;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  errorBox.hidden = true;
  results.innerHTML = '<p class="loading">Проверяем условия и календари…</p>';
  const payload = Object.fromEntries(new FormData(form));
  if (!payload.duration_hours) delete payload.duration_hours;
  if (!payload.language) delete payload.language;
  if (!payload.compare_date) delete payload.compare_date;
  if (!payload.wishes) delete payload.wishes;
  try {
    const response = await fetch('/api/recommend', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось получить рекомендации');
    results.innerHTML = '';
    results.appendChild(renderSet(data.primary, `Результат на ${data.primary.request.event_date}`));
    if (data.comparison) {
      const change = document.createElement('aside');
      change.className = 'change';
      change.innerHTML = `<strong>Что изменила дата</strong><p>${data.availability_changes.text}</p>`;
      results.appendChild(change);
      results.appendChild(renderSet(data.comparison, `Сравнение на ${data.comparison.request.event_date}`));
    }
  } catch (error) {
    results.innerHTML = '';
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  }
});
