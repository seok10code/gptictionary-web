(() => {
    if (globalThis.__gptictionaryWatching) return;
    globalThis.__gptictionaryWatching = true;
    let timer, busy = false;
    const quietHashes = new Map();
    const conversationId = () => location.pathname.match(/\/c\/([^/]+)/)?.[1];
    const streaming = () => Boolean(document.querySelector(
        '[data-is-streaming="true"], [data-testid="stop-button"], '
        + '[data-testid="stop-generating-button"], [data-talvt-turn-state="streaming"]'
    ));
    async function capture() {
        if (busy) return;
        busy = true;
        let cid;
        try {
            cid = conversationId();
            if (!cid) return;
            const enabled = await chrome.storage.local.get(GPTIC_POLICY.enabledKey);
            if (enabled[GPTIC_POLICY.enabledKey] !== true || conversationId() !== cid) return;
            const data = readConversation();
            if (!data.identity_checked || data.conversation_id !== cid) throw new Error('주소와 본문의 대화 ID가 다릅니다.');
            const groups = [];
            let group = null;
            for (const message of data.messages) {
                if (message.role === 'user') {
                    group = {question: message, answers: []};
                    groups.push(group);
                } else if (message.role === 'assistant' && group && message.message_id) {
                    group.answers.push(message);
                }
            }
            const pairs = groups.filter(g => g.question.message_id && g.answers.length);
            const selected = GPTIC_POLICY.select(pairs);
            const records = {};
            let previous = null;
            let latestHash = null, latestReady = false, latestEligible = null;
            const newest = groups.at(-1);
            const newestQuestionId = newest?.question.message_id;
            for (const [index, pair] of pairs.entries()) {
                const answer = pair.answers.map(m => m.text).join('\n\n');
                const answerId = pair.answers.at(-1).message_id;
                const raw = JSON.stringify([cid, pair.question.message_id, answerId, pair.question.text, answer]);
                const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
                const hash = [...new Uint8Array(bytes)].map(n => n.toString(16).padStart(2, '0')).join('');
                const firstSeen = quietHashes.get(hash) ?? Date.now();
                quietHashes.set(hash, firstSeen);
                const stable = Date.now() - firstSeen >= 12000 && !(index === pairs.length-1 && streaming());
                if (pair.question.message_id === newestQuestionId) {
                    latestHash = hash;
                    latestReady = stable;
                    latestEligible = selected[index];
                }
                if (stable && selected[index]) {
                    records[`gptic:draft:${cid}:${hash}`] = {
                        conversation_id: cid, source_conversation_id: cid, identity_checked: true,
                        title: data.title, question_id: pair.question.message_id, answer_id: answerId,
                        question: pair.question.text, answer, captured_at: new Date().toISOString(),
                        stage: 'draft', auto_policy: 1, content_hash: hash, protocol: 3,
                        previous_question_id: previous, order_known: true, snapshot_stable: true
                    };
                }
                if (selected[index]) previous = pair.question.message_id;
            }
            while (quietHashes.size > 1000) quietHashes.delete(quietHashes.keys().next().value);
            if (conversationId() !== cid || (await chrome.storage.local.get(GPTIC_POLICY.enabledKey))[GPTIC_POLICY.enabledKey] !== true) return;
            const keys = Object.keys(records);
            const existing = keys.length ? await chrome.storage.local.get(keys) : {};
            const additions = {};
            for (const [key, value] of Object.entries(records)) {
                const old = existing[key];
                const linkChanged = old && (
                    old.previous_question_id !== value.previous_question_id
                    || old.order_known !== value.order_known
                );
                if (!old || old.auto_policy !== 1 || old.protocol !== 3
                    || !old.snapshot_stable || linkChanged) {
                    // Changed order metadata must reach the server even if the
                    // unchanged question/answer was previously acknowledged.
                    additions[key] = {
                        ...value,
                        ...(!linkChanged && old ? {
                            ...(old.classification_state ? {
                                classification_state: old.classification_state,
                                classifier_decision: old.classifier_decision,
                                classifier_reason: old.classifier_reason,
                                admission_token: old.admission_token
                            } : {}),
                            ...(old.synced_at ? {synced_at: old.synced_at} : {})
                        } : {})
                    };
                }
            }
            if (Object.keys(additions).length) await chrome.storage.local.set(additions);
            await chrome.storage.local.set({[`gptic:status:${cid}`]: {
                at: new Date().toISOString(), questions: groups.length,
                answers: data.messages.filter(m => m.role === 'assistant').length,
                paired: pairs.length, eligible: selected.filter(Boolean).length, newSnapshots: Object.keys(additions).length,
                missingIds: data.domInfo.missingIds, error: null,
                latestQuestion: newest?.question.text.slice(0, 500) || '',
                latestQuestionId: newest?.question.message_id || null,
                latestHash, latestReady, latestEligible,
                latestStreaming: streaming()
            }});
        } catch (error) {
            if (cid) try { await chrome.storage.local.set({[`gptic:status:${cid}`]: {at: new Date().toISOString(), error: error.message}}); } catch {}
        } finally { busy = false; }
    }
    function schedule() { clearTimeout(timer); timer = setTimeout(capture, 2500); }
    new MutationObserver(schedule).observe(document.body, {childList: true, subtree: true, characterData: true});
    chrome.storage.onChanged.addListener((changes, area) => {
        if (area === 'local' && Object.keys(changes).some(k => k === GPTIC_POLICY.enabledKey)) schedule();
    });
    setInterval(capture, 10000);
    schedule();
})();
