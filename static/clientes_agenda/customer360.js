(() => {
    const containers = document.querySelectorAll('[data-history-container]');

    containers.forEach((container) => {
        container.addEventListener('click', async (event) => {
            const button = event.target.closest('[data-history-next]');
            if (!button || !container.contains(button)) return;

            event.preventDefault();
            button.setAttribute('aria-busy', 'true');
            try {
                const response = await fetch(button.href, {
                    method: 'GET',
                    headers: { 'Accept': 'text/html' },
                    credentials: 'same-origin',
                });
                if (!response.ok) throw new Error('history request failed');
                const html = await response.text();
                const parsed = new DOMParser().parseFromString(html, 'text/html');
                const nextItems = parsed.querySelector('[data-history-items]');
                if (!nextItems) throw new Error('history response missing items');

                const items = container.querySelector('[data-history-items]');
                items.insertAdjacentHTML('beforeend', nextItems.innerHTML);
                const nextButton = parsed.querySelector('[data-history-next]');
                if (nextButton) {
                    button.replaceWith(nextButton);
                } else {
                    button.remove();
                }
            } catch (_error) {
                button.removeAttribute('aria-busy');
                button.textContent = 'Tentar carregar novamente';
            }
        });
    });
})();
