(() => {
  const picker = document.querySelector('.nm-date-picker');
  if (!picker) return;
  const form = picker.closest('form');
  const field = picker.querySelector('input[name="day"]');
  const trigger = picker.querySelector('.nm-calendar-trigger');
  const panel = picker.querySelector('.nm-calendar');
  const grid = picker.querySelector('.nm-calendar-grid');
  const heading = picker.querySelector('[data-calendar-heading]');
  const endpoint = picker.dataset.calendarUrl;
  const weekdays = ['일', '월', '화', '수', '목', '금', '토'];
  const cache = new Map();
  const initial = field.value ? new Date(`${field.value}T12:00:00`) : new Date();
  let cursor = new Date(initial.getFullYear(), initial.getMonth(), 1);
  const dateKey = (year, month, day) => `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  const close = () => { panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); };

  async function render() {
    const year = cursor.getFullYear();
    const month = cursor.getMonth();
    const cacheKey = `${year}-${month + 1}`;
    let counts = cache.get(cacheKey);
    if (!counts) {
      try {
        const response = await fetch(`${endpoint}?year=${year}&month=${month + 1}`, { headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error('calendar request failed');
        counts = (await response.json()).days || {};
        cache.set(cacheKey, counts);
      } catch (_) { counts = {}; }
    }
    heading.textContent = `${year}년 ${month + 1}월`;
    grid.replaceChildren();
    weekdays.forEach((label) => {
      const cell = document.createElement('span');
      cell.className = 'nm-calendar-weekday'; cell.setAttribute('role', 'columnheader'); cell.textContent = label; grid.append(cell);
    });
    const offset = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const today = new Date();
    for (let i = 0; i < offset; i += 1) {
      const blank = document.createElement('span'); blank.className = 'nm-calendar-blank'; blank.setAttribute('role', 'gridcell'); grid.append(blank);
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      const key = dateKey(year, month, day); const count = counts[key] || 0;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'nm-calendar-day';
      button.setAttribute('role', 'gridcell'); button.textContent = String(day);
      button.setAttribute('aria-label', `${year}년 ${month + 1}월 ${day}일${count ? `, 수정된 노트 ${count}개` : ''}`);
      if (count) button.classList.add('has-notes');
      if (field.value === key) button.classList.add('selected');
      if (today.getFullYear() === year && today.getMonth() === month && today.getDate() === day) button.classList.add('today');
      button.addEventListener('click', () => { field.value = key; form.requestSubmit(); }); grid.append(button);
    }
  }
  trigger.addEventListener('click', async () => {
    const opening = panel.hidden; panel.hidden = !opening; trigger.setAttribute('aria-expanded', String(opening));
    if (opening) await render();
  });
  picker.querySelectorAll('[data-month-step]').forEach((button) => button.addEventListener('click', () => {
    cursor.setMonth(cursor.getMonth() + Number(button.dataset.monthStep)); render();
  }));
  document.addEventListener('click', (event) => { if (!picker.contains(event.target)) close(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !panel.hidden) { close(); trigger.focus(); } });
})();
