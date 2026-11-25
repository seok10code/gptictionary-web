importScripts('collector-local.js', 'collector-policy.js');

let syncing = false;
const activeImageUploads = new Set();
const SYNC_STATUS = 'gptic:sync-status';
const CLASSIFIER_POLICY_VERSION = 3;

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

async function syncAnswerImages(key, item) {
    if (activeImageUploads.has(key) || !item.image_source_id || !item.images?.length) return;
    activeImageUploads.add(key);
    try {
        const endpoint = GPTIC_CONFIG.endpoint.replace(
            /\/snapshots$/, `/sources/${item.image_source_id}/images`
        );
        const pending = [];
        for (const url of item.images) {
            try {
                const host = new URL(url).hostname;
                const chatgptHost = host === 'chatgpt.com' || host === 'chat.openai.com';
                const response = await fetch(url, {
                    credentials: chatgptHost ? 'include' : 'omit',
                    signal: AbortSignal.timeout(15000)
                });
                if (!response.ok) {
                    if (response.status === 429 || response.status >= 500) pending.push(url);
                    continue;
                }
                if (Number(response.headers.get('Content-Length')) > 8 * 1024 * 1024) {
                    await response.body?.cancel();
                    continue;
                }
                const image = await response.blob();
                if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/svg+xml'].includes(image.type.split(';')[0])
                    || image.size > 8 * 1024 * 1024) continue;
                const upload = await fetch(endpoint, {
                    method: 'POST', credentials: 'omit', redirect: 'error',
                    headers: {Authorization: `Bearer ${GPTIC_CONFIG.token}`},
                    body: image, signal: AbortSignal.timeout(20000)
                });
                if (!upload.ok && upload.status !== 413 && upload.status !== 415) pending.push(url);
            } catch {
                pending.push(url);
            }
        }
        const nextAttempt = (item.image_attempts || 0) + 1;
        const stored = (await chrome.storage.local.get(key))[key];
        if (stored?.image_source_id === item.image_source_id) {
            await chrome.storage.local.set({[key]: {
                ...stored, images: nextAttempt < 3 ? pending : [], image_attempts: nextAttempt
            }});
        }
    } finally {
        activeImageUploads.delete(key);
    }
}

