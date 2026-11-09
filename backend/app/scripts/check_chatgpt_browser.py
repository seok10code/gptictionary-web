import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def is_conversation(page):
    url = urlparse(page.url)
    return (
        url.hostname in {"chatgpt.com", "chat.openai.com"}
        and re.search(r"/c/[^/]+", url.path) is not None
    )


def main():
    # 평소 사용하는 크롬과 분리된 전용 프로필입니다.
    profile = (
        Path.home()
        / "Library"
        / "Application Support"
        / "GPTictionary"
        / "chatgpt-browser"
    )
    profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            viewport={"width": 1280, "height": 900},
        )

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(
                "https://chatgpt.com/",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            print("\n열린 브라우저에서 다음을 진행해주세요.")
            print("1. ChatGPT에 직접 로그인")
            print("2. 짧은 영어 질문 대화 하나 열기")
            print("3. 대화 내용이 표시되고 답변 생성이 끝날 때까지 기다리기")
            input("\n준비됐으면 이 터미널에서 Enter: ")

            pages = [
                tab for tab in context.pages
                if not tab.is_closed() and is_conversation(tab)
            ]

            if not pages:
                print("\n열린 대화 페이지를 찾지 못했습니다.")
                print("새 채팅 첫 화면이 아니라 기존 대화 하나를 열어주세요.")
                return

            if len(pages) == 1:
                page = pages[0]
            else:
                print("\n열려 있는 대화를 선택해주세요.")
                for index, tab in enumerate(pages, 1):
                    print(f"{index}. {tab.title()}")

                choice = input("번호: ").strip()
                if not choice.isdigit() or not 1 <= int(choice) <= len(pages):
                    print("선택 번호가 올바르지 않습니다.")
                    return

                page = pages[int(choice) - 1]

            # 웹 화면의 메시지 영역을 읽습니다.
            # 화면 구조가 바뀌면 이 선택자를 조정해야 합니다.
            messages = page.locator(
                '[data-message-author-role="user"],'
                '[data-message-author-role="assistant"]'
            ).evaluate_all("""
                elements => elements.map(element => {
                    const content =
                        element.querySelector(".markdown") || element;
                    const wrapper =
                        element.closest("[data-message-id]");

                    return {
                        role: element.getAttribute("data-message-author-role"),
                        message_id: wrapper
                            ? wrapper.getAttribute("data-message-id")
                            : null,
                        text: content.innerText.trim()
                    };
                }).filter(message => message.text)
            """)

            users = [m for m in messages if m["role"] == "user"]
            assistants = [m for m in messages if m["role"] == "assistant"]

            print("\n===== 수집 확인 =====")
            print("대화 제목:", page.title())
            print("읽은 질문 수:", len(users))
            print("읽은 답변 수:", len(assistants))
            print(
                "메시지 ID 확인:",
                sum(bool(m["message_id"]) for m in messages),
                "개",
            )

            if not users or not assistants:
                print("\n질문·답변을 모두 확인하지 못했습니다.")
                print("로그인 상태와 대화 표시 상태를 확인해야 합니다.")
            else:
                print("\n첫 질문 미리보기:")
                print(users[0]["text"][:200])
                print("\n마지막 답변 미리보기:")
                print(assistants[-1]["text"][:300])
                print("\n현재 화면에 로드된 메시지만 읽었습니다.")
                print("긴 대화의 전체 수집 여부는 아직 확인하지 않았습니다.")
                print("DB에는 저장하지 않았습니다.")

            input("\n확인이 끝났으면 Enter를 눌러 브라우저 닫기: ")

        finally:
            context.close()


if __name__ == "__main__":
    main()
