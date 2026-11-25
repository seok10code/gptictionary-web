function readConversation() {
    const expectedConversationId =
        location.pathname.match(/\/c\/([^/]+)/)?.[1];

    if (!expectedConversationId) {
        throw new Error('대화 주소를 확인할 수 없습니다.');
    }

    function isOnActiveSurface(element) {
        if (element.closest('[hidden], [aria-hidden="true"]')) return false;
        if (!element.getClientRects().length) return false;

        const rect = element.getBoundingClientRect();
        const width =
            document.documentElement.clientWidth || window.innerWidth;

        return rect.width > 0 && rect.height > 0
            && rect.right > 0 && rect.left < width;
    }

    function sourceIds(scope) {
        return [...new Set(Array.from(scope.querySelectorAll(
            '[data-chatgpt-selection-conversation-id]'
        )).filter(isOnActiveSurface).map(node =>
            node.getAttribute('data-chatgpt-selection-conversation-id')
        ).filter(Boolean))];
    }

    const scopes = Array.from(document.querySelectorAll(
        '[data-chatgpt-conversation-selection-target], main'
    )).filter(isOnActiveSurface);

    const valid = scopes.filter(scope => {
        const ids = sourceIds(scope);
        if (ids.length !== 1) return false;
        if (ids[0] === expectedConversationId) return true;

        // The `local-chatgpt:` value is a UI-local selection key, not the
        // canonical /c/<uuid>. Accept it only on the active scope when both
        // sides of a completed exchange are present. Other mismatches remain
        // blocked so stale or unrelated conversations are not uploaded.
        const localUiId = /^local-chatgpt:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(ids[0]);
        return localUiId;    });

    const root = valid.find(scope => !valid.some(
        other => other !== scope && scope.contains(other)
    ));

    if (!root) {
        const found = [...new Set(scopes.flatMap(sourceIds))];
        throw new Error(
            '대화 ID 불일치 또는 로딩 중. '
            + `주소: ${expectedConversationId} / `
            + `본문: ${found.join(', ') || '확인 불가'}`
        );
    }

    // 두 종류를 함께 조회해 화면에 나타난 순서를 유지합니다.
    const nodes = Array.from(root.querySelectorAll(
        '[data-user-message-bubble="true"], '
        + '[data-markdown-text-style="assistant-message"]'
    ));

    const groups = new Map();
    const styleCounts = {};

    function oneSearchId(element) {
        const raw = element.closest(
            '[data-chatgpt-search-message-ids]'
        )?.getAttribute('data-chatgpt-search-message-ids') || '';

        const ids = [...new Set(raw.match(
            /[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/gi
        ) || [])];

        // 여러 ID가 있으면 임의로 하나를 고르지 않습니다.
        return ids.length === 1 ? ids[0] : null;
    }

    function answerImages(element) {
        const owner = element.closest('[data-message-author-role]');
        if (owner && owner.getAttribute('data-message-author-role') !== 'assistant') return [];
        const scope = owner || element;
        return Array.from(scope.querySelectorAll('img')).filter(image =>
            image.closest('[data-message-author-role]') === owner
            && !image.closest('[data-user-message-bubble="true"], button[aria-haspopup="menu"]')
            && isOnActiveSurface(image)
            && image.naturalWidth >= 80 && image.naturalHeight >= 80
        ).map(image => image.currentSrc || image.src).filter(url =>
            url?.startsWith('https://')
        );
    }

    for (const [index, element] of nodes.entries()) {
        if (!isOnActiveSurface(element)) continue;
        const isUser = element.matches(
            '[data-user-message-bubble="true"]'
        );

        // 중첩된 본문은 중복 수집하지 않습니다.
        if (element.parentElement?.closest(
            '[data-user-message-bubble="true"]'
        )) continue;

        if (!isUser && element.parentElement?.closest(
            '[data-markdown-text-style="assistant-message"]'
        )) continue;

        const role = isUser ? 'user' : 'assistant';
        const style = isUser
            ? 'user-message-bubble'
            : 'assistant-message';

        const text = (
            element.innerText ?? element.textContent ?? ''
        ).trim();

        const images = isUser ? [] : answerImages(element);
        if (!text && !isUser && !images.length) continue;

        const owner = element.closest(
            '[data-chatgpt-selection-message-id], [data-message-id]'
        );

        const id = isUser ? oneSearchId(element) : (
            owner?.getAttribute('data-chatgpt-selection-message-id')
            || owner?.getAttribute('data-message-id')
            || null
        );

        styleCounts[style] = (styleCounts[style] || 0) + 1;

        const key = id
            ? `${role}:${id}`
            : `unidentified:${index}`;

        if (!groups.has(key)) {
            groups.set(key, {
                message_id: id,
                role,
                parts: [],
                images: new Set()
            });
        }

        const group = groups.get(key);
        images.forEach(url => group.images.add(url));
        if (text && !group.parts.includes(text)) {
            group.parts.push(text);
        }
    }

    let messages = Array.from(groups.values()).map(group => ({
        message_id: group.message_id,
        role: group.role,
        text: group.parts.join('\n\n'),
        images: [...group.images]
    }));

    if (nodes.length === 0) {
        messages = Array.from(root.querySelectorAll(
            '[data-message-author-role="user"], '
            + '[data-message-author-role="assistant"]'
        )).map(element => {
            const body = element.querySelector('.markdown') || element;

            return {
                message_id: element.closest(
                    '[data-message-id]'
                )?.getAttribute('data-message-id') || null,
                role: element.getAttribute('data-message-author-role'),
                images: answerImages(element),
                text: (
                    body.innerText ?? body.textContent ?? ''
                ).trim()
            };
        }).filter(message => message.role === "user" || message.text || message.images.length);
    }

    return {
        title: document.title,
        conversation_id: expectedConversationId,
        identity_checked: true,
        messages,
        styleCounts,
        domInfo: {
            conversationCheck: {
                urlId: expectedConversationId,
                bodyIds: sourceIds(root),
                bodyIdKind: sourceIds(root)[0] === expectedConversationId
                    ? 'canonical'
                    : 'local-ui'
            },
            order: messages.map(message => message.role),
            missingIds: messages.filter(
                message => !message.message_id
            ).length
        }
    };
}
