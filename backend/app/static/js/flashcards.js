const data = window.FLASHCARD_DATA ?? {};
const words = data.words ?? [];
const currentMode = data.mode ?? "random";

const STORAGE_KEY = "gptictionary_flashcards_settings";

const defaultSettings = {
    duration: 20,
    wordAudio: true,
    sentenceAudio: true,
    fade: true,
    theme: "auto",
};

let settings = loadSettings();

let currentIndex = 0;
let isPlaying = true;
let audioUnlocked = false;
let cycleId = 0;
let controlsTimer = null;
let countdownTimer = null;
let wakeLock = null;

const audioCache = new Map();

const audioPlayer = new Audio();
audioPlayer.preload = "auto";
audioPlayer.playsInline = true;
audioPlayer.volume = 1;

let currentAudioUrl = null;
let currentAudioResolver = null;

let pointerStartX = 0;
let pointerStartY = 0;
let pointerStartedAt = 0;
let activePointerId = null;
let longPressTimer = null;
let longPressTriggered = false;
let didSwipe = false;


const page = document.getElementById("flashcards-page");
const flashcard = document.getElementById("flashcard");

const progressBar = document.getElementById("progress-bar");
const counter = document.getElementById("counter");
const countdown = document.getElementById("countdown");
const modeLabel = document.getElementById("mode-label");

const recallPrompt = document.getElementById("recall-prompt");
const wordElement = document.getElementById("word");
const definitionElement = document.getElementById("definition");
const sentenceElement = document.getElementById("sentence");
const synonymsElement = document.getElementById("synonyms");
const usageNoteElement = document.getElementById("usage-note");

const answerBlock = document.getElementById("answer-block");
const exampleSection = document.getElementById("example-section");
const synonymsSection = document.getElementById("synonyms-section");
const usageSection = document.getElementById("usage-section");

const controls = document.getElementById("controls");
const previousButton = document.getElementById("previous-button");
const nextButton = document.getElementById("next-button");
const speakButton = document.getElementById("speak-button");
const playButton = document.getElementById("play-button");
const settingsButton = document.getElementById("settings-button");

const settingsPanel = document.getElementById("settings-panel");
const closeSettingsButton = document.getElementById(
    "close-settings-button"
);

const modeSelect = document.getElementById("mode-select");
const durationSelect = document.getElementById("duration-select");
const themeSelect = document.getElementById("theme-select");
const wordAudioToggle = document.getElementById(
    "word-audio-toggle"
);
const sentenceAudioToggle = document.getElementById(
    "sentence-audio-toggle"
);
const fadeToggle = document.getElementById("fade-toggle");

const modeNames = {
    random: "랜덤",
    priority: "우선순위",
    memorize: "암기 부족",
    wrong: "오답",
    recent: "최근",
    today: "오늘",
};


function loadSettings() {
    try {
        const saved = JSON.parse(
            localStorage.getItem(STORAGE_KEY) || "{}"
        );

        return {
            ...defaultSettings,
            ...saved,
        };
    } catch {
        return { ...defaultSettings };
    }
}


function saveSettings() {
    localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(settings)
    );
}


function getCurrentWord() {
    return words[currentIndex] ?? null;
}


function sleep(ms) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, ms);
    });
}


