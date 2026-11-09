const button = document.getElementById('read');
const output = document.getElementById('result');


button.addEventListener('click', async () => {
    button.disabled = true;
    output.textContent = '대화를 읽는 중…';

    try {
        const [tab] = await chrome.tabs.query({
            active: true,
            currentWindow: true
        });

        const url = new URL(tab.url || '');

        if (
            !['chatgpt.com', 'chat.openai.com'].includes(url.hostname)
            || !/\/c\/[^/]+/.test(url.pathname)
        ) {
            throw new Error('ChatGPT에서 기존 대화 하나를 열어주세요.');
        }

        /* SHARED_COLLECTOR_READER */
        await chrome.scripting.executeScript({
            target: {tabId: tab.id},
            files: ['collector-read.js']
        });

        const results = await chrome.scripting.executeScript({
            target: {tabId: tab.id},
            func: () => readConversation()
        });

        const data = results[0]?.result;
        if (!data) {
            throw new Error('페이지에서 결과를 받지 못했습니다.');
        }

        const users = data.messages.filter(m => m.role === 'user');
        const assistants = data.messages.filter(
            m => m.role === 'assistant'
        );
        const unknown = data.messages.filter(m => m.role === 'unknown');

        output.textContent = [
            `대화: ${data.title}`,
            `질문: ${users.length}개`,
            `답변: ${assistants.length}개`,
            `역할 미확인: ${unknown.length}개`,
            `메시지 ID: ${data.messages.filter(m => m.message_id).length}개`,
            '',
            '발견한 본문 스타일:',
            JSON.stringify(data.styleCounts, null, 2),
            '', '질문 영역 진단:',
            JSON.stringify(data.domInfo, null, 2),
            '',
            '첫 질문:',
            users[0]?.text.slice(0, 150) || '(없음)',
            '',
            '마지막 답변:',
            assistants.at(-1)?.text.slice(0, 200) || '(없음)',
            '',
            '현재 로드된 내용만 확인했습니다.',
            '서버 전송·DB 저장은 하지 않았습니다.'
        ].join('\n');

    } catch (error) {
        output.textContent = `확인 실패: ${error.message}`;
    } finally {
        button.disabled = false;
    }
});
