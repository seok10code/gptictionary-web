importScripts('collector-local.js', 'collector-policy.js');

let syncing = false;
const SYNC_STATUS = 'gptic:sync-status';

async function syncDrafts() {
    if (syncing) return {busy: true};
    syncing = true;

    try {
        const all = await chrome.storage.local.get(null);

        const batch = Object.entries(all).filter(([key, item]) =>
            key.startsWith('gptic:draft:')
            && item?.stage === 'draft'
            && item.identity_checked === true
            && item.source_conversation_id === item.conversation_id
            && !item.synced_at
            && all[GPTIC_POLICY.enabledKey] === true
            && item.auto_policy === 1
        ).sort((a, b) =>
            String(a[1].captured_at).localeCompare(
                String(b[1].captured_at)
            )
        ).slice(0, 10);

        if (!batch.length) return {sent: 0};

        await chrome.storage.local.set({
            [SYNC_STATUS]: {
                running: true,
                at: new Date().toISOString()
            }
        });

        const snapshots = batch.map(([, item]) => ({
            conversation_id: item.conversation_id,
            title: item.title.slice(0, 255),
            source_conversation_id: item.source_conversation_id,
            identity_checked: item.identity_checked,
            question_id: item.question_id,
            answer_id: item.answer_id,
            question: item.question,
            answer: item.answer,
            content_hash: item.content_hash,
            protocol: item.protocol === 2 ? 2 : 1,
            previous_question_id: item.previous_question_id ?? null,
            order_known: item.protocol === 2 && item.order_known === true,
            snapshot_stable: item.protocol === 2 && item.snapshot_stable === true,
            captured_at: item.captured_at
        }));

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        let response;

        try {
            if ((await chrome.storage.local.get(GPTIC_POLICY.enabledKey))[GPTIC_POLICY.enabledKey] !== true) return {sent: 0};
            response = await fetch(GPTIC_CONFIG.endpoint, {
                method: 'POST',
                credentials: 'omit',
                redirect: 'error',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${GPTIC_CONFIG.token}`
                },
                body: JSON.stringify({snapshots}),
                signal: controller.signal
            });
        } finally {
            clearTimeout(timeout);
        }

        const result = await response.json().catch(() => null);

        if (!response.ok) {
            const detail = typeof result?.detail === 'string'
                ? result.detail
                : '전송을 완료하지 못했습니다.';
            throw new Error(`HTTP ${response.status}: ${detail}`);
        }

        const acknowledged = new Set(result?.acknowledged || []);

        if (!batch.every(([, item]) =>
            acknowledged.has(item.content_hash)
        )) {
            throw new Error('서버 저장 확인이 불완전합니다. 재전송 대기 중입니다.');
        }

        const at = new Date().toISOString();
        const updates = {};

        for (const [key, item] of batch) {
            updates[key] = {...item, synced_at: at};
        }

        updates[SYNC_STATUS] = {
            running: false,
            at,
            sent: batch.length,
            added: result.added,
            duplicates: result.duplicates,
            error: null
        };

        await chrome.storage.local.set(updates);
        return {sent: batch.length};

    } catch (error) {
        try {
            await chrome.storage.local.set({
                [SYNC_STATUS]: {
                    running: false,
                    at: new Date().toISOString(),
                    error: error.message
                }
            });
        } catch {}

        return {error: error.message};

    } finally {
        syncing = false;
    }
}

async function ensureAlarm() {
    if (!await chrome.alarms.get('gptic-sync')) {
        await chrome.alarms.create(
            'gptic-sync', {periodInMinutes: 1}
        );
    }
}

chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === 'gptic-sync') syncDrafts();
});

chrome.storage.onChanged.addListener((changes, area) => {
    if (
        area === 'local'
        && Object.entries(changes).some(([key, change]) =>
            (
                key.startsWith('gptic:draft:')
                && change.newValue
                && !change.newValue.synced_at
            )
            || (
                key === GPTIC_POLICY.enabledKey
                && change.newValue === true
            )
        )
    ) syncDrafts();
});

chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (
        sender.id === chrome.runtime.id
        && message?.type === 'GPTIC_SYNC_NOW'
    ) {
        syncDrafts().then(reply).catch(
            () => reply({error: '전송 실패'})
        );
        return true;
    }
});

chrome.runtime.onInstalled.addListener(() => {
    ensureAlarm();
    syncDrafts();
});

chrome.runtime.onStartup.addListener(() => {
    ensureAlarm();
    syncDrafts();
});

ensureAlarm().catch(() => {});
