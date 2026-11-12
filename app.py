from difflib import SequenceMatcher
import json
import os
import random
import re
from google import genai
import pdfplumber
import streamlit as st

# 페이지 기본 설정
st.set_page_config(
    page_title="전공영어 스마트 단어 퀴즈", page_icon="📖", layout="centered"
)

PDF_FILE_NAME = "단어장.pdf"
WRONG_WORDS_FILE = "wrong_words.json"


# Gemini API 클라이언트 초기화
def get_ai_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            api_key = None

    if api_key:
        try:
            return genai.Client(api_key=api_key)
        except Exception:
            return None
    return None


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


# 한국어 접사/조사 정규화 보조 함수 ('예방적 서비스' -> '예방서비스')
def normalize_korean(text):
    cleaned = re.sub(r"\s+", "", text.strip()).lower()
    # 번역 과정에서 자주 붙는 '-적', '-의', '-한' 등 제거
    cleaned = re.sub(r"(적|의|한)(?=[가-힣])", "", cleaned)
    return cleaned


# [개선됨] AI 초유연 채점 + 접사/유사도 스마트 판별 함수
def judge_with_ai(english_word, user_answer, dictionary_meaning):
    u_raw = user_answer.strip()
    if not u_raw:
        return False, "답변이 입력되지 않았습니다."

    u_clean = re.sub(r"\s+", "", u_raw).lower()
    d_clean = re.sub(r"\s+", "", dictionary_meaning.strip()).lower()

    # 1차: 완전 일치 및 포함 검사
    if u_clean in d_clean or d_clean in u_clean:
        return True, "사전 뜻과 일치합니다."

    # 2차: 한국어 접사('-적', '-의' 등) 제거 후 일치 검사 ('예방적 서비스' == '예방서비스')
    u_norm = normalize_korean(u_raw)
    d_norm = normalize_korean(dictionary_meaning)
    if u_norm and (u_norm in d_norm or d_norm in u_norm):
        return True, "접사/표현 차이를 반영하여 정답으로 인정되었습니다."

    # 3차: AI API를 이용한 관대한 번역·문맥 의미 판별
    client = get_ai_client()
    if client:
        try:
            prompt = f"""
            당신은 대학원 영어 시험 대비를 돕는 매우 관대하고 유연한 채점관입니다.
            
            - 출제 영어 표현: '{english_word}'
            - 단어장 기준 뜻: '{dictionary_meaning}'
            - 학습자 입력 답안: '{user_answer}'
            
            [절대 준수 채점 원칙]
            1. 한국어 번역 특성상 붙거나 빠지는 접사·조사 차이('-적', '-의', '-한', '-화', '-성' 등)는 100% 동일한 정답(CORRECT)으로 인정하세요.
               * 핵심 예시: '예방서비스' <-> '예방적 서비스' (무조건 CORRECT)
               * 핵심 예시: '구조불평등' <-> '구조적 불평등' (무조건 CORRECT)
               * 핵심 예시: '심리재활' <-> '심리적 재활' (무조건 CORRECT)
            2. 글자가 다르더라도 영어 독해 문맥상 뜻이 통하는 유의어, 동의어, 자연스러운 의역이면 모두 정답(CORRECT)으로 인정하세요.
               * 예시: '완화하다' <-> '줄이다', '경감시키다', '약화시키다' (CORRECT)
            3. 품사 차이(명사형 vs 동사형 vs 형용사형, 예: '사정' <-> '평가하다')나 띄어쓰기 차이는 무시하고 핵심 의미가 맞으면 정답(CORRECT) 처리하세요.
            4. 전혀 다른 엉뚱한 뜻이나 반대 의미일 때만 오답(INCORRECT) 처리하세요.
            
            반드시 첫 줄에 'CORRECT' 또는 'INCORRECT'만 출력하고, 둘째 줄에 학습자에게 도움이 되는 짧은 피드백 한 문장을 작성하세요.
            """
            response = client.models.generate_content(
                model="gemini-2.5-flash", contents=prompt
            )
            text_res = response.text.strip()
            lines = [
                line.strip() for line in text_res.split("\n") if line.strip()
            ]

            if (
                lines
                and "CORRECT" in lines[0].upper()
                and "INCORRECT" not in lines[0].upper()
            ):
                reason = (
                    lines[1]
                    if len(lines) > 1
                    else "문맥상 의미가 통해 정답으로 인정되었습니다."
                )
                return True, reason
            else:
                reason = (
                    lines[1]
                    if len(lines) > 1
                    else "핵심 의미와 다소 거리가 있습니다."
                )
                return False, reason
        except Exception as e:
            print(f"AI 채점 중 오류 발생: {e}")

    # 4차: API 미연결 시 백업 키워드 및 문자열 유사도(75% 이상) 검사
    keywords = [
        k.strip() for k in dictionary_meaning.replace("/", ",").split(",") if k
    ]
    for kw in keywords:
        kw_norm = normalize_korean(kw)
        if not kw_norm:
            continue
        if kw_norm in u_norm or u_norm in kw_norm:
            return True, "핵심 의미가 일치합니다."
        similarity = SequenceMatcher(None, u_norm, kw_norm).ratio()
        if similarity >= 0.75:
            return True, "유사한 표현으로 정답 인정되었습니다."

    return False, "사전적 의미와 일치하지 않습니다."