function scheduleAnswerImages(key, item) {
    syncAnswerImages(key, item).catch(error => console.warn('답변 이미지 전송 실패', error.message));
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
                && (item.classification_state !== 'rejected'
                    || (item.classifier_policy_version !== CLASSIFIER_POLICY_VERSION && Boolean(item.previous_question_id)))
                && all[GPTIC_POLICY.enabledKey] === true
                && item.auto_policy === 1
                && item.snapshot_stable === true
            ).sort((a, b) =>
                String(a[1].captured_at).localeCompare(String(b[1].captured_at))
            ).slice(0, 1);
            if (!batch.length) break;
            const [key, item] = batch[0];
            // ACKNOWLEDGED_MESSAGE_HISTORY_DEDUPE_V2_20261123
            // A history rescan may yield a different body hash for the same
            // ChatGPT message IDs. An acknowledged Q/A pair is already saved.
            const alreadySent = Object.entries(all).find(([otherKey, other]) =>
                otherKey !== key
                && otherKey.startsWith('gptic:draft:')
                && other?.conversation_id === item.conversation_id
                && other?.question_id === item.question_id
                && other?.answer_id === item.answer_id
                && other?.question === item.question
                && Boolean(other?.synced_at)
            )?.[1];
            if (alreadySent) {
                await chrome.storage.local.set({[key]: {
                    ...item,
                    classification_state: alreadySent.classification_state,
                    classifier_decision: alreadySent.classifier_decision,
                    classifier_reason: alreadySent.classifier_reason || '',
                    admission_token: alreadySent.admission_token || null,
                    classifier_policy_version: alreadySent.classifier_policy_version,
                    classified_at: alreadySent.classified_at,
                    synced_at: alreadySent.synced_at
                }});
                continue;
            }
            await chrome.storage.local.set({[SYNC_STATUS]: {
                running: true, at: new Date().toISOString(), sent
            }});

            let current = item;
            // CLASSIFICATION_DECISION_REUSE_20261123: history scans can
            // produce another content hash for the same question/answer IDs.
            // Classification depends on the question and predecessor, not the
            // answer body, so reuse the terminal decision for that same context.
            const sibling = Object.entries(all).find(([otherKey, other]) =>
                otherKey !== key
                && otherKey.startsWith('gptic:draft:')
                && other?.conversation_id === current.conversation_id
                && other?.question_id === current.question_id
                && other?.question === current.question
                && other?.previous_question_id === current.previous_question_id
                && other?.classifier_policy_version === CLASSIFIER_POLICY_VERSION
                && (other?.classification_state === 'accepted'
                    || other?.classification_state === 'rejected')
                && (other.classification_state === 'rejected' || Boolean(other.admission_token))
            )?.[1];
            if ((!current.classification_state
                    || current.classifier_policy_version !== CLASSIFIER_POLICY_VERSION)
                && sibling) {
                current = {
                    ...current,
                    classification_state: sibling.classification_state,
                    classifier_decision: sibling.classifier_decision,
                    classifier_reason: sibling.classifier_reason || '',
                    admission_token: sibling.admission_token || null,
                    classifier_policy_version: CLASSIFIER_POLICY_VERSION,
                    previous_question_id: sibling.previous_question_id ?? current.previous_question_id ?? null,
                    classified_at: sibling.classified_at || new Date().toISOString()
                };
                await chrome.storage.local.set({[key]: current});
            }
            if (!current.classification_state
                || current.classifier_policy_version !== CLASSIFIER_POLICY_VERSION) {
                const decision = await postJson(classifyEndpoint, {
                    conversation_id: current.conversation_id,
                    source_conversation_id: current.source_conversation_id,
                    identity_checked: current.identity_checked,
                    question_id: current.question_id,
                    previous_question_id: current.previous_question_id ?? null,
                    question: current.question,
                    answer: current.answer
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
                    classifier_policy_version: CLASSIFIER_POLICY_VERSION,
                    previous_question_id: decision.accepted && decision.decision === 'followup'
                        ? (decision.previous_question_id ?? current.previous_question_id ?? null)
                        : (current.previous_question_id ?? null),
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
                // Only a GPT-confirmed follow-up depends on an earlier job.
                // Direct requests must not be blocked by a rejected question.
                previous_question_id: current.classifier_decision === 'followup'
                    ? (current.previous_question_id ?? null) : null,
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
            const synced = {...current, synced_at: at, image_source_id: result.source_ids?.[0]};
            await chrome.storage.local.set({
                [key]: synced,
                [SYNC_STATUS]: {
                    running: true, at, sent: sent + 1,
                    added: result.added, duplicates: result.duplicates, error: null
                }
            });
            scheduleAnswerImages(key, synced);
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

// GPTIC_WAKE_RECOVERY_V1
const recoveryAt = new Map();
async function requestPageCapture(tabId) {
    if (!Number.isInteger(tabId)) return;
    const now = Date.now();
    if (now - (recoveryAt.get(tabId) || 0) < 3000) return;

    const enabled = await chrome.storage.local.get(GPTIC_POLICY.enabledKey);
    if (enabled[GPTIC_POLICY.enabledKey] !== true) return;
    let tab;
    try { tab = await chrome.tabs.get(tabId); } catch { return; }
    let url;
    try { url = new URL(tab.url || ''); } catch { return; }
    if (!['chatgpt.com', 'chat.openai.com'].includes(url.hostname)
        || url.protocol !== 'https:' || !/\/c\/[^/]+/.test(url.pathname)) return;

    recoveryAt.set(tabId, now);
    try {
        await chrome.tabs.sendMessage(tabId, {type: 'GPTIC_CAPTURE_NOW'});
        return;
    } catch {
        // A discarded or stale tab may no longer have the content script.
    }
    try {
        await chrome.scripting.executeScript({
            target: {tabId},
            files: ['collector-read.js', 'collector-policy.js', 'collector-auto.js']
        });
        await chrome.tabs.sendMessage(tabId, {type: 'GPTIC_CAPTURE_NOW'});
    } catch {
        // The tab may be navigating; focus/update events will retry.
    }
}

async function recoverActiveChatTab(windowId = null) {
    try {
        const query = windowId && windowId !== chrome.windows.WINDOW_ID_NONE
            ? {active: true, windowId}
            : {active: true, lastFocusedWindow: true};
        const [tab] = await chrome.tabs.query(query);
        if (tab?.id != null) await requestPageCapture(tab.id);
    } catch {}
}

async function ensureAlarm() {
    if (!await chrome.alarms.get('gptic-sync')) {
        await chrome.alarms.create('gptic-sync', {periodInMinutes: 1});
    }
}

chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === 'gptic-sync') {
        void syncDrafts();
        void recoverActiveChatTab();
        chrome.storage.local.get(null).then(items => {
            if (items[GPTIC_POLICY.enabledKey] !== true) return;
            const pending = Object.entries(items).filter(([key, item]) =>
                key.startsWith('gptic:draft:') && item?.image_source_id && item.images?.length
            );
            for (const [key, item] of pending.slice(0, 4)) scheduleAnswerImages(key, item);
        });
    }
});

chrome.tabs.onActivated.addListener(({tabId}) => { void requestPageCapture(tabId); });
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (changeInfo.status === 'complete' || changeInfo.url) void requestPageCapture(tabId);
});
chrome.windows.onFocusChanged.addListener(windowId => {
    if (windowId !== chrome.windows.WINDOW_ID_NONE) void recoverActiveChatTab(windowId);
});

chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && Object.entries(changes).some(([key, change]) =>
        (key.startsWith('gptic:draft:') && change.newValue && !change.newValue.synced_at)
        || (key === GPTIC_POLICY.enabledKey && change.newValue === true)
    )) syncDrafts();
});

chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (sender.id !== chrome.runtime.id) return;
    if (message?.type === 'GPTIC_SYNC_NOW') {
        syncDrafts().then(reply).catch(() => reply({error: '전송 실패'}));
        return true;
    }
    if (message?.type === 'GPTIC_CAPTURE_ACTIVE_TAB') {
        recoverActiveChatTab().then(() => reply({ok: true})).catch(() => reply({ok: false}));
        return true;
    }
});

chrome.runtime.onInstalled.addListener(() => { ensureAlarm(); syncDrafts(); recoverActiveChatTab(); });
chrome.runtime.onStartup.addListener(() => { ensureAlarm(); syncDrafts(); recoverActiveChatTab(); });
ensureAlarm().catch(() => {});
