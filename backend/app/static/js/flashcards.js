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
let sequenceToken = 0;

let timers = [];
let countdownTimer = null;
let controlsTimer = null;
let currentAudio = null;
let currentAudioUrl = null;
let currentAudioFinish = null;
let wakeLock = null;

const audioCache = new Map();

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


function setStageVisible(element, visible) {
    if (!element || element.hidden) {
        return;
    }

    element.classList.toggle("stage-hidden", !visible);
    element.classList.toggle("stage-visible", visible);
}


function resetStages() {
    setStageVisible(answerBlock, false);
    setStageVisible(exampleSection, false);
    setStageVisible(synonymsSection, false);
    setStageVisible(usageSection, false);
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

    resetStages();
}


function clearTimers() {
    timers.forEach((timerId) => {
        window.clearTimeout(timerId);
    });

    timers = [];

    if (countdownTimer !== null) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
    }
}


function schedule(callback, delay) {
    const token = sequenceToken;

    const timerId = window.setTimeout(() => {
        if (
            token !== sequenceToken ||
            !isPlaying
        ) {
            return;
        }

        callback();
    }, delay);

    timers.push(timerId);
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


function startCountdown() {
    let remaining = settings.duration;

    countdown.textContent = `${remaining}s`;

    countdownTimer = window.setInterval(() => {
        remaining -= 1;

        if (remaining < 0) {
            remaining = 0;
        }

        countdown.textContent = `${remaining}s`;
    }, 1000);
}


function stopCurrentAudio() {
    const audio = currentAudio;
    const finish = currentAudioFinish;

    currentAudio = null;
    currentAudioFinish = null;

    if (audio) {
        try {
            audio.pause();
            audio.currentTime = 0;
        } catch {
            // 이미 종료된 오디오는 무시
        }
    }

    /*
    자동 카드 전환으로 음성이 중단돼도
    기존 await가 영원히 멈추지 않게 한다.
    */
    if (finish) {
        finish();
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
    const cacheKey = `${audioType}:${text}`;

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
                text,
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

        const audio = new Audio(currentAudioUrl);

        audio.preload = "auto";
        audio.volume = 1;
        audio.playsInline = true;

        currentAudio = audio;

        const played = await new Promise((resolve) => {
            let finished = false;

            const finish = (result) => {
                if (finished) {
                    return;
                }

                finished = true;

                audio.removeEventListener(
                    "ended",
                    handleEnded
                );

                audio.removeEventListener(
                    "error",
                    handleError
                );

                if (currentAudio === audio) {
                    currentAudio = null;
                }

                if (currentAudioFinish === stopResolver) {
                    currentAudioFinish = null;
                }

                resolve(result);
            };

            const handleEnded = () => {
                finish(true);
            };

            const handleError = () => {
                console.error(
                    "TTS audio error:",
                    audio.error
                );

                finish(false);
            };

            const stopResolver = () => {
                finish(false);
            };

            currentAudioFinish = stopResolver;

            audio.addEventListener(
                "ended",
                handleEnded,
                { once: true }
            );

            audio.addEventListener(
                "error",
                handleError,
                { once: true }
            );

            audio.play().catch((error) => {
                console.error(
                    "TTS playback failed:",
                    error
                );

                finish(false);
            });
        });

        return played;

    } catch (error) {
        console.error("OpenAI TTS error:", error);
        return false;
    }
}


async function speakSentence(token = sequenceToken) {
    const currentWord = getCurrentWord();

    if (
        !currentWord ||
        !settings.sentenceAudio ||
        !audioEnabled
    ) {
        return;
    }

    const sentence =
        (currentWord.sentence || "").trim();

    if (!sentence || token !== sequenceToken) {
        return;
    }

    await playTTSAudio(
        sentence,
        "sentence"
    );
}

function sleep(ms) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, ms);
    });
}