# 세션 상태 초기화
if "word_dict" not in st.session_state:
    st.session_state.word_dict = load_pdf_data()
if "wrong_words" not in st.session_state:
    st.session_state.wrong_words = load_wrong_words()
if "quiz_mode" not in st.session_state:
    st.session_state.quiz_mode = "practice"
if "question_type" not in st.session_state:
    st.session_state.question_type = "choice"
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
        curr_w = random.choice(pool)
        st.session_state.current_word = curr_w

        if st.session_state.quiz_mode == "wrong_only":
            correct_meaning = st.session_state.wrong_words.get(curr_w, "")
        else:
            correct_meaning = word_dict.get(curr_w, "")

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

# 1. 문제 방식 선택
q_type = st.radio(
    "📝 문제 방식 선택",
    ["4지선다 객관식", "🤖 AI 유연 주관식 채점"],
    horizontal=True,
)
new_q_type = "choice" if q_type == "4지선다 객관식" else "subjective"
if new_q_type != st.session_state.question_type:
    st.session_state.question_type = new_q_type
    next_question()
    st.rerun()

# AI 주관식 선택 시 연결 상태 안내
if st.session_state.question_type == "subjective":
    if get_ai_client():
        st.caption(
            "🟢 AI 유연 채점 활성화됨 (접사·유의어·의역 표현 자동 정답 인정)"
        )
    else:
        st.caption(
            "🟡 스마트 유사도 채점 모드 (접사 및 키워드 유사도 기반 자동 정답 인정)"
        )

# 2. 게임 모드 선택 버튼
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

# --------------------------------------------------
# 모드 1: 4지선다 객관식
# --------------------------------------------------
if st.session_state.question_type == "choice":
    options = st.session_state.current_options
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

# --------------------------------------------------
# 모드 2: 🤖 AI 유연 주관식 채점
# --------------------------------------------------
else:
    with st.form(key="subjective_form", clear_on_submit=False):
        user_ans = st.text_input(
            "단어의 뜻을 입력하세요:",
            placeholder="의미가 통하는 표현이면 자유롭게 정답 인정됩니다...",
            disabled=st.session_state.answered,
        )
        submit_btn = st.form_submit_button(
            "AI 심사 제출",
            use_container_width=True,
            disabled=st.session_state.answered,
        )

        if submit_btn:
            st.session_state.answered = True
            st.session_state.total_asked += 1

            with st.spinner("🤖 AI가 문맥과 의미를 유연하게 심사 중..."):
                is_correct, reason = judge_with_ai(
                    curr_word, user_ans, correct_meaning
                )

            if is_correct:
                st.session_state.score += 1
                st.session_state.feedback = (
                    "success",
                    f"⭕ 정답입니다! ({reason})\n- 단어장 뜻: {correct_meaning}",
                )
                if curr_word in st.session_state.wrong_words:
                    del st.session_state.wrong_words[curr_word]
                    save_wrong_words(st.session_state.wrong_words)
            else:
                st.session_state.feedback = (
                    "error",
                    f"❌ 오답입니다. ({reason})\n- 제출한 답: {user_ans}\n- 단어장 뜻: {correct_meaning}",
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
