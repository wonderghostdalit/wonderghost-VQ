from difflib import SequenceMatcher
import json
import os
import random
import re
import time
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

# 503 서버 혼잡 우회용 안정 모델 리스트
ETYMOLOGY_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]


# Gemini API 클라이언트 캐싱 초기화
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


# 틀린 단어 전용: AI 어원·접두사·어근 논리 분해 생성 함수
def generate_etymology_analysis(english_word, korean_meaning):
    client = get_ai_client()
    if not client:
        return "⚠️ Gemini API 키가 연결되어 있지 않아 어원 분석을 생성할 수 없습니다. Streamlit Secrets에 GEMINI_API_KEY를 등록해 주세요."

    prompt = f"""
    당신은 영어 어원학(Etymology)과 형태소 분석에 정통한 일타 강사입니다.
    학습자가 아래 영어 표현을 틀렸습니다. 단어의 구성 요소(접두사·어근·접미사 또는 핵심 단어 결합)를 논리적으로 분해해서 뜻을 추론할 수 있도록 설명해 주세요. (억지 발음 연상이나 말장난은 절대 쓰지 마세요.)

    - 영단어/표현: {english_word}
    - 한글 뜻: {korean_meaning}

    [작성 형식 - 반드시 아래 3가지 구조로 명확하고 간결하게 작성]
    1. 🧩 **형태소 분해:** (예: `ab-` (반대·이탈) + `normal` (정상적인) 형태처럼 접두사/어근/접미사 각각의 기본 의미 명시)
    2. 💡 **의미 도출 논리:** (분해된 조각들이 어떻게 합쳐져서 '{korean_meaning}'이라는 뜻이 되는지 한 줄 연결)
    3. 🔗 **같은 접두사·어근 확장 단어 (2개):** (이 원리를 그대로 적용할 수 있는 영단어 2개와 짧은 분해 풀이)
    """

    last_error = ""
    for model_name in ETYMOLOGY_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=350,
                    temperature=0.3,
                ),
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            last_error = str(e)
            if any(
                code in last_error
                for code in ["503", "429", "404", "UNAVAILABLE", "overloaded"]
            ):
                time.sleep(0.4)
                continue
            else:
                break

    return f"⚠️ 현재 구글 AI 서버 접속량이 많아 일시적으로 지연되고 있습니다. 아래 '🔄 어원 분석 다시 시도하기' 버튼을 눌러주세요.\n(상세: {last_error[:90]})"


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


# [신규] 영단어 및 한글 뜻 패턴 기반 품사·유형 자동 분류 함수
def classify_pos(word, meaning):
    w_clean = word.strip()
    # 첫 번째 대표 뜻 기준으로 끝맺음 어미 분석
    primary_m = re.split(r"[,/]", meaning)[0].strip()
    # 괄호 안 부가설명 제거
    primary_m = re.sub(r"\([^)]*\)", "", primary_m).strip()

    # 1. 숙어·구동사·구문 (공백이 포함된 2단어 이상 표현)
    if " " in w_clean:
        return "숙어·구문"

    # 2. 부사 (-ly 접미사 또는 '~하게', '~히', '~적으로' 종료)
    if (
        w_clean.lower().endswith("ly")
        and len(w_clean) > 4
        or re.search(r"(하게|히|적으로|로서|로써)$", primary_m)
    ):
        return "부사"

    # 3. 동사 ('~하다', '~되다', '~시키다', '~주다', '~받다', '~지다', '~이다' 등 용언 종결형)
    if re.search(
        r"(하다|되다|시키다|주다|받다|지다|나다|내다|가다|오다|두다|보다|삼다|입다|얻다|잃다|막다|돕다|찾다|품다|겪다|맺다|풀다|잇다|짓다|끄다|쓰다|트다|크다)$",
        primary_m,
    ):
        return "동사"

    # 4. 형용사 ('~적인', '~한', '~된', '~할', '~없는', '~있는', '~스러운', '~로운' 등 관형형)
    if re.search(
        r"(적인|한|된|할|없는|있는|스러운|로운|다운|같은|높은|낮은|많은|적은|큰|작은|새로운|오래된|중요한|주요한)$",
        primary_m,
    ):
        return "형용사"

    # 5. 나머지 일반 명사 및 개념어
    return "명사·기타"


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


# 초고속 스마트 유사도 판별 함수
def evaluate_subjective_fast(user_answer, dictionary_meaning):
    u_raw = user_answer.strip()
    if not u_raw:
        return False, "답변이 입력되지 않았습니다."

    u_clean = re.sub(r"\s+", "", u_raw).lower()
    d_clean = re.sub(r"\s+", "", dictionary_meaning.strip()).lower()

    if u_clean in d_clean or d_clean in u_clean:
        return True, "사전 뜻과 일치합니다."

    u_norm = normalize_korean(u_raw)
    d_norm = normalize_korean(dictionary_meaning)
    if u_norm and (u_norm in d_norm or d_norm in u_norm):
        return True, "표현·접사 차이를 반영하여 정답 인정되었습니다."

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
        if similarity >= 0.65:
            return (
                True,
                f"유사도 기준({int(similarity*100)}%)을 통과하여 정답 인정되었습니다.",
            )

    return False, "사전적 의미와 일치하지 않습니다."


