// Скрипт динамического добавления участников в формах состязаний

function addParticipantRow(containerId, templateId) {
    const container = document.getElementById(containerId);
    const template = document.getElementById(templateId);
    if (!container || !template) return;

    const clone = template.content.cloneNode(true);
    const rowIndex = container.querySelectorAll('.participant-row').length;
    
    // Обновляем атрибуты name и id, если есть суффиксы индексов
    const disqCheckboxes = clone.querySelectorAll('.disq-checkbox');
    disqCheckboxes.forEach(cb => {
        cb.name = `disq_${rowIndex}`;
        cb.id = `disq_${rowIndex}`;
        const label = clone.querySelector(`label[for="${cb.id}"]`) || clone.querySelector('.disq-label');
        if (label) label.htmlFor = `disq_${rowIndex}`;
    });

    container.appendChild(clone);
    updateRowNumbers();
}

function removeParticipantRow(button) {
    const row = button.closest('.participant-row');
    const container = row.parentElement;
    if (container.querySelectorAll('.participant-row').length > 1) {
        row.remove();
        updateRowNumbers();
    } else {
        alert("В состязании должен оставаться хотя бы один участник.");
    }
}

function updateRowNumbers() {
    const rows = document.querySelectorAll('.participant-row');
    rows.forEach((row, idx) => {
        const numElem = row.querySelector('.row-number');
        if (numElem) {
            numElem.textContent = idx + 1;
        }
        const cb = row.querySelector('.disq-checkbox');
        if (cb) {
            cb.name = `disq_${idx}`;
            cb.id = `disq_${idx}`;
            const label = row.querySelector('.disq-label');
            if (label) label.htmlFor = `disq_${idx}`;
        }
    });
}

function toggleTimeInput(checkbox) {
    const row = checkbox.closest('.participant-row');
    const timeInput = row.querySelector('.time-input');
    if (timeInput) {
        if (checkbox.checked) {
            timeInput.value = '';
            timeInput.readOnly = true;
            timeInput.placeholder = 'Дисквалифицирован';
        } else {
            timeInput.readOnly = false;
            timeInput.placeholder = 'например 02:04.50';
        }
    }
}
