import json
import os
import random
import re
import pdfplumber
import streamlit as st

# 페이지 기본 설정
st.set_page_config(
    page_title="전공영어 스마트 단어 퀴즈", page_icon="📖", layout="centered"
)

PDF_FILE_NAME = "단어장.pdf"
WRONG_WORDS_FILE = "wrong_words.json"


# 1. PDF 데이터 로드 및 파싱
@st.cache_data
def load_pdf_data():
    extracted_dict = {}
    if not os.path.exists(PDF_FILE_NAME):
        return None

    try:
        with pdfplumber.open(PDF_FILE_NAME) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if len(row) >= 2:
                            w = re.sub(r"[★☐Πコロ]", "", row[0] or "").strip()
                            m = re.sub(r"[★☐Πコロ]", "", row[1] or "").strip()
                            if (
                                w
                                and m
                                and w not in ["영어", "목차"]
                                and m not in ["한글 뜻", "암기"]
                            ):
                                extracted_dict[w] = m

                if not tables:
                    text = page.extract_text()
                    if text:
                        for line in text.split("\n"):
                            if "|" in line:
                                parts = line.split("|")
                                if len(parts) >= 2:
                                    w = re.sub(
                                        r"[★☐Πコロ]", "", parts[0]
                                    ).strip()
                                    m = re.sub(
                                        r"[★☐Πコロ]", "", parts[1]
                                    ).strip()
                                    if (
                                        w
                                        and m
                                        and w not in ["영어", "목차"]
                                        and m not in ["한글 뜻", "암기"]
                                    ):
                                        extracted_dict[w] = m
    except Exception as e:
        st.error(f"PDF 파일 처리 중 오류 발생: {e}")
        return None

    return extracted_dict