# 세션 상태 초기화
word_dict = load_pdf_data()
st.session_state.word_dict = word_dict

if not word_dict:
    st.error(
        f"'{PDF_FILE_NAME}' 파일을 찾을 수 없거나 단어를 추출하지 못했습니다."
    )
    st.stop()

# 단어별 품사 매핑 딕셔너리 생성
pos_map = {w: classify_pos(w, m) for w, m in word_dict.items()}

if "wrong_words" not in st.session_state:
    st.session_state.wrong_words = load_wrong_words()
if "quiz_mode" not in st.session_state:
    st.session_state.quiz_mode = "practice"
if "question_type" not in st.session_state:
    st.session_state.question_type = "choice"
if "pos_filter" not in st.session_state:
    st.session_state.pos_filter = "전체"
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

if st.session_state.current_word and (
    st.session_state.current_word not in word_dict
    and st.session_state.current_word not in st.session_state.wrong_words
):
    st.session_state.current_word = None


# 현재 모드 + 품사 필터가 모두 반영된 출제 단어 풀 반환
def get_words_pool():
    if st.session_state.quiz_mode == "wrong_only":
        base_pool = list(st.session_state.wrong_words.keys())
    else:
        base_pool = list(word_dict.keys())

    selected_pos = st.session_state.pos_filter
    if selected_pos == "전체":
        return base_pool

    return [
        w
        for w in base_pool
        if classify_pos(
            w,
            st.session_state.wrong_words.get(w, word_dict.get(w, "")),
        )
        == selected_pos
    ]


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

        # 객관식 보기도 가급적 같은 품사군에서 먼저 뽑아 난이도와 자연스러움 향상
        curr_pos = classify_pos(curr_w, correct_meaning)
        same_pos_meanings = [
            m
            for w, m in word_dict.items()
            if m != correct_meaning and pos_map.get(w) == curr_pos
        ]
        if len(same_pos_meanings) >= 3:
            wrong_options = same_pos_meanings
        else:
            wrong_options = [
                m for m in word_dict.values() if m != correct_meaning
            ]

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

# 2. 품사·유형별 필터 선택 영역
pos_categories = ["전체", "동사", "형용사", "부사", "숙어·구문", "명사·기타"]
pos_counts = {
    cat: (
        len(word_dict)
        if cat == "전체"
        else sum(1 for v in pos_map.values() if v == cat)
    )
    for cat in pos_categories
}

selected_pos = st.selectbox(
    "🏷️ 품사·유형별 집중 학습 필터",
    options=pos_categories,
    index=pos_categories.index(st.session_state.pos_filter),
    format_func=lambda x: f"{x} ({pos_counts[x]}개)",
)

if selected_pos != st.session_state.pos_filter:
    st.session_state.pos_filter = selected_pos
    st.session_state.score = 0
    st.session_state.total_asked = 0
    next_question()
    st.rerun()

# 3. 게임 모드 선택 버튼
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
active_pool_count = len(get_words_pool())
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
        f"**현재 범위({st.session_state.pos_filter}):** {active_pool_count}개 | **누적 오답:** {len(st.session_state.wrong_words)}개"
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
    st.warning(
        f"선택하신 **'{st.session_state.pos_filter}'** 분류에 해당하는 출제 단어가 없습니다. 다른 품사나 '전체'를 선택해 주세요."
    )
    st.stop()

if st.session_state.quiz_mode == "wrong_only":
    correct_meaning = st.session_state.wrong_words.get(curr_word, "")
else:
    correct_meaning = word_dict.get(curr_word, "")

curr_word_pos = classify_pos(curr_word, correct_meaning)
st.info(f"`[{curr_word_pos}]`\n### **{curr_word}**")

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
# 모드 2: 주관식 채점 (초고속 즉시 판별)
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
        submit_btn = st.form_submit_button(
            "⚡ 정답 제출 (Enter)",
            use_container_width=True,
            disabled=st.session_state.answered,
        )

        if submit_btn:
            st.session_state.answered = True
            st.session_state.total_asked += 1

            is_correct, reason = evaluate_subjective_fast(
                user_ans, correct_meaning
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

# 정답 제출 후 추가 기능 (오답일 때만 AI 형태소·어원 풀이 실행)
if st.session_state.answered:
    if st.session_state.last_was_wrong:
        if curr_word not in st.session_state.etymology_cache:
            with st.spinner("🧩 틀린 단어의 접두사·어근 형태소 분석 중..."):
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
            if current_etym.startswith("⚠️"):
                if st.button("🔄 어원 분석 다시 시도하기", key="retry_etym"):
                    st.rerun()

    # 주관식 수동 정답 인정 안전장치
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
