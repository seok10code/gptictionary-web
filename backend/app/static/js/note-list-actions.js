(() => {
  document.addEventListener('submit', (event) => {
    const allForm = event.target.closest('[data-delete-all-notes]');
    if (allForm) {
      event.preventDefault();
      const confirmation = window.prompt(
        '모든 영어 노트를 삭제합니다. 원문 대화는 보존됩니다. 계속하려면 전체삭제를 입력하세요.'
      );
      if (confirmation !== '전체삭제') return;
      if (!window.confirm('노트와 노트별 학습 기록을 영구 삭제할까요? 되돌릴 수 없습니다.')) return;
      HTMLFormElement.prototype.submit.call(allForm);
      return;
    }
    const oneForm = event.target.closest('[data-delete-one-note]');
    if (oneForm && !window.confirm('이 노트를 삭제할까요? 원문 대화는 보존됩니다.')) {
      event.preventDefault();
    }
  });

  document.addEventListener('click', (event) => {
    document.querySelectorAll('.nm-note-menu[open]').forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.nm-note-menu[open]').forEach((menu) => {
      menu.open = false;
      menu.querySelector('summary')?.focus();
    });
  });
})();
