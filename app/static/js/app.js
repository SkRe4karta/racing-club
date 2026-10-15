(() => {
  const toggle = document.querySelector('#theme-toggle');
  const media = matchMedia('(prefers-color-scheme: dark)');
  const updateThemeLabel = () => { toggle.setAttribute('aria-label', document.documentElement.dataset.theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'); };
  updateThemeLabel();
  toggle.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('racing-theme', theme); } catch (_) {}
    updateThemeLabel();
  });
  media.addEventListener('change', e => { let saved; try { saved = localStorage.getItem('racing-theme'); } catch (_) {} if (!saved) { document.documentElement.dataset.theme = e.matches ? 'dark' : 'light'; updateThemeLabel(); } });
  const menu = document.querySelector('.menu-toggle'), sidebar = document.querySelector('.sidebar'), shade = document.querySelector('.menu-shade');
  function closeMenu() { sidebar.classList.remove('open'); menu.setAttribute('aria-expanded','false'); shade.hidden = true; if (innerWidth <= 900) sidebar.inert = true; }
  function syncMenu() { sidebar.inert = innerWidth <= 900 && !sidebar.classList.contains('open'); }
  syncMenu(); addEventListener('resize', syncMenu);
  menu.addEventListener('click', () => { if (sidebar.classList.contains('open')) { closeMenu(); return; } sidebar.inert = false; sidebar.classList.add('open'); shade.hidden = false; menu.setAttribute('aria-expanded','true'); sidebar.querySelector('a').focus(); });
  shade.addEventListener('click', closeMenu);
  document.addEventListener('keydown', e => { if (sidebar.classList.contains('open')) { if (e.key === 'Escape') { closeMenu(); menu.focus(); } if (e.key === 'Tab') { const links = [...sidebar.querySelectorAll('a')]; const first = links[0], last = links.at(-1); if(e.shiftKey && document.activeElement === first) {e.preventDefault(); last.focus();} else if(!e.shiftKey && document.activeElement === last) {e.preventDefault(); first.focus();} } } });
  const parseTime = value => {
    value = value.trim().replace(',', '.');
    if (!/^(?:\d+:)?\d+(?:\.\d+)?$/.test(value)) return false;
    const parts = value.split(':');
    if (parts.length === 2 && Number(parts[1]) >= 60) return false;
    const seconds = parts.length === 2 ? Number(parts[0]) * 60 + Number(parts[1]) : Number(value);
    return Number.isFinite(seconds) && Math.round(seconds * 100) > 0;
  };
  function validateRows() {
    const forms = document.querySelectorAll('form[method="POST"]');
    forms.forEach(form => {
      const horses = new Set(), jockeys = new Set();
      form.querySelectorAll('.participant-row').forEach((row, index) => {
        row.querySelectorAll('select, .time-input').forEach((input, fieldIndex) => {
          if (!input.id) input.id = `participant-${index}-${fieldIndex}`;
          const label = input.parentElement.querySelector('label');
          if (label) label.htmlFor = input.id;
        });
        const horse = row.querySelector('[name="horse_id[]"]'), jockey = row.querySelector('[name="jockey_id[]"]');
        let message = '';
        for (const [input, seen, label] of [[horse,horses,'Лошадь'],[jockey,jockeys,'Жокей']]) {
          if (!input) continue;
          const duplicate = input.value && seen.has(input.value);
          input.setCustomValidity(duplicate ? `${label} уже выбран в другой строке` : '');
          if (duplicate) message = `${label} уже выбран в другой строке`;
          if (input.value) seen.add(input.value);
        }
        const time = row.querySelector('.time-input'), dq = row.querySelector('.disq-checkbox');
        if (time) {
          if (!time.getAttribute('aria-label')) time.setAttribute('aria-label',`Время участника ${index+1}`);
          time.required = !dq?.checked;
          const valid = dq?.checked ? !time.value.trim() : parseTime(time.value);
          const error = valid ? '' : 'Укажите время: 124.50 или 02:04.50, либо дисквалификацию';
          time.setCustomValidity(error);
          if (error && !message) message = error;
        }
        let feedback = row.querySelector('.row-feedback');
        if (!feedback) { feedback = document.createElement('div'); feedback.className = 'row-feedback'; feedback.id = `feedback-${index}`; feedback.setAttribute('aria-live','polite'); if (row.tagName === 'TR') row.querySelector('td:has(.time-input)').append(feedback); else row.append(feedback); }
        feedback.textContent = message || (time ? 'Результат заполнен' : 'Выберите пару «лошадь — жокей»');
        feedback.classList.toggle('invalid', !!message);
        if (time) time.setAttribute('aria-describedby', feedback.id);
      });
      const count = form.querySelectorAll('.participant-row').length;
      if (count && !form.querySelector('.participant-count')) { const label = document.createElement('p'); label.className = 'small text-muted participant-count'; form.prepend(label); }
      if (form.querySelector('.participant-count')) form.querySelector('.participant-count').textContent = `Участников: ${count}`;
    });
  }
  document.addEventListener('input', validateRows); document.addEventListener('change', validateRows);
  new MutationObserver(validateRows).observe(document.querySelector('main'), {childList:true});
  document.querySelectorAll('[id$="participants-container"]').forEach(el => new MutationObserver(validateRows).observe(el,{childList:true}));
  validateRows();
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('button[data-original-label]').forEach(button => {
      button.disabled = false;
      button.textContent = button.dataset.originalLabel;
      button.removeAttribute('aria-busy');
    });
  });
  document.querySelectorAll('form[method="POST"]').forEach(form => form.addEventListener('submit', e => {
    validateRows();
    if (!form.checkValidity()) {e.preventDefault();form.reportValidity();return;}
    const button = form.querySelector('[type="submit"]');
    if (button) { button.disabled = true; button.dataset.originalLabel = button.textContent; button.textContent = 'Сохранение…'; button.setAttribute('aria-busy','true'); }
  }));
})();
