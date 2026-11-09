(() => {
    const button = document.getElementById('sync-now');
    const output = document.getElementById('sync-status');

    async function refresh() {
        try {
            const all = await chrome.storage.local.get(null);
            const records = Object.entries(all)
                .filter(([key]) => key.startsWith('gptic:draft:'))
                .map(([, value]) => value);

            const sent = records.filter(item => item.synced_at).length;
            const pending = records.filter(item =>
                !item.synced_at
                && item.identity_checked === true
                && item.source_conversation_id === item.conversation_id
                && all[`gptic:enabled:${item.conversation_id}`]
            ).length;
            const paused = records.length - sent - pending;
            const status = all['gptic:sync-status'];

            output.textContent = [
                `전송 완료: ${sent}개`,
                `전송 대기: ${pending}개`,
                paused ? `보류(대화 확인 필요·감지 꺼짐): ${paused}개` : '',
                status?.running ? '서버에 전송 중…' : '',
                status?.at
                    ? `최근 전송 시도: ${new Date(status.at).toLocaleTimeString()}`
                    : '',
                status?.error ? `오류: ${status.error}` : '',
                '서버에 원본을 보관합니다. 수집 후 서버가 대화별로 자동 정리합니다.'
            ].filter(Boolean).join('\n');

        } catch (error) {
            output.textContent = error.message;
        }
    }

    button.addEventListener('click', async () => {
        button.disabled = true;
        try {
            await chrome.runtime.sendMessage({type: 'GPTIC_SYNC_NOW'});
            await refresh();
        } catch (error) {
            output.textContent = error.message;
        } finally {
            button.disabled = false;
        }
    });

    refresh();
    setInterval(refresh, 2000);
})();
