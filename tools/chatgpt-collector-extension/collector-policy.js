// Local candidate filter; final learning classification stays on the server.
globalThis.GPTIC_POLICY = (() => {
    const enabledKey = 'gptic:auto-enabled';
    function select(pairs) {
        let context = false;
        return pairs.map(pair => {
            const q = pair.question.text.trim();
            const a = pair.answers.map(m => m.text).join('\n\n');
            const unrelated = /(?:```|Traceback|SQLAlchemy|localhost|\/Downloads\/|API\s*\d+\/|보고서:)/i.test(q)
                || /(?:코드|파이썬|자바스크립트|데이터베이스|콜렉터|collector|gptictionary|서버|펌웨어|타이어|공기압|주식|날씨|여행\s*일정)/i.test(q);
            const explicit = /(?:영어|영문|영작|문법|시제|현재완료|과거완료|관계대명사|가정법|수동태|전치사|동명사|부정사|구동사|present perfect|simple past|in English)/i.test(q);
            const vocabulary = /^[\s"'`“”‘’A-Za-z.,!? -]{1,100}\s*(?:뜻|의미|차이|뉘앙스|발음|사용법)(?:이|가|은|는|을|를|에|좀|뭐|어떻게|\s|[?!.])*.*$/i.test(q)
                || (/^[A-Za-z][A-Za-z '-]{0,45}[?.]?$/.test(q) && /(?:뜻|의미|품사|예문|동의어|반의어|명사|형용사|동사)/.test(a));
            const englishRequest = /(?:meaning of|difference between|what does .+ mean|how (?:do|can) (?:I|you) say)/i.test(q);
            const followup = context && q.length < 350 && /(?:그럼|그러면|이거|그거|이건|그건|이렇게|저렇게|예문|예시|상황|정중|편하게|친구|상사|거래처|고객|차이|뉘앙스|맞아|가능|써도|설명|더 |왜|문장|표현|since|yesterday|for\b)/i.test(q);
            const selected = !unrelated && (explicit || vocabulary || englishRequest || followup);
            context = selected;
            return selected;
        });
    }
    return {enabledKey, select};
})();
