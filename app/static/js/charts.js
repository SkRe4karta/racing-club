/* Local SVG charts: no CDN, keyboard focus, data fallback and no network requests. */
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const element = (name, attrs, value) => {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (value !== undefined) node.textContent = value;
    return node;
  };
  document.querySelectorAll('[data-chart]').forEach(container => {
    const data = JSON.parse(container.dataset.chart);
    const points = data.values.map((value, i) => ({value, label: data.labels[i]}));
    if (!points.some(point => point.value !== null)) {
      const empty = document.createElement('p'); empty.className = 'chart-empty';
      empty.textContent = 'Пока нет данных для графика'; container.append(empty); return;
    }
    const svg = element('svg', {viewBox:'0 0 700 250', role:'img', 'aria-label':'График: ' + points.map(p => `${p.label}: ${p.value ?? 'нет оценки'}`).join('; ')});
    const max = Math.max(1, ...points.map(p => p.value || 0));
    const tooltip = document.createElement('div'); tooltip.className = 'chart-tooltip'; tooltip.setAttribute('aria-live','polite');
    tooltip.textContent = 'Наведите курсор или выберите столбец клавишей Tab';
    for (let i = 0; i <= 4; i++) {
      const y = 205 - i * 45;
      svg.append(element('line',{x1:45,x2:690,y1:y,y2:y,stroke:'#393939','stroke-width':1}));
      svg.append(element('text',{x:34,y:y+4,fill:'#b5b5b5','font-size':11,'text-anchor':'end'},Math.round(max*i/4*10)/10));
    }
    const step = 630 / points.length;
    points.forEach((point,index) => {
      const x = 55 + index * step;
      if (point.value !== null) {
        const height = point.value / max * 180;
        const bar = element('rect',{x, y:205-height, width:Math.max(3,step*.62),height:Math.max(2,height),fill:'#91ff79',tabindex:0,role:'img','aria-label':`${point.label}: ${point.value}`,class:'chart-point'});
        const describe = () => { tooltip.textContent = `${point.label}: ${point.value}`; };
        bar.addEventListener('focus',describe);bar.addEventListener('mouseenter',describe);svg.append(bar);
      }
      if (points.length <= 12 || index % Math.ceil(points.length / 8) === 0) svg.append(element('text',{x:x+step*.31,y:230,fill:'#ddd','font-size':10,'text-anchor':'middle'},point.label));
    });
    container.append(svg,tooltip);
  });
  document.querySelectorAll('.prediction-form').forEach(form => {
    const validate = () => {
      const fields = [...form.querySelectorAll('select')];
      fields.forEach(field => field.setCustomValidity(field.value && fields.some(other => other !== field && other.value === field.value) ? 'Выберите три разные лошади' : ''));
    };
    form.addEventListener('change',validate);validate();
  });
})();
