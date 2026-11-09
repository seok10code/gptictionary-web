(() => {
    const el = id => document.getElementById(id);
    const toggle = el('auto');
    let refreshing = false, rerun = false, currentCid = null;
    function text(id, value) {
        if (el(id).textContent !== value) el(id).textContent = value;
    }
    const time = at => at && Number.isFinite(Date.parse(at))
        ? new Date(at).toLocaleString('ko-KR', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}) : '시간 확인 불가';
    const short = q => String(q || '(질문 없음)').replace(/\s+/g,' ').slice(0,85);
    function paint(on, message, explanation = '', warning = false) {
        if (toggle.checked !== on) toggle.checked = on;
        const cls = warning ? 'dot error' : 'dot' + (on ? ' on' : '');
        if (el('dot').className !== cls) el('dot').className = cls;
        text('state', message); text('detail', explanation);
    }
    function extras(latest, records, problem = '') {
        const seen = new Set();
        const sent = records.filter(item => item.synced_at).sort((a,b) => String(b.synced_at).localeCompare(String(a.synced_at))).filter(item => {
            const key = item.question_id || item.content_hash;
            if (seen.has(key)) return false;
            seen.add(key); return true;
        }).slice(0,3);
        text('receipt-list', sent.length ? sent.map(item => `✓ ${time(item.synced_at)}\n${short(item.question)}`).join('\n\n') : '아직 접수 기록이 없습니다.');
        text('checked', latest?.at ? `최근 대화 확인 · ${time(latest.at)}` : '아직 이 페이지의 감지 결과가 없습니다.');
        text('debug', problem);
        if (el('diagnostic').hidden !== !problem) el('diagnostic').hidden = !problem;
    }
    async function refresh() {
        if (refreshing) { rerun = true; return; }
        refreshing = true;
        try {
            const all = await chrome.storage.local.get(null);
            const on = all[GPTIC_POLICY.enabledKey] === true;
            const [tab] = await chrome.tabs.query({active:true,currentWindow:true});
            let url;
            try { url = new URL(tab?.url || ''); } catch {}
            if (!url || !['chatgpt.com','chat.openai.com'].includes(url.hostname) || url.protocol !== 'https:') {
                currentCid = null; extras(null, []);
                paint(on, on ? 'ChatGPT 페이지를 기다리는 중' : '자동 감지 꺼짐'); return;
            }
            const cid = url.pathname.match(/\/c\/([^/]+)/)?.[1];
            currentCid = cid || null;
            if (!cid) { extras(null, []); paint(on, on ? '대화를 시작하면 자동으로 감지합니다' : '자동 감지 꺼짐'); return; }
            const latest = all[`gptic:status:${cid}`];
            const records = Object.entries(all).filter(([key,item]) => key.startsWith(`gptic:draft:${cid}:`) && item?.auto_policy === 1).map(([,item])=>item);
            const pending = records.filter(item=>!item.synced_at);
            const sync = all['gptic:sync-status'];
            const stale = latest?.at && Date.now() - Date.parse(latest.at) > 45000;
            const problem = on && (latest?.error || (pending.length && sync?.error) || (!latest || stale ? '현재 페이지의 감지 응답이 없거나 오래되었습니다. 확장을 업데이트한 직후라면 이 ChatGPT 탭을 한 번 새로고침해 주세요.' : ''));
            extras(latest, records, String(problem || ''));
            const question = latest?.latestQuestion ? `최근 질문: ${short(latest.latestQuestion)}` : '';
            if (!on) { paint(false, '자동 감지 꺼짐'); return; }
            if (latest?.error) {
                paint(on, '대화를 읽지 못해 전송하지 않았습니다', '아래 ‘멈춘 이유 보기’에서 원인을 확인해 주세요.', true);
            } else if (!latest || stale) {
                paint(on, '현재 페이지의 감지 응답을 기다리는 중', '아래 ‘멈춘 이유 보기’를 확인해 주세요.', true);
            } else if (pending.length && sync?.error) {
                paint(on, '서버 연결을 기다리는 중', `${pending.length}건 대기 · 연결되면 자동 재전송합니다.`, true);
            } else if (latest.latestQuestion !== undefined) {
                const current = records.find(item => item.content_hash === latest.latestHash);
                if (latest.missingIds && (!latest.latestQuestionId || !latest.latestHash)) {
                    paint(on, '질문·답변 ID를 확인하는 중', question, true);
                    extras(latest, records, '화면에 메시지는 있지만 질문/답변 ID를 아직 확인하지 못했습니다.');
                } else if (latest.latestStreaming) {
                    paint(on, '답변 작성 중 · 아직 전송하지 않았습니다', question);
                } else if (latest.latestEligible === false) {
                    paint(on, '최근 질문은 영어 학습 후보가 아닙니다', question);
                } else if (current?.synced_at) {
                    paint(on, '최근 질문 서버 접수 완료', question);
                } else if (current) {
                    paint(on, '최근 질문 자동 전송 대기 중', question);
                } else {
                    paint(on, '최근 답변을 확인 중 · 아직 접수되지 않았습니다', question || '답변 완료 후 보통 20~30초 정도 걸립니다.');
                }
            } else {
                paint(on, '현재 감지 상태를 확인하는 중', '최근 접수 기록은 아래에서 확인할 수 있습니다.');
            }
        } catch {
            paint(toggle.checked, '확장 프로그램을 다시 열어주세요', '', true);
        } finally {
            refreshing = false;
            if (rerun) { rerun = false; void refresh(); }
        }
    }
    toggle.addEventListener('change', async () => {
        toggle.disabled = true;
        try { await chrome.storage.local.set({[GPTIC_POLICY.enabledKey]:toggle.checked}); }
        catch { paint(toggle.checked, '설정을 저장하지 못했습니다', '', true); }
        finally { toggle.disabled = false; await refresh(); }
    });
    chrome.storage.onChanged.addListener((changes,area)=>{
        if (area !== 'local') return;
        if (Object.keys(changes).some(key => key === GPTIC_POLICY.enabledKey || key === 'gptic:sync-status'
            || (currentCid && (key === `gptic:status:${currentCid}` || key.startsWith(`gptic:draft:${currentCid}:`))))) refresh();
    });
    refresh(); setInterval(refresh,2000);
})();
