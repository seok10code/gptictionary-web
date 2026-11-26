(() => {
    const section = document.querySelector('[data-note-images]');
    const dialog = section?.querySelector('dialog');
    if (typeof dialog?.showModal !== 'function') return;

    const image = dialog.querySelector('img');
    section.addEventListener('click', event => {
        const link = event.target.closest('.nd-image-preview');
        if (!link || event.defaultPrevented || event.button !== 0
            || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;

        event.preventDefault();
        image.alt = link.querySelector('img').alt;
        image.src = link.href;
        dialog.showModal();
    });

    dialog.addEventListener('click', event => {
        if (event.target !== dialog) return;
        const bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right
            || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });

    dialog.addEventListener('close', () => image.removeAttribute('src'));
})();