function normalizeSynonyms(value) {
    return (value || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
        .join("  ·  ");
}


function formatUsageNote(text) {
    if (!text) {
        return "";
    }

    return text
        .replace(
            /\s*💬\s*실제 대화\s*/g,
            "\n\n💬 실제 대화\n"
        )
        .replace(
            /\s*📝\s*글쓰기 예문\s*/g,
            "\n\n📝 글쓰기 예문\n"
        )
        .replace(/\s+A:\s*/g, "\nA: ")
        .replace(/\s+B:\s*/g, "\nB: ")
        .trim();
}


/*
카드가 뜨자마자 모든 정보를 표시한다.
더 이상 Example을 몇 초 뒤에 보여주지 않는다.
*/
function showAllSections() {
    const sections = [
        answerBlock,
        exampleSection,
        synonymsSection,
        usageSection,
    ];

    sections.forEach((element) => {
        if (!element || element.hidden) {
            return;
        }

        element.classList.remove("stage-hidden");
        element.classList.add("stage-visible");
    });
}


function renderCurrentWord() {
    const currentWord = getCurrentWord();

    if (!currentWord) {
        return;
    }

    const vocabulary =
        (currentWord.vocabulary || "").trim();

    const definition =
        (currentWord.definition || "").trim();

    const sentence =
        (currentWord.sentence || "").trim();

    const synonyms =
        (currentWord.synonyms || "").trim();

    const usageNote =
        (currentWord.usage_note || "").trim();

    wordElement.textContent = vocabulary;

    wordElement.classList.remove(
        "word-medium",
        "word-long",
        "word-very-long"
    );

    if (vocabulary.length >= 28) {
        wordElement.classList.add(
            "word-very-long"
        );
    } else if (vocabulary.length >= 18) {
        wordElement.classList.add(
            "word-long"
        );
    } else if (vocabulary.length >= 11) {
        wordElement.classList.add(
            "word-medium"
        );
    }

    definitionElement.textContent =
        definition || "등록된 뜻이 없습니다.";

    sentenceElement.textContent = sentence;

    synonymsElement.textContent =
        normalizeSynonyms(synonyms);

    usageNoteElement.textContent =
        formatUsageNote(usageNote);

    exampleSection.hidden = !sentence;
    synonymsSection.hidden = !synonyms;
    usageSection.hidden = !usageNote;

    recallPrompt.textContent =
        `What does "${vocabulary}" mean?`;

    counter.textContent =
        `${currentIndex + 1} / ${words.length}`;

    modeLabel.textContent =
        modeNames[currentMode] || currentMode;

    document.title =
        `${vocabulary} · GPTictionary`;

    showAllSections();
}


function stopCurrentAudio() {
    const resolver = currentAudioResolver;

    currentAudioResolver = null;

    try {
        audioPlayer.pause();
        audioPlayer.currentTime = 0;
    } catch {
        // 이미 정지된 상태면 무시
    }

    if (resolver) {
        resolver(false);
    }

    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
        currentAudioUrl = null;
    }
}


async function requestTTSAudio(
    text,
    audioType = "word"
) {
    const cleanText = (text || "").trim();
    const cacheKey = `${audioType}:${cleanText}`;

    if (audioCache.has(cacheKey)) {
        return audioCache.get(cacheKey);
    }

    const response = await fetch(
        "/api/flashcards/tts",
        {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                text: cleanText,
                audio_type: audioType,
            }),
        }
    );

    if (!response.ok) {
        const errorText = await response.text();

        throw new Error(
            `TTS failed: ${response.status} ${errorText}`
        );
    }

    const blob = await response.blob();

    audioCache.set(cacheKey, blob);

    return blob;
}


async function playTTSAudio(
    text,
    audioType = "word"
) {
    const cleanText = (text || "").trim();

    if (!cleanText || !audioUnlocked) {
        return false;
    }

    stopCurrentAudio();

    try {
        const blob = await requestTTSAudio(
            cleanText,
            audioType
        );

        currentAudioUrl =
            URL.createObjectURL(blob);

        audioPlayer.src = currentAudioUrl;
        audioPlayer.currentTime = 0;
        audioPlayer.volume = 1;

        return await new Promise((resolve) => {
            let completed = false;

            const finish = (playedNormally) => {
                if (completed) {
                    return;
                }

                completed = true;

                audioPlayer.removeEventListener(
                    "ended",
                    handleEnded
                );

                audioPlayer.removeEventListener(
                    "error",
                    handleError
                );

                if (currentAudioResolver === finish) {
                    currentAudioResolver = null;
                }

                resolve(playedNormally);
            };

            const handleEnded = () => {
                finish(true);
            };

            const handleError = () => {
                console.error(
                    "Audio element error:",
                    audioPlayer.error
                );

                finish(false);
            };

            currentAudioResolver = finish;

            audioPlayer.addEventListener(
                "ended",
                handleEnded,
                { once: true }
            );

            audioPlayer.addEventListener(
                "error",
                handleError,
                { once: true }
            );

            audioPlayer.play().catch((error) => {
                console.error(
                    "Audio playback failed:",
                    error
                );

                finish(false);
            });
        });
    } catch (error) {
        console.error("OpenAI TTS error:", error);
        return false;
    }
}


/*
처음 사용자 조작에서 실제 단어를 재생해
브라우저의 음성 권한을 활성화한다.
*/
async function unlockAudio() {
    if (audioUnlocked) {
        return true;
    }

    const currentWord = getCurrentWord();

    if (!currentWord) {
        return false;
    }

    const word =
        (currentWord.vocabulary || "").trim();

    if (!word) {
        return false;
    }

    audioUnlocked = true;

    const played = await playTTSAudio(
        word,
        "word"
    );

    if (!played) {
        audioUnlocked = false;
        return false;
    }

    return true;
}


async function playCardAudio(
    expectedCycleId
) {
    if (
        !audioUnlocked ||
        expectedCycleId !== cycleId ||
        !isPlaying
    ) {
        return;
    }

    const currentWord = getCurrentWord();

    if (!currentWord) {
        return;
    }

    const word =
        (currentWord.vocabulary || "").trim();

    const sentence =
        (currentWord.sentence || "").trim();

    if (settings.wordAudio && word) {
        await playTTSAudio(word, "word");
    }

    if (
        expectedCycleId !== cycleId ||
        !isPlaying
    ) {
        return;
    }

    await sleep(500);

    if (
        expectedCycleId !== cycleId ||
        !isPlaying
    ) {
        return;
    }

    if (settings.sentenceAudio && sentence) {
        await playTTSAudio(
            sentence,
            "sentence"
        );
    }
}


function restartProgress() {
    progressBar.style.transition = "none";
    progressBar.style.width = "0%";

    void progressBar.offsetWidth;

    if (!isPlaying) {
        return;
    }

    window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
            progressBar.style.transition =
                `width ${settings.duration}s linear`;

            progressBar.style.width = "100%";
        });
    });
}


function startCountdown(expectedCycleId) {
    if (countdownTimer !== null) {
        window.clearInterval(countdownTimer);
    }

    let remaining = settings.duration;

    countdown.textContent = `${remaining}s`;

    countdownTimer = window.setInterval(() => {
        if (
            expectedCycleId !== cycleId ||
            !isPlaying
        ) {
            window.clearInterval(countdownTimer);
            countdownTimer = null;
            return;
        }

        remaining -= 1;

        if (remaining < 0) {
            remaining = 0;
        }

        countdown.textContent = `${remaining}s`;
    }, 1000);
}


async function runCardCycle(expectedCycleId) {
    const startedAt = Date.now();

    renderCurrentWord();
    restartProgress();
    startCountdown(expectedCycleId);

    /*
    화면은 즉시 전부 표시하고,
    음성만 순차적으로 실행한다.
    */
    await playCardAudio(expectedCycleId);

    if (
        expectedCycleId !== cycleId ||
        !isPlaying
    ) {
        return;
    }

    const elapsed = Date.now() - startedAt;
    const totalDuration = settings.duration * 1000;
    const remaining = Math.max(
        0,
        totalDuration - elapsed
    );

    await sleep(remaining);

    if (
        expectedCycleId !== cycleId ||
        !isPlaying
    ) {
        return;
    }

    currentIndex =
        (currentIndex + 1) % words.length;

    startNewCycle();
}


function startNewCycle() {
    stopCurrentAudio();

    if (countdownTimer !== null) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
    }

    cycleId += 1;

    const expectedCycleId = cycleId;

    runCardCycle(expectedCycleId);
}


