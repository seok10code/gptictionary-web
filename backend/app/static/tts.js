let selectedVoice = null;

function loadVoices() {
    const voices = window.speechSynthesis.getVoices();

    selectedVoice =
        voices.find(v => v.lang === "en-US" && v.name.toLowerCase().includes("samantha")) ||
        voices.find(v => v.lang === "en-US" && v.name.toLowerCase().includes("google")) ||
        voices.find(v => v.lang === "en-US") ||
        voices.find(v => v.lang.startsWith("en")) ||
        null;
}

function speakText(text) {
    if (!text) return;

    if (!window.speechSynthesis) {
        alert("이 브라우저는 음성 읽기를 지원하지 않습니다.");
        return;
    }

    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 0.85;
    utterance.pitch = 1;
    utterance.volume = 1;

    if (selectedVoice) {
        utterance.voice = selectedVoice;
    }

    window.speechSynthesis.speak(utterance);
}

document.addEventListener("DOMContentLoaded", function () {
    loadVoices();

    if (window.speechSynthesis.onvoiceschanged !== undefined) {
        window.speechSynthesis.onvoiceschanged = loadVoices;
    }

    document.querySelectorAll("[data-speak]").forEach(function (el) {
        el.style.cursor = "pointer";
        el.title = "클릭하면 발음 듣기";

        el.addEventListener("click", function () {
            const text = el.getAttribute("data-speak");
            speakText(text);
        });
    });
});