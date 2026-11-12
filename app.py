from difflib import SequenceMatcher
import json
import os
import random
import re
from google import genai
from google.genai import types
import pdfplumber
import streamlit as st
import streamlit.components.v1 as components

# 페이지 기본 설정
st.set_page_config(
    page_title="전공영어 스마트 단어 퀴즈", page_icon="📖", layout="centered"
)

PDF_FILE_NAME = "단어장.pdf"
WRONG_WORDS_FILE = "wrong_words.json"
FAST_JUDGE_MODEL = "gemini-3.8-flash-lite"  # 초고속 채점 전용 경량 모델
ETYMOLOGY_MODEL = "gemini-3.8-flash"  # 상세 어원 분석 모델


# Gemini API 클라이언트 캐싱 초기화 (매번 재연결하는 지연 시간 제거)
@st.cache_resource
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


# 어원·접두사·어근 논리 분해 AI 생성 함수
def generate_etymology_analysis(english_word, korean_meaning):
    client = get_ai_client()
    if not client:
        return "⚠️ Gemini API 키가 연결되어 있지 않아 어원 분석을 생성할 수 없습니다. Streamlit Secrets에 GEMINI_API_KEY를 등록해 주세요."

    try:
        prompt = f"""
        당신은 영어 어원학(Etymology)과 형태소 분석에 정통한 강사입니다.
        학습자가 아래 영어 표현의 뜻을 논리적으로 추론할 수 있도록, 구성 요소(접두사·어근·접미사 또는 핵심 단어 결합)를 분해해서 설명해 주세요. (발음 연상/말장난 금지)

        - 영단어/표현: {english_word}
        - 한글 뜻: {korean_meaning}

        [작성 형식]
        1. 🧩 **형태소 분해:** (예: `ab-` (반대·이탈) + `normal` (정상적인))
        2. 💡 **의미 도출 논리:** (합쳐져서 '{korean_meaning}'이 되는 논리 1문장)
        3. 🔗 **확장 단어 (2개):** (같은 접두사·어근 단어 2개와 짧은 분해)
        """
        response = client.models.generate_content(
            model=ETYMOLOGY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=350),
        )
        return response.text.strip()
    except Exception as e:
        return f"⚠️ 어원 분석 생성 중 오류가 발생했습니다: {e}"


# 유효한 영단어-한글뜻 쌍인지 검증하는 필터 함수
def is_valid_vocab_pair(word, meaning):
    if not word or not meaning:
        return False
    if word in ["영어", "목차", "단어", "표현"] or meaning in ["한글 뜻", "암기", "뜻", "의미"]:
        return False
    if not re.search(r"[a-zA-Z]", word):
        return False
    if not re.search(r"[가-힣]", meaning):
        return False
    return True


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
                            w = re.sub(r"\s+", " ", w)
                            m = re.sub(r"\s+", " ", m)
                            if is_valid_vocab_pair(w, m):
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
                                    if is_valid_vocab_pair(w, m):
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
                raw_data = json.load(f)
                cleaned_data = {
                    k: v
                    for k, v in raw_data.items()
                    if is_valid_vocab_pair(k, v)
                }
                if len(cleaned_data) != len(raw_data):
                    save_wrong_words(cleaned_data)
                return cleaned_data
        except Exception:
            return {}
    return {}