function moveToCard(nextIndex) {
    cycleId += 1;
    stopCurrentAudio();

    if (countdownTimer !== null) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
    }

    const completeMove = () => {
        currentIndex = nextIndex;

        flashcard.classList.remove("is-changing");

        if (isPlaying) {
            startNewCycle();
        } else {
            renderCurrentWord();
            showAllSections();

            progressBar.style.transition = "none";
            progressBar.style.width = "0%";

            countdown.textContent = "일시정지";
        }
    };

    if (settings.fade) {
        flashcard.classList.add("is-changing");
        window.setTimeout(completeMove, 280);
    } else {
        completeMove();
    }
}


function showNextCard() {
    moveToCard(
        (currentIndex + 1) % words.length
    );
}


function showPreviousCard() {
    moveToCard(
        (currentIndex - 1 + words.length) %
        words.length
    );
}


function togglePlayback() {
    isPlaying = !isPlaying;

    playButton.textContent =
        isPlaying ? "일시정지" : "자동 재생";

    cycleId += 1;
    stopCurrentAudio();

    if (countdownTimer !== null) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
    }

    if (isPlaying) {
        startNewCycle();
    } else {
        renderCurrentWord();
        showAllSections();

        progressBar.style.transition = "none";
        progressBar.style.width = "0%";

        countdown.textContent = "일시정지";
    }
}


function showControls() {
    controls.classList.remove("is-hidden");

    if (controlsTimer !== null) {
        window.clearTimeout(controlsTimer);
    }

    controlsTimer = window.setTimeout(() => {
        if (
            !settingsPanel.classList.contains(
                "is-open"
            )
        ) {
            controls.classList.add("is-hidden");
        }
    }, 4000);
}


function openSettings() {
    settingsPanel.classList.add("is-open");

    settingsPanel.setAttribute(
        "aria-hidden",
        "false"
    );

    controls.classList.remove("is-hidden");
}


function closeSettings() {
    settingsPanel.classList.remove("is-open");

    settingsPanel.setAttribute(
        "aria-hidden",
        "true"
    );

    showControls();
}


function applyTheme() {
    let resolvedTheme = settings.theme;

    if (resolvedTheme === "auto") {
        const hour = new Date().getHours();

        resolvedTheme =
            hour >= 7 && hour < 19
                ? "light"
                : "dark";
    }

    document.body.classList.toggle(
        "theme-light",
        resolvedTheme === "light"
    );

    document.body.classList.toggle(
        "theme-dark",
        resolvedTheme === "dark"
    );
}


function populateSettings() {
    modeSelect.value = currentMode;

    durationSelect.value =
        String(settings.duration);

    themeSelect.value = settings.theme;

    wordAudioToggle.checked =
        settings.wordAudio;

    sentenceAudioToggle.checked =
        settings.sentenceAudio;

    fadeToggle.checked =
        settings.fade;
}


async function requestWakeLock() {
    if (!("wakeLock" in navigator)) {
        return;
    }

    try {
        wakeLock = await navigator.wakeLock.request(
            "screen"
        );
    } catch {
        wakeLock = null;
    }
}


/*
첫 화면 터치:
현재 단어를 실제로 재생해 음성을 활성화하고
카드 시간을 처음부터 다시 시작한다.
*/
page.addEventListener(
    "pointerdown",
    async (event) => {
        if (
            audioUnlocked ||
            event.target.closest("button") ||
            event.target.closest(".settings-panel")
        ) {
            return;
        }

        const unlocked = await unlockAudio();

        if (unlocked && isPlaying) {
            startNewCycle();
        }
    },
    {
        passive: true,
    }
);


flashcard.addEventListener("click", (event) => {
    if (
        event.target.closest("button") ||
        event.target.closest("a") ||
        event.target.closest("input") ||
        event.target.closest("select") ||
        event.target.closest(".settings-panel") ||
        longPressTriggered ||
        didSwipe
    ) {
        longPressTriggered = false;
        didSwipe = false;
        return;
    }

    togglePlayback();
    showControls();
});


