importScripts('collector-local.js', 'collector-policy.js');

let syncing = false;
const SYNC_STATUS = 'gptic:sync-status';

async function postJson(url, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    try {
        const response = await fetch(url, {
            method: 'POST', credentials: 'omit', redirect: 'error',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${GPTIC_CONFIG.token}`
            }, body: JSON.stringify(body), signal: controller.signal
        });
        const result = await response.json().catch(() => null);
        if (!response.ok) {
            const detail = typeof result?.detail === 'string'
                ? result.detail : '전송을 완료하지 못했습니다.';
            const error = new Error(`HTTP ${response.status}: ${detail}`);
            error.status = response.status;
            throw error;
        }
        return result;
    } finally {
        clearTimeout(timeout);
    }
}

async function syncDrafts() {
    if (syncing) return {busy: true};
    syncing = true;
    let sent = 0;
    try {
        const endpoint = GPTIC_CONFIG.endpoint;
        const classifyEndpoint = endpoint.replace(/\/snapshots$/, '/classify');
        for (let count = 0; count < 10; count++) {
            const all = await chrome.storage.local.get(null);
            if (all[GPTIC_POLICY.enabledKey] !== true) break;
            const batch = Object.entries(all).filter(([key, item]) =>
                key.startsWith('gptic:draft:')
                && item?.stage === 'draft'
                && item.identity_checked === true
                && item.source_conversation_id === item.conversation_id
                && !item.synced_at
                && item.classification_state !== 'rejected'
                && all[GPTIC_POLICY.enabledKey] === true
                && item.auto_policy === 1
                && item.snapshot_stable === true
            ).sort((a, b) =>
                String(a[1].captured_at).localeCompare(String(b[1].captured_at))
            ).slice(0, 1);
            if (!batch.length) break;
            const [key, item] = batch[0];
            await chrome.storage.local.set({[SYNC_STATUS]: {
                running: true, at: new Date().toISOString(), sent
            }});

            let current = item;
            if (!current.classification_state) {
                const decision = await postJson(classifyEndpoint, {
                    conversation_id: current.conversation_id,
                    source_conversation_id: current.source_conversation_id,
                    identity_checked: current.identity_checked,
                    question_id: current.question_id,
                    previous_question_id: current.previous_question_id ?? null,
                    question: current.question
                });
                if (decision?.question_id !== current.question_id || typeof decision.accepted !== 'boolean') {
                    throw new Error('서버 질문 분류 응답을 확인하지 못했습니다.');
                }
                current = {
                    ...current,
                    classification_state: decision.accepted ? 'accepted' : 'rejected',
                    classifier_decision: decision.decision,
                    classifier_reason: decision.reason || '',
                    admission_token: decision.accepted ? decision.admission_token : null,
                    classified_at: new Date().toISOString()
                };
                await chrome.storage.local.set({[key]: current});
            }

            if (current.classification_state === 'rejected') {
                continue;
            }
            if (current.classification_state !== 'accepted' || !current.admission_token) {
                throw new Error('서버 승인 토큰을 확인하지 못했습니다.');
            }
            const enabled = await chrome.storage.local.get(GPTIC_POLICY.enabledKey);
            if (enabled[GPTIC_POLICY.enabledKey] !== true) break;

            let result;
            try {
                result = await postJson(endpoint, {snapshots: [{
                conversation_id: current.conversation_id,
                title: String(current.title || 'ChatGPT 대화').slice(0, 255),
                source_conversation_id: current.source_conversation_id,
                identity_checked: current.identity_checked,
                question_id: current.question_id,
                answer_id: current.answer_id,
                question: current.question,
                answer: current.answer,
                content_hash: current.content_hash,
                protocol: 3,
                admission_token: current.admission_token,
                previous_question_id: current.previous_question_id ?? null,
                order_known: current.order_known === true,
                snapshot_stable: true,
                captured_at: current.captured_at
                }]});
            } catch (error) {
                if (error.status === 403) {
                    await chrome.storage.local.set({[key]: {
                        ...current, classification_state: null,
                        classifier_decision: null, classifier_reason: '',
                        admission_token: null, classified_at: null
                    }});
                }
                throw error;
            }
            if (!(result?.acknowledged || []).includes(current.content_hash)) {
                throw new Error('서버 저장 확인이 불완전합니다. 재전송 대기 중입니다.');
            }
            const at = new Date().toISOString();
            await chrome.storage.local.set({
                [key]: {...current, synced_at: at},
                [SYNC_STATUS]: {
                    running: true, at, sent: sent + 1,
                    added: result.added, duplicates: result.duplicates, error: null
                }
            });
            sent++;
        }
        await chrome.storage.local.set({[SYNC_STATUS]: {
            running: false, at: new Date().toISOString(), sent, error: null
        }});
        return {sent};
    } catch (error) {
        try {
            await chrome.storage.local.set({[SYNC_STATUS]: {
                running: false, at: new Date().toISOString(), sent,
                error: error.message
            }});
        } catch {}
        return {error: error.message};
    } finally {
        syncing = false;
    }
}

async function ensureAlarm() {
    if (!await chrome.alarms.get('gptic-sync')) {
        await chrome.alarms.create('gptic-sync', {periodInMinutes: 1});
    }
}

chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === 'gptic-sync') syncDrafts();
});

chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && Object.entries(changes).some(([key, change]) =>
        (key.startsWith('gptic:draft:') && change.newValue && !change.newValue.synced_at)
        || (key === GPTIC_POLICY.enabledKey && change.newValue === true)
    )) syncDrafts();
});

chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (sender.id === chrome.runtime.id && message?.type === 'GPTIC_SYNC_NOW') {
        syncDrafts().then(reply).catch(() => reply({error: '전송 실패'}));
        return true;
    }
});

chrome.runtime.onInstalled.addListener(() => { ensureAlarm(); syncDrafts(); });
chrome.runtime.onStartup.addListener(() => { ensureAlarm(); syncDrafts(); });
ensureAlarm().catch(() => {});