async function runCardAudioSequence(
    token,
    skipWordAudio = false
) {
    if (
        !audioUnlocked ||
        token !== sequenceToken ||
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

    /*
    1. 단어 한 번
    */
    if (
        !skipWordAudio &&
        settings.wordAudio &&
        word
    ) {
        await playTTSAudio(word, "word");
    }

    if (
        token !== sequenceToken ||
        !isPlaying
    ) {
        return;
    }

    /*
    2. 단어와 예문 사이 간격
    */
    await new Promise((resolve) => {
        window.setTimeout(resolve, 800);
    });

    if (
        token !== sequenceToken ||
        !isPlaying
    ) {
        return;
    }

    /*
    3. 예문 표시 및 재생
    */
    setStageVisible(exampleSection, true);

    if (
        settings.sentenceAudio &&
        sentence
    ) {
        await playTTSAudio(
            sentence,
            "sentence"
        );
    }
}

function startCardCycle(
    skipWordAudio = false
) {
    clearTimers();
    stopCurrentAudio();

    sequenceToken += 1;

    const token = sequenceToken;

    renderCurrentWord();
    restartProgress();
    startCountdown();

    const totalMs =
        settings.duration * 1000;

    const answerTime =
        Math.max(700, totalMs * 0.05);

    const audioStartTime =
        Math.max(1000, totalMs * 0.08);

    const synonymsTime =
        Math.max(6000, totalMs * 0.55);

    const usageTime =
        Math.max(8500, totalMs * 0.72);

    schedule(() => {
        recallPrompt.style.opacity = "0.4";
        setStageVisible(answerBlock, true);
    }, answerTime);

    /*
    카드당 음성 흐름은 이것 하나만 실행한다.
    */
    schedule(() => {
        runCardAudioSequence(
            token,
            skipWordAudio
        );
    }, audioStartTime);

    schedule(() => {
        setStageVisible(synonymsSection, true);
    }, synonymsTime);

    schedule(() => {
        setStageVisible(usageSection, true);
    }, usageTime);

    schedule(() => {
        if (
            token !== sequenceToken ||
            !isPlaying
        ) {
            return;
        }

        showNextCard();
    }, totalMs);
}


function revealAll() {
    setStageVisible(answerBlock, true);
    setStageVisible(exampleSection, true);
    setStageVisible(synonymsSection, true);
    setStageVisible(usageSection, true);

    progressBar.style.transition = "none";
    progressBar.style.width = "0%";

    countdown.textContent = "일시정지";
}


function changeCard(nextIndex) {
    clearTimers();
    stopCurrentAudio();

    sequenceToken += 1;

    if (settings.fade) {
        flashcard.classList.add("is-changing");

        window.setTimeout(() => {
            currentIndex = nextIndex;

            flashcard.classList.remove(
                "is-changing"
            );

            if (isPlaying) {
                startCardCycle();
            } else {
                renderCurrentWord();
                revealAll();
            }
        }, 300);

        return;
    }

    currentIndex = nextIndex;

    if (isPlaying) {
        startCardCycle();
    } else {
        renderCurrentWord();
        revealAll();
    }
}


function showNextCard() {
    const nextIndex =
        (currentIndex + 1) % words.length;

    changeCard(nextIndex);
}


function showPreviousCard() {
    const nextIndex =
        (currentIndex - 1 + words.length) %
        words.length;

    changeCard(nextIndex);
}


function togglePlayback() {
    isPlaying = !isPlaying;

    playButton.textContent =
        isPlaying ? "일시정지" : "자동 재생";

    if (isPlaying) {
        startCardCycle();
    } else {
        clearTimers();
        stopCurrentAudio();

        sequenceToken += 1;

        revealAll();
    }
}


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

    /*
    사용자가 화면을 터치한 이벤트 안에서
    실제 단어 음성을 한 번 재생한다.
    */
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


/* 이벤트 */

previousButton.addEventListener("click", () => {
    showPreviousCard();
    showControls();
});

nextButton.addEventListener("click", () => {
    showNextCard();
    showControls();
});

playButton.addEventListener("click", () => {
    togglePlayback();
    showControls();
});

speakButton.addEventListener("click", async () => {
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
});

settingsButton.addEventListener(
    "click",
    openSettings
);

closeSettingsButton.addEventListener(
    "click",
    closeSettings
);

page.addEventListener(
    "pointerdown",
    async () => {
        if (audioUnlocked) {
            return;
        }

        const unlocked = await unlockAudio();

        if (unlocked && isPlaying) {
            startCardCycle(true);
        }
    },
    {
        passive: true,
    }
);


page.addEventListener("click", (event) => {
    if (
        event.target.closest("button") ||
        event.target.closest(
            ".settings-panel"
        )
    ) {
        return;
    }

    showControls();
});

durationSelect.addEventListener("change", () => {
    settings.duration =
        Number(durationSelect.value);

    saveSettings();

    if (isPlaying) {
        startCardCycle();
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

document.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") {
        showPreviousCard();
    }

    if (event.key === "ArrowRight") {
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
requestWakeLock();
startCardCycle();

window.setInterval(
    applyTheme,
    60 * 1000
);