flashcard.addEventListener(
    "pointerdown",
    (event) => {
        if (
            event.pointerType === "mouse"
            && event.button !== 0
        ) {
            return;
        }

        activePointerId = event.pointerId;
        pointerStartX = event.clientX;
        pointerStartY = event.clientY;
        pointerStartedAt = Date.now();

        longPressTriggered = false;
        didSwipe = false;

        try {
            flashcard.setPointerCapture(
                event.pointerId
            );
        } catch (error) {
            // Pointer capture is optional.
        }

        if (longPressTimer !== null) {
            window.clearTimeout(longPressTimer);
        }

        longPressTimer = window.setTimeout(
            async () => {
                longPressTriggered = true;

                const currentWord = getCurrentWord();

                if (!currentWord) {
                    return;
                }

                if (!audioUnlocked) {
                    await unlockAudio();
                } else {
                    await playTTSAudio(
                        currentWord.vocabulary,
                        "word"
                    );
                }

                showControls();
            },
            650
        );
    }
);


flashcard.addEventListener(
    "pointermove",
    (event) => {
        if (
            activePointerId !== event.pointerId
        ) {
            return;
        }

        const distanceX = Math.abs(
            event.clientX - pointerStartX
        );

        const distanceY = Math.abs(
            event.clientY - pointerStartY
        );

        if (
            distanceX > 14
            || distanceY > 14
        ) {
            if (longPressTimer !== null) {
                window.clearTimeout(
                    longPressTimer
                );
                longPressTimer = null;
            }
        }

        if (
            distanceX > distanceY
            && distanceX > 10
        ) {
            event.preventDefault();
        }
    }
);


flashcard.addEventListener(
    "pointerup",
    async (event) => {
        if (
            activePointerId !== event.pointerId
        ) {
            return;
        }

        activePointerId = null;

        if (longPressTimer !== null) {
            window.clearTimeout(longPressTimer);
            longPressTimer = null;
        }

        if (longPressTriggered) {
            return;
        }

        const deltaX =
            event.clientX - pointerStartX;

        const deltaY =
            event.clientY - pointerStartY;

        const elapsed =
            Date.now() - pointerStartedAt;

        const isHorizontalSwipe =
            Math.abs(deltaX) >= 42
            && Math.abs(deltaX)
            > Math.abs(deltaY) * 1.1
            && elapsed <= 1200;

        if (!isHorizontalSwipe) {
            return;
        }

        didSwipe = true;
        event.preventDefault();

        if (!audioUnlocked) {
            await unlockAudio();
        }

        if (deltaX < 0) {
            flashcard.classList.add(
                "swipe-left"
            );
            showNextCard();
        } else {
            flashcard.classList.add(
                "swipe-right"
            );
            showPreviousCard();
        }

        window.setTimeout(() => {
            flashcard.classList.remove(
                "swipe-left",
                "swipe-right"
            );

            didSwipe = false;
        }, 320);

        showControls();
    }
);


flashcard.addEventListener(
    "pointercancel",
    () => {
        activePointerId = null;

        if (longPressTimer !== null) {
            window.clearTimeout(longPressTimer);
            longPressTimer = null;
        }
    }
);


previousButton.addEventListener(
    "click",
    async () => {
        if (!audioUnlocked) {
            await unlockAudio();
        }

        showPreviousCard();
        showControls();
    }
);


nextButton.addEventListener(
    "click",
    async () => {
        if (!audioUnlocked) {
            await unlockAudio();
        }

        showNextCard();
        showControls();
    }
);


speakButton.addEventListener(
    "click",
    async () => {
        const currentWord = getCurrentWord();

        if (!currentWord) {
            return;
        }

        if (!audioUnlocked) {
            await unlockAudio();
            showControls();
            return;
        }

        await playTTSAudio(
            currentWord.vocabulary,
            "word"
        );

        showControls();
    }
);


