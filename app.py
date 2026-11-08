import json
import os
import random
import re
import tkinter as tk
from tkinter import font, messagebox
import pdfplumber

# --------------------------------------------------
# [고해상도 디스플레이 DPI 깨짐 방지 설정]
# --------------------------------------------------
try:
    from ctypes import windll

    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

PDF_FILE_NAME = "단어장.pdf"
WRONG_WORDS_FILE = "wrong_words.json"


class VocabQuizApp:

    def __init__(self, root):
        self.root = root
        self.root.title("전공영어 퀴즈 프로그램")
        self.root.configure(bg="#F4F6F9")

        # 1. 고정 픽셀 대신 사용자 화면 크기를 계산하여 넉넉하게 자동 할당
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        app_width = int(screen_width * 0.55)
        app_height = int(screen_height * 0.85)

        # 최소 크기 지정 및 초기 크기 할당
        self.root.minsize(600, 700)
        self.root.geometry(f"{app_width}x{app_height}+100+50")

        # 폰트 설정
        self.font_title = font.Font(
            family="Malgun Gothic", size=15, weight="bold"
        )
        self.font_sub = font.Font(family="Malgun Gothic", size=10)
        self.font_word = font.Font(
            family="Malgun Gothic", size=20, weight="bold"
        )
        self.font_btn = font.Font(family="Malgun Gothic", size=11)
        self.font_feedback = font.Font(
            family="Malgun Gothic", size=12, weight="bold"
        )

        # 데이터 변수
        self.word_dict = {}
        self.words_list = []
        self.wrong_words = self.load_wrong_words()

        # 퀴즈 상태 변수
        self.quiz_mode = "practice"
        self.current_word = ""
        self.correct_answer = ""
        self.score = 0
        self.total_asked = 0
        self.max_questions = 0

        self.create_widgets()
        self.load_pdf_automatically()

    def load_wrong_words(self):
        if os.path.exists(WRONG_WORDS_FILE):
            try:
                with open(WRONG_WORDS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_wrong_words(self):
        try:
            with open(WRONG_WORDS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.wrong_words, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"오답노트 저장 실패: {e}")

    def create_widgets(self):
        # 상단 헤더 프레임 (여백 절감)
        header_frame = tk.Frame(self.root, bg="#2C3E50", pady=8)
        header_frame.pack(fill="x")

        self.lbl_title = tk.Label(
            header_frame,
            text="📖 전공영어 스마트 단어 퀴즈",
            font=self.font_title,
            fg="#FFFFFF",
            bg="#2C3E50",
        )
        self.lbl_title.pack()

        # 모드 선택 버튼 영역
        mode_frame = tk.Frame(self.root, bg="#F4F6F9")
        mode_frame.pack(fill="x", pady=6)

        self.btn_mode_practice = tk.Button(
            mode_frame,
            text="일반 무제한 연습",
            font=self.font_sub,
            bg="#34495E",
            fg="white",
            relief="flat",
            padx=10,
            pady=3,
            command=lambda: self.start_quiz("practice"),
        )
        self.btn_mode_practice.pack(side="left", padx=15)

        self.btn_mode_20 = tk.Button(
            mode_frame,
            text="🎮 20문제 Challenge",
            font=self.font_sub,
            bg="#27AE60",
            fg="white",
            relief="flat",
            padx=10,
            pady=3,
            command=lambda: self.start_quiz("game_20"),
        )
        self.btn_mode_20.pack(side="left", padx=5)

        self.btn_mode_wrong = tk.Button(
            mode_frame,
            text="✍️ 오답노트 퀴즈",
            font=self.font_sub,
            bg="#E67E22",
            fg="white",
            relief="flat",
            padx=10,
            pady=3,
            command=lambda: self.start_quiz("wrong_only"),
        )
        self.btn_mode_wrong.pack(side="right", padx=15)

        # 점수 및 정보 프레임
        info_frame = tk.Frame(self.root, bg="#F4F6F9")
        info_frame.pack(fill="x", padx=20, pady=2)

        self.lbl_score = tk.Label(
            info_frame,
            text="점수: 0 / 0",
            font=self.font_sub,
            fg="#555555",
            bg="#F4F6F9",
        )
        self.lbl_score.pack(side="left")

        self.lbl_wrong_count = tk.Label(
            info_frame,
            text=f"누적 오답: {len(self.wrong_words)}개",
            font=self.font_sub,
            fg="#C0392B",
            bg="#F4F6F9",
        )
        self.lbl_wrong_count.pack(side="right")

        # 단어 표시 카드 (높이를 높이지 않고 유연하게 배치)
        card_frame = tk.Frame(
            self.root,
            bg="#FFFFFF",
            highlightbackground="#D5D8DC",
            highlightthickness=1,
            pady=10,
        )
        card_frame.pack(fill="x", padx=20, pady=8)

        self.lbl_word = tk.Label(
            card_frame,
            text="단어를 불러오는 중...",
            font=self.font_word,
            fg="#16A085",
            bg="#FFFFFF",
            wraplength=700,
        )
        self.lbl_word.pack(expand=True, pady=10)

        # 피드백 메세지 레이블
        self.lbl_feedback = tk.Label(
            self.root, text="", font=self.font_feedback, bg="#F4F6F9"
        )
        self.lbl_feedback.pack(pady=2)

        # 보기 버튼 영역 (4지선다 - 패딩 최소화)
        self.option_buttons = []
        for i in range(4):
            btn = tk.Button(
                self.root,
                text="",
                font=self.font_btn,
                width=50,
                pady=5,
                state=tk.DISABLED,
                bg="#FFFFFF",
                fg="#2C3E50",
                activebackground="#EAECEE",
                relief="groove",
                bd=1,
            )
            btn.pack(pady=3)
            self.option_buttons.append(btn)

        # 하단 컨트롤 영역 ([다음 문제] 버튼)
        bottom_frame = tk.Frame(self.root, bg="#F4F6F9")
        bottom_frame.pack(fill="x", pady=10)

        self.btn_next = tk.Button(
            bottom_frame,
            text="다음 문제 ➔",
            font=self.font_btn,
            bg="#2980B9",
            fg="#FFFFFF",
            disabledforeground="#E0E0E0",
            relief="flat",
            padx=25,
            pady=6,
            state=tk.DISABLED,
            command=self.next_question,
        )
        self.btn_next.pack()

    def clean_text(self, text):
        if not text:
            return ""
        cleaned = re.sub(r"[★☐Πコロ]", "", text)
        return cleaned.strip()

    def load_pdf_automatically(self):
        if not os.path.exists(PDF_FILE_NAME):
            messagebox.showerror(
                "파일 오류",
                f"'{PDF_FILE_NAME}' 파일을 찾을 수 없습니다.\n"
                "파이썬 코드가 있는 동일한 폴더에 '단어장.pdf' 파일을 넣어주세요.",
            )
            self.lbl_word.config(text="파일 없음")
            return

        extracted_dict = {}
        try:
            with pdfplumber.open(PDF_FILE_NAME) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if len(row) >= 2:
                                word = self.clean_text(row[0])
                                meaning = self.clean_text(row[1])

                                if (
                                    word
                                    and meaning
                                    and word not in ["영어", "목차"]
                                    and meaning not in ["한글 뜻", "암기"]
                                ):
                                    extracted_dict[word] = meaning

                    if not tables:
                        text = page.extract_text()
                        if text:
                            lines = text.split("\n")
                            for line in lines:
                                if "|" in line:
                                    parts = line.split("|")
                                    if len(parts) >= 2:
                                        w = self.clean_text(parts[0])
                                        m = self.clean_text(parts[1])
                                        if (
                                            w
                                            and m
                                            and w not in ["영어", "목차"]
                                            and m not in ["한글 뜻", "암기"]
                                        ):
                                            extracted_dict[w] = m

            if not extracted_dict:
                messagebox.showwarning(
                    "경고", "PDF에서 단어를 추출하지 못했습니다."
                )
                self.lbl_word.config(text="단어 추출 실패")
                return

            self.word_dict = extracted_dict
            self.start_quiz("practice")

        except Exception as e:
            messagebox.showerror("오류", f"PDF를 읽는 도중 오류가 발생했습니다: {e}")

    def start_quiz(self, mode):
        self.quiz_mode = mode
        self.score = 0
        self.total_asked = 0

        if mode == "game_20":
            self.max_questions = 20
            self.words_list = list(self.word_dict.keys())
            messagebox.showinfo(
                "20문제 Challenge",
                "총 20문제가 출제됩니다!\n준비되셨으면 시작하세요.",
            )
        elif mode == "wrong_only":
            if not self.wrong_words:
                messagebox.showinfo(
                    "오답노트 비어있음",
                    "저장된 오답이 없습니다! 일반 모드로 시작합니다.",
                )
                self.start_quiz("practice")
                return
            self.max_questions = 0
            self.words_list = list(self.wrong_words.keys())
            messagebox.showinfo(
                "오답노트 모드",
                f"틀렸던 단어 {len(self.words_list)}개를 집중 학습합니다.",
            )
        else:
            self.max_questions = 0
            self.words_list = list(self.word_dict.keys())

        self.next_question()

    def next_question(self):
        if self.quiz_mode == "game_20" and self.total_asked >= self.max_questions:
            messagebox.showinfo(
                "게임 완료!",
                f"🎉 20문제를 모두 풀었습니다!\n\n최종 점수: {self.score} / 20 점",
            )
            self.start_quiz("practice")
            return

        if not self.words_list:
            return

        self.lbl_feedback.config(text="")
        self.btn_next.config(state=tk.DISABLED, bg="#BDC3C7", fg="#FFFFFF")

        self.current_word = random.choice(self.words_list)
        if self.quiz_mode == "wrong_only":
            self.correct_answer = self.wrong_words[self.current_word]
        else:
            self.correct_answer = self.word_dict[self.current_word]

        self.lbl_word.config(text=self.current_word)

        if self.quiz_mode == "game_20":
            self.lbl_score.config(
                text=f"진행: {self.total_asked + 1} / 20 문제  |  점수: {self.score}점"
            )
        else:
            self.lbl_score.config(
                text=f"점수: {self.score} / {self.total_asked}"
            )

        self.lbl_wrong_count.config(text=f"누적 오답: {len(self.wrong_words)}개")

        all_meanings = list(self.word_dict.values())
        wrong_options = [m for m in all_meanings if m != self.correct_answer]

        sample_count = min(3, len(wrong_options))
        options = random.sample(wrong_options, sample_count) + [
            self.correct_answer
        ]
        random.shuffle(options)

        for i, option in enumerate(options):
            self.option_buttons[i].config(
                text=f"{i+1}. {option}",
                state=tk.NORMAL,
                bg="#FFFFFF",
                fg="#2C3E50",
                command=lambda opt=option: self.check_answer(opt),
            )

    def check_answer(self, selected_option):
        self.total_asked += 1

        for btn in self.option_buttons:
            btn.config(state=tk.DISABLED)

        self.btn_next.config(state=tk.NORMAL, bg="#2980B9", fg="#FFFFFF")

        if selected_option == self.correct_answer:
            self.score += 1
            self.lbl_feedback.config(text="⭕ 정답입니다!", fg="#27AE60")

            if self.current_word in self.wrong_words:
                del self.wrong_words[self.current_word]
                self.save_wrong_words()
        else:
            self.lbl_feedback.config(
                text=f"❌ 오답입니다. (정답: {self.correct_answer})", fg="#C0392B"
            )

            self.wrong_words[self.current_word] = self.correct_answer
            self.save_wrong_words()

        if self.quiz_mode == "game_20":
            self.lbl_score.config(
                text=f"진행: {self.total_asked} / 20 문제  |  점수: {self.score}점"
            )
        else:
            self.lbl_score.config(
                text=f"점수: {self.score} / {self.total_asked}"
            )
        self.lbl_wrong_count.config(text=f"누적 오답: {len(self.wrong_words)}개")


if __name__ == "__main__":
    root = tk.Tk()
    app = VocabQuizApp(root)
    root.mainloop()