(() => {
  let saved;
  try { saved = localStorage.getItem('racing-theme'); } catch (_) {}
  document.documentElement.dataset.theme = ['light','dark'].includes(saved) ? saved : 'dark';
})();