# 2. 오답노트 처리
def load_wrong_words():
    if os.path.exists(WRONG_WORDS_FILE):
        try:
            with open(WRONG_WORDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_wrong_words(wrong_dict):
    try:
        with open(WRONG_WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(wrong_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"오답노트 저장 실패: {e}")


# 세션 상태 초기화
if "word_dict" not in st.session_state:
    st.session_state.word_dict = load_pdf_data()
if "wrong_words" not in st.session_state:
    st.session_state.wrong_words = load_wrong_words()
if "quiz_mode" not in st.session_state:
    st.session_state.quiz_mode = "practice"
if "current_word" not in st.session_state:
    st.session_state.current_word = None
if "current_options" not in st.session_state:
    st.session_state.current_options = []
if "score" not in st.session_state:
    st.session_state.score = 0
if "total_asked" not in st.session_state:
    st.session_state.total_asked = 0
if "answered" not in st.session_state:
    st.session_state.answered = False
if "feedback" not in st.session_state:
    st.session_state.feedback = None

word_dict = st.session_state.word_dict

if not word_dict:
    st.error(
        f"'{PDF_FILE_NAME}' 파일을 찾을 수 없거나 단어를 추출하지 못했습니다."
    )
    st.stop()


def get_words_pool():
    if st.session_state.quiz_mode == "wrong_only":
        return list(st.session_state.wrong_words.keys())
    return list(word_dict.keys())


def next_question():
    pool = get_words_pool()
    if not pool:
        st.session_state.current_word = None
        st.session_state.current_options = []
    else:
        # 단어 선정
        curr_w = random.choice(pool)
        st.session_state.current_word = curr_w

        # 정답 추출
        if st.session_state.quiz_mode == "wrong_only":
            correct_meaning = st.session_state.wrong_words.get(curr_w, "")
        else:
            correct_meaning = word_dict.get(curr_w, "")

        # 보기 4개 미리 생성 후 세션에 고정 저장 (혼선 방지 핵심!)
        all_meanings = list(word_dict.values())
        wrong_options = [m for m in all_meanings if m != correct_meaning]
        sample_count = min(3, len(wrong_options))

        options = random.sample(wrong_options, sample_count) + [
            correct_meaning
        ]
        random.shuffle(options)
        st.session_state.current_options = options

    st.session_state.answered = False
    st.session_state.feedback = None


if st.session_state.current_word is None:
    next_question()

# UI 구성
st.title("📖 전공영어 스마트 단어 퀴즈")

# 모드 선택 버튼
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("일반 연습", use_container_width=True):
        st.session_state.quiz_mode = "practice"
        st.session_state.score = 0
        st.session_state.total_asked = 0
        next_question()
        st.rerun()

with col2:
    if st.button("🎮 20문제 챌린지", use_container_width=True):
        st.session_state.quiz_mode = "game_20"
        st.session_state.score = 0
        st.session_state.total_asked = 0
        next_question()
        st.rerun()

with col3:
    if st.button("✍️ 오답노트 퀴즈", use_container_width=True):
        if not st.session_state.wrong_words:
            st.toast("저장된 오답이 없습니다!")
        else:
            st.session_state.quiz_mode = "wrong_only"
            st.session_state.score = 0
            st.session_state.total_asked = 0
            next_question()
            st.rerun()

st.divider()

# 점수판
info_col1, info_col2 = st.columns(2)
with info_col1:
    if st.session_state.quiz_mode == "game_20":
        st.caption(
            f"**진행:** {st.session_state.total_asked} / 20 문제 | **점수:** {st.session_state.score}점"
        )
    else:
        st.caption(
            f"**점수:** {st.session_state.score} / {st.session_state.total_asked}"
        )
with info_col2:
    st.caption(f"**누적 오답:** {len(st.session_state.wrong_words)}개")

# 20문제 게임 완료 체크
if (
    st.session_state.quiz_mode == "game_20"
    and st.session_state.total_asked >= 20
):
    st.balloons()
    st.success(
        f"🎉 20문제를 모두 풀었습니다! 최종 점수: {st.session_state.score} / 20 점"
    )
    if st.button("다시 도전하기", use_container_width=True):
        st.session_state.score = 0
        st.session_state.total_asked = 0
        next_question()
        st.rerun()
    st.stop()

# 문제 출력 카드
curr_word = st.session_state.current_word
if not curr_word:
    st.warning("출제할 단어가 없습니다.")
    st.stop()

if st.session_state.quiz_mode == "wrong_only":
    correct_meaning = st.session_state.wrong_words.get(curr_word, "")
else:
    correct_meaning = word_dict.get(curr_word, "")

st.info(f"### **{curr_word}**")

# 고정된 보기 가져오기
options = st.session_state.current_options

# 보기 버튼 및 채점
for i, opt in enumerate(options):
    btn_disabled = st.session_state.answered
    if st.button(
        f"{i+1}. {opt}",
        key=f"opt_{i}",
        disabled=btn_disabled,
        use_container_width=True,
    ):
        st.session_state.answered = True
        st.session_state.total_asked += 1

        if opt == correct_meaning:
            st.session_state.score += 1
            st.session_state.feedback = ("success", "⭕ 정답입니다!")
            if curr_word in st.session_state.wrong_words:
                del st.session_state.wrong_words[curr_word]
                save_wrong_words(st.session_state.wrong_words)
        else:
            st.session_state.feedback = (
                "error",
                f"❌ 오답입니다. (정답: {correct_meaning})",
            )
            st.session_state.wrong_words[curr_word] = correct_meaning
            save_wrong_words(st.session_state.wrong_words)

        st.rerun()

# 결과 피드백 및 다음 문제 버튼
if st.session_state.feedback:
    fb_type, fb_msg = st.session_state.feedback
    if fb_type == "success":
        st.success(fb_msg)
    else:
        st.error(fb_msg)

if st.session_state.answered:
    if st.button("다음 문제 ➔", type="primary", use_container_width=True):
        next_question()
        st.rerun()