def save_wrong_words(wrong_dict):
    try:
        with open(WRONG_WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(wrong_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"오답노트 저장 실패: {e}")


# 한국어 접사/조사 정규화 보조 함수
def normalize_korean(text):
    cleaned = re.sub(r"\s+", "", text.strip()).lower()
    cleaned = re.sub(r"(적|의|한)(?=[가-힣])", "", cleaned)
    return cleaned


# 스마트 유사도 판별 단독 함수
def judge_with_similarity(user_answer, dictionary_meaning, threshold=0.65):
    u_raw = user_answer.strip()
    u_clean = re.sub(r"\s+", "", u_raw).lower()
    d_clean = re.sub(r"\s+", "", dictionary_meaning.strip()).lower()

    if u_clean in d_clean or d_clean in u_clean:
        return True, "사전 뜻과 직접 일치합니다."

    u_norm = normalize_korean(u_raw)
    d_norm = normalize_korean(dictionary_meaning)
    if u_norm and (u_norm in d_norm or d_norm in u_norm):
        return True, "접사 및 표현 차이를 반영하여 정답 인정되었습니다."

    keywords = [
        k.strip() for k in dictionary_meaning.replace("/", ",").split(",") if k
    ]
    for kw in keywords:
        kw_norm = normalize_korean(kw)
        if not kw_norm:
            continue
        if kw_norm in u_norm or u_norm in kw_norm:
            return True, "핵심 키워드가 일치합니다."
        similarity = SequenceMatcher(None, u_norm, kw_norm).ratio()
        if similarity >= threshold:
            return (
                True,
                f"유사도 기준({int(similarity*100)}%)을 통과하여 정답 인정되었습니다.",
            )

    return False, "유사도 기준과 일치하지 않습니다."


# [속도 최적화] 통합 주관식 채점 함수
def evaluate_subjective(
    english_word, user_answer, dictionary_meaning, use_ai=True
):
    u_raw = user_answer.strip()
    if not u_raw:
        return False, "답변이 입력되지 않았습니다."

    # 1단계: API 통신 없는 즉각 로컬 고속 필터 (명확한 일치/고유사도 0.01초 내 즉시 통과)
    is_fast_match, fast_reason = judge_with_similarity(
        u_raw, dictionary_meaning, threshold=0.80
    )
    if is_fast_match:
        return True, fast_reason

    # 2단계: 유의어·의역이 필요한 경우에만 초경량 AI 모델 호출 (토큰 및 사고 시간 최소화)
    if use_ai:
        client = get_ai_client()
        if client:
            try:
                prompt = (
                    f"영단어 '{english_word}'의 뜻은 '{dictionary_meaning}', 답안은 '{user_answer}'이다. "
                    f"유의어, 의역, 품사/접사('-적','-의') 차이는 관대하게 정답 인정한다. "
                    f"첫 줄에 CORRECT 또는 INCORRECT만, 둘째 줄에 짧은 이유 15자 이내로 출력하라."
                )
                response = client.models.generate_content(
                    model=FAST_JUDGE_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=60,
                        temperature=0.1,
                    ),
                )
                text_res = response.text.strip()
                lines = [
                    line.strip()
                    for line in text_res.split("\n")
                    if line.strip()
                ]

                if (
                    lines
                    and "CORRECT" in lines[0].upper()
                    and "INCORRECT" not in lines[0].upper()
                ):
                    reason = (
                        lines[1]
                        if len(lines) > 1
                        else "유의어로 인정되었습니다."
                    )
                    return True, reason
                else:
                    reason = (
                        lines[1]
                        if len(lines) > 1
                        else "사전적 의미와 다릅니다."
                    )
                    return False, reason
            except Exception as e:
                print(f"AI 채점 오류 (유사도 모드로 전환): {e}")

    # 3단계: AI 미사용 또는 오류 시 기본 유사도(0.65) 판정
    return judge_with_similarity(user_answer, dictionary_meaning, threshold=0.65)


# 세션 상태 초기화
word_dict = load_pdf_data()
st.session_state.word_dict = word_dict

if "wrong_words" not in st.session_state:
    st.session_state.wrong_words = load_wrong_words()
if "quiz_mode" not in st.session_state:
    st.session_state.quiz_mode = "practice"
if "question_type" not in st.session_state:
    st.session_state.question_type = "choice"
if "use_ai_grading" not in st.session_state:
    st.session_state.use_ai_grading = True
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
if "last_was_wrong" not in st.session_state:
    st.session_state.last_was_wrong = False
if "etymology_cache" not in st.session_state:
    st.session_state.etymology_cache = {}