playButton.addEventListener("click", () => {
    togglePlayback();
    showControls();
});


settingsButton.addEventListener(
    "click",
    openSettings
);


closeSettingsButton.addEventListener(
    "click",
    closeSettings
);


durationSelect.addEventListener("change", () => {
    settings.duration =
        Number(durationSelect.value);

    saveSettings();

    if (isPlaying) {
        startNewCycle();
    }
});


themeSelect.addEventListener("change", () => {
    settings.theme = themeSelect.value;

    saveSettings();
    applyTheme();
});


wordAudioToggle.addEventListener(
    "change",
    () => {
        settings.wordAudio =
            wordAudioToggle.checked;

        saveSettings();
    }
);


sentenceAudioToggle.addEventListener(
    "change",
    () => {
        settings.sentenceAudio =
            sentenceAudioToggle.checked;

        saveSettings();
    }
);


fadeToggle.addEventListener("change", () => {
    settings.fade = fadeToggle.checked;
    saveSettings();
});


modeSelect.addEventListener("change", () => {
    const selectedMode = modeSelect.value;

    window.location.href =
        `/flashcards?mode=${encodeURIComponent(
            selectedMode
        )}`;
});


document.addEventListener("keydown", async (event) => {
    if (event.key === "ArrowLeft") {
        if (!audioUnlocked) {
            await unlockAudio();
        }

        showPreviousCard();
    }

    if (event.key === "ArrowRight") {
        if (!audioUnlocked) {
            await unlockAudio();
        }

        showNextCard();
    }

    if (event.code === "Space") {
        event.preventDefault();
        togglePlayback();
    }

    showControls();
});


document.addEventListener(
    "visibilitychange",
    () => {
        if (
            document.visibilityState === "visible"
        ) {
            requestWakeLock();
        }
    }
);


/* 시작 */

populateSettings();
applyTheme();
renderCurrentWord();
showAllSections();
requestWakeLock();
startNewCycle();

window.setInterval(
    applyTheme,
    60 * 1000
);



// ===== iPad Safari 전용 스와이프 =====
(() => {
    let swipeStartX = 0;
    let swipeStartY = 0;
    let swipeStartTime = 0;

    function isFlashcardTarget(target) {
        return Boolean(
            target.closest("#flashcard, .flashcard")
        );
    }

    function isControlTarget(target) {
        return Boolean(
            target.closest(
                "button, a, input, select, textarea, " +
                ".controls, .settings-panel"
            )
        );
    }

    document.addEventListener(
        "touchstart",
        (event) => {
            if (
                event.touches.length !== 1 ||
                !isFlashcardTarget(event.target) ||
                isControlTarget(event.target)
            ) {
                return;
            }

            const touch = event.touches[0];

            swipeStartX = touch.clientX;
            swipeStartY = touch.clientY;
            swipeStartTime = Date.now();
        },
        {
            capture: true,
            passive: true,
        }
    );

    document.addEventListener(
        "touchend",
        (event) => {
            if (
                event.changedTouches.length !== 1 ||
                !isFlashcardTarget(event.target) ||
                isControlTarget(event.target)
            ) {
                return;
            }

            const touch = event.changedTouches[0];

            const deltaX =
                touch.clientX - swipeStartX;

            const deltaY =
                touch.clientY - swipeStartY;

            const elapsed =
                Date.now() - swipeStartTime;

            const horizontalDistance =
                Math.abs(deltaX);

            const verticalDistance =
                Math.abs(deltaY);

            const isSwipe =
                horizontalDistance >= 30 &&
                horizontalDistance >
                    verticalDistance * 1.05 &&
                elapsed <= 1500;

            if (!isSwipe) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();

            if (deltaX < 0) {
                showNextCard();
            } else {
                showPreviousCard();
            }

            showControls();
        },
        {
            capture: true,
            passive: false,
        }
    );
})();