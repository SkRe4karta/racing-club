(() => {
  let saved;
  try { saved = localStorage.getItem('racing-theme'); } catch (_) {}
  document.documentElement.dataset.theme = ['light','dark'].includes(saved) ? saved : matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
})();