if "question_counter" not in st.session_state:
    st.session_state.question_counter = 0

if not word_dict:
    st.error(
        f"'{PDF_FILE_NAME}' 파일을 찾을 수 없거나 단어를 추출하지 못했습니다."
    )
    st.stop()

if st.session_state.current_word and (
    st.session_state.current_word not in word_dict
    and st.session_state.current_word not in st.session_state.wrong_words
):
    st.session_state.current_word = None


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
    st.session_state.last_was_wrong = False
    st.session_state.question_counter += 1


if st.session_state.current_word is None:
    next_question()

# UI 구성
st.title("📖 전공영어 스마트 단어 퀴즈")

# 1. 문제 방식 선택
q_type = st.radio(
    "📝 문제 방식 선택",
    ["4지선다 객관식", "✍️ 주관식 뜻 입력"],
    horizontal=True,
)
new_q_type = "choice" if q_type == "4지선다 객관식" else "subjective"
if new_q_type != st.session_state.question_type:
    st.session_state.question_type = new_q_type
    next_question()
    st.rerun()

# 주관식 선택 시 채점 엔진 ON/OFF 토글 스위치 제공
if st.session_state.question_type == "subjective":
    ai_available = get_ai_client() is not None

    use_ai = st.toggle(
        "🤖 AI 유연 채점 모드 켜기 (끄면 초고속 스마트 유사도 채점 모드로 동작)",
        value=st.session_state.use_ai_grading,
        disabled=not ai_available,
    )
    st.session_state.use_ai_grading = use_ai

    if not ai_available:
        st.caption(
            "⚠️ API 키가 등록되지 않아 자동으로 **🟡 스마트 유사도 채점 모드**가 적용됩니다."
        )
    elif use_ai:
        st.caption(
            "🟢 **AI 고속 유연 채점 활성화됨**: 일치 표현은 즉시 통과, 유의어는 경량 AI가 빠르게 판별합니다."
        )
    else:
        st.caption(
            "🟡 **스마트 유사도 채점 모드**: API 대기 시간 없이 접사·키워드 유사도로 즉시 채점합니다."
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
    st.caption(
        f"**총 단어:** {len(word_dict)}개 | **누적 오답:** {len(st.session_state.wrong_words)}개"
    )

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
                st.session_state.last_was_wrong = False
                if curr_word in st.session_state.wrong_words:
                    del st.session_state.wrong_words[curr_word]
                    save_wrong_words(st.session_state.wrong_words)
            else:
                st.session_state.feedback = (
                    "error",
                    f"❌ 오답입니다. (정답: {correct_meaning})",
                )
                st.session_state.last_was_wrong = True
                st.session_state.wrong_words[curr_word] = correct_meaning
                save_wrong_words(st.session_state.wrong_words)

            st.rerun()

# --------------------------------------------------
# 모드 2: 주관식 채점
# --------------------------------------------------
else:
    q_idx = st.session_state.question_counter
    with st.form(key=f"subjective_form_{q_idx}", clear_on_submit=False):
        user_ans = st.text_input(
            "단어의 뜻을 입력하세요 (엔터: 제출 / 결과 확인 후 엔터 한 번 더: 다음 문제):",
            placeholder="단어의 뜻을 자유롭게 입력하세요...",
            disabled=st.session_state.answered,
            key=f"input_{q_idx}",
        )
        btn_label = (
            "🤖 AI 심사 제출 (Enter)"
            if (st.session_state.use_ai_grading and get_ai_client())
            else "⚡ 정답 제출 (Enter)"
        )
        submit_btn = st.form_submit_button(
            btn_label,
            use_container_width=True,
            disabled=st.session_state.answered,
        )

        if submit_btn:
            st.session_state.answered = True
            st.session_state.total_asked += 1

            active_ai = st.session_state.use_ai_grading and (
                get_ai_client() is not None
            )
            if active_ai:
                with st.spinner("⚡ 채점 중..."):
                    is_correct, reason = evaluate_subjective(
                        curr_word, user_ans, correct_meaning, use_ai=True
                    )
            else:
                is_correct, reason = evaluate_subjective(
                    curr_word, user_ans, correct_meaning, use_ai=False
                )

            if is_correct:
                st.session_state.score += 1
                st.session_state.feedback = (
                    "success",
                    f"⭕ 정답입니다! ({reason})\n- 단어장 뜻: {correct_meaning}",
                )
                st.session_state.last_was_wrong = False
                if curr_word in st.session_state.wrong_words:
                    del st.session_state.wrong_words[curr_word]
                    save_wrong_words(st.session_state.wrong_words)
            else:
                st.session_state.feedback = (
                    "error",
                    f"❌ 오답입니다. ({reason})\n- 제출한 답: {user_ans}\n- 단어장 뜻: {correct_meaning}",
                )
                st.session_state.last_was_wrong = True
                st.session_state.wrong_words[curr_word] = correct_meaning
                save_wrong_words(st.session_state.wrong_words)

            st.rerun()

# 결과 피드백 영역
if st.session_state.feedback:
    fb_type, fb_msg = st.session_state.feedback
    if fb_type == "success":
        st.success(fb_msg)
    else:
        st.error(fb_msg)

# 정답 제출 후 추가 기능 (오답 시 자동 어원 풀이 / 수동 인정 / 다음 문제)
if st.session_state.answered:
    if st.session_state.last_was_wrong:
        if curr_word not in st.session_state.etymology_cache:
            with st.spinner("🧩 접두사·어근 구조 분석 중..."):
                analysis = generate_etymology_analysis(
                    curr_word, correct_meaning
                )
                if not analysis.startswith("⚠️"):
                    st.session_state.etymology_cache[curr_word] = analysis
                current_etym = analysis
        else:
            current_etym = st.session_state.etymology_cache[curr_word]

        with st.container(border=True):
            st.markdown(f"#### 🧩 **{curr_word}** 어원·형태소 구조 풀이")
            st.markdown(current_etym)

    if (
        st.session_state.last_was_wrong
        and st.session_state.question_type == "subjective"
    ):
        if st.button(
            "🙋‍♂️ 의미가 맞으므로 직접 정답으로 인정하기",
            use_container_width=True,
        ):
            st.session_state.score += 1
            st.session_state.last_was_wrong = False
            st.session_state.feedback = (
                "success",
                f"⭕ 수동으로 정답 인정되었습니다!\n- 단어장 뜻: {correct_meaning}",
            )
            if curr_word in st.session_state.wrong_words:
                del st.session_state.wrong_words[curr_word]
                save_wrong_words(st.session_state.wrong_words)
            st.rerun()

    if st.button(
        "다음 문제 ➔ (Enter)", type="primary", use_container_width=True
    ):
        next_question()
        st.rerun()

    # 키보드 Enter 키 감지하여 '다음 문제 ➔' 버튼 자동 실행
    components.html(
        """
        <script>
        const doc = window.parent.document;
        if (!window.parent._nextEnterListenerAdded) {
            window.parent._nextEnterListenerAdded = true;
            doc.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.isComposing) {
                    const buttons = Array.from(doc.querySelectorAll('button'));
                    const nextBtn = buttons.find(b => b.innerText.includes('다음 문제 ➔'));
                    if (nextBtn) {
                        e.preventDefault();
                        nextBtn.click();
                    }
                }
            });
        }
        </script>
        """,
        height=0,
    )
else:
    if st.session_state.question_type == "subjective":
        components.html(
            """
            <script>
            const doc = window.parent.document;
            setTimeout(() => {
                const inputs = doc.querySelectorAll('input[type="text"]');
                if (inputs.length > 0) {
                    const activeInput = inputs[inputs.length - 1];
                    if (!activeInput.disabled) {
                        activeInput.focus();
                    }
                }
            }, 150);
            </script>
            """,
            height=0,
        )
