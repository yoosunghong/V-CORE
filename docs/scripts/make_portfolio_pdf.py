# -*- coding: utf-8 -*-
"""Build a 1920x1080 landscape PDF deck combining PORTFOLIO.md sections 5.2 + 6.

All charts are rendered with matplotlib and embedded directly into 16:9 slide pages.
Run with anaconda python (has matplotlib + Malgun Gothic):
    C:/Users/PC/anaconda3/python.exe docs/scripts/make_portfolio_pdf.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, FancyArrowPatch

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

# ---- palette -----------------------------------------------------------------
NAVY = "#1e293b"
SLATE = "#334155"
OLL = "#4C72B0"   # Ollama
LLA = "#DD8452"   # llama.cpp
GREEN = "#2a9d8f"
RED = "#C44E52"
GRAY = "#94a3b8"
LIGHT = "#f1f5f9"
INK = "#0f172a"

W, H = 19.2, 10.8          # inches -> 1920x1080 @ 100 dpi
DPI = 100

PAGES = []


def new_slide(title, kicker=None, page_no=None):
    fig = plt.figure(figsize=(W, H), dpi=DPI)
    fig.patch.set_facecolor("white")
    # header band
    fig.add_artist(Rectangle((0, 0.905), 1, 0.095, color=NAVY,
                             transform=fig.transFigure, zorder=0))
    fig.add_artist(Rectangle((0, 0.900), 1, 0.006, color=LLA,
                             transform=fig.transFigure, zorder=1))
    fig.text(0.035, 0.952, title, color="white", fontsize=30,
             fontweight="bold", va="center")
    if kicker:
        fig.text(0.965, 0.952, kicker, color="#cbd5e1", fontsize=15,
                 va="center", ha="right")
    if page_no is not None:
        fig.text(0.972, 0.03, f"{page_no:02d}", color=GRAY, fontsize=14,
                 ha="right", va="center")
        fig.text(0.035, 0.03, "VCORE · LLM 추론 엔진 & 평가 체계", color=GRAY,
                 fontsize=12, va="center")
    return fig


def axbox(fig, l, b, w, h):
    ax = fig.add_axes([l, b, w, h])
    return ax


def style_bar_ax(ax, ymax=100, ylabel="%"):
    ax.set_ylim(0, ymax)
    ax.set_ylabel(ylabel, fontsize=12, color=SLATE)
    ax.grid(axis="y", color="#e2e8f0", linewidth=0.9)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#cbd5e1")
    ax.tick_params(colors=SLATE, labelsize=11)


def card(fig, l, b, w, h, fc="white", ec="#e2e8f0"):
    fig.add_artist(Rectangle((l, b), w, h, transform=fig.transFigure,
                             facecolor=fc, edgecolor=ec, linewidth=1.4,
                             zorder=0.5))


# =============================================================================
# SLIDE 1 — Title
# =============================================================================
fig = plt.figure(figsize=(W, H), dpi=DPI)
fig.patch.set_facecolor(NAVY)
fig.add_artist(Rectangle((0, 0), 1, 1, color=NAVY, transform=fig.transFigure))
fig.add_artist(Rectangle((0.035, 0.62), 0.14, 0.012, color=LLA,
                         transform=fig.transFigure))
fig.text(0.035, 0.72, "온프레미스 LLM 추론 엔진 선택 & 평가 체계", color="white",
         fontsize=46, fontweight="bold")
fig.text(0.035, 0.665, "llama.cpp vs Ollama 벤치마크 · 2×2 Ablation · QLoRA 프롬프트 증류",
         fontsize=22, color="#cbd5e1")

stats = [
    ("2,660회", "벤치마크 채점\n133케이스×12카테고리×4셀×R5"),
    ("+21.6pp", "검증 레이어 결함 적발·수정\nA2 54.3% → 75.9% (CI 비중첩)"),
    ("~11.7s→2.4s", "llama.cpp CUDA + reasoning-off\ndisambiguation 경로 latency"),
    ("49% → 96%", "프롬프트 증류(QLoRA SFT)\n4줄 최소 프롬프트 tool-routing"),
]
x0 = 0.035
bw = 0.218
for i, (big, small) in enumerate(stats):
    x = x0 + i * (bw + 0.012)
    fig.add_artist(Rectangle((x, 0.16), bw, 0.30, transform=fig.transFigure,
                             facecolor="#27364b", edgecolor="#3b4d66", linewidth=1.2))
    fig.text(x + 0.018, 0.40, big, color=LLA, fontsize=30, fontweight="bold")
    fig.text(x + 0.018, 0.215, small, color="#e2e8f0", fontsize=14, va="bottom")
fig.text(0.035, 0.075, "VCORE — AI Twin 플랫폼 · 포트폴리오 (PORTFOLIO.md §5.2 + §6)",
         color=GRAY, fontsize=15)
PAGES.append(fig)


# =============================================================================
# SLIDE 2 — 평가가 풀어야 했던 질문 + 2x2 Ablation 설계
# =============================================================================
fig = new_slide("평가 설계 — 모델 성능과 시스템 성능을 분리한다", "§6.1–6.4", 2)

# left: 4 questions
fig.text(0.035, 0.83, "추론 백엔드 교체가 던진 4개 질문", fontsize=20,
         fontweight="bold", color=INK)
qs = [
    "1.  어떤 Provider가 더 안정적으로 Tool Calling을 수행하는가?",
    "2.  JSON 구조화 출력은 얼마나 안정적인가?",
    "3.  Validation Layer는 실제로 도움이 되는가?",
    "4.  Fine-tuning이 정말 필요한 상황인가?",
]
for i, q in enumerate(qs):
    y = 0.75 - i * 0.075
    card(fig, 0.035, y - 0.025, 0.43, 0.058, fc=LIGHT)
    fig.text(0.05, y + 0.004, q, fontsize=16, color=SLATE, va="center")
fig.text(0.035, 0.40,
         "핵심 철학:  단순 latency 비교로는 답할 수 없다.\n"
         "\"모델 성능\"과 \"시스템(후처리 레이어) 성능\"을 분리해\n측정해야 엉뚱한 레이어를 고치지 않는다.",
         fontsize=17, color=INK, va="top", linespacing=1.6)
fig.text(0.035, 0.20, "규모  133 케이스 × 12 카테고리 × R5 × 4셀 = 2,660회 채점\n"
                      "         (재시도 포함 ~2,860 LLM 호출) · 전 항목 Wilson 95% CI",
         fontsize=14, color=SLATE, va="top", linespacing=1.7)

# right: 2x2 matrix
mx, my, mw, mh = 0.55, 0.30, 0.40, 0.50
fig.text(mx, my + mh + 0.03, "2×2 Ablation — 한 변수만 분리", fontsize=20,
         fontweight="bold", color=INK)
ax = fig.add_axes([mx, my, mw, mh]); ax.axis("off")
ax.set_xlim(0, 2); ax.set_ylim(0, 2)
cells = {(0, 1): ("A1", "Ollama · Layer OFF\n(intrinsic)", OLL),
         (1, 1): ("A2", "Ollama · Layer ON\n(production)", OLL),
         (0, 0): ("B1", "llama.cpp · Layer OFF\n(intrinsic)", LLA),
         (1, 0): ("B2", "llama.cpp · Layer ON\n(production)", LLA)}
for (cx, cy), (tag, desc, col) in cells.items():
    ax.add_patch(Rectangle((cx + 0.04, cy + 0.04), 0.92, 0.92,
                           facecolor=col, alpha=0.13, edgecolor=col, linewidth=2))
    ax.text(cx + 0.5, cy + 0.72, tag, ha="center", fontsize=26,
            fontweight="bold", color=col)
    ax.text(cx + 0.5, cy + 0.32, desc, ha="center", fontsize=12.5,
            color=SLATE, linespacing=1.4)
fig.text(mx, my - 0.045,
         "LlamaCppLlmGateway가 OllamaLlmGateway를 상속해 transport만 오버라이드\n"
         "→ 레이어 로직이 두 Provider에 바이트 단위로 동일 → 순수 비교 성립",
         fontsize=13, color=SLATE, va="top", linespacing=1.6)
PAGES.append(fig)


# =============================================================================
# SLIDE 3 — 헤드라인 결과: Task Success(+CI) & Latency
# =============================================================================
fig = new_slide("헤드라인 결과 — Task Success(Wilson CI) & Latency", "§6.5 · §5.2", 3)

# chart A: Task success with CI
ax = axbox(fig, 0.055, 0.16, 0.40, 0.62)
labels = ["A1\nOllama OFF", "A2\nOllama ON", "B1\nllama OFF", "B2\nllama ON"]
vals = [75.6, 75.9, 69.0, 74.0]
lo = [72.2, 72.6, 65.4, 70.5]
hi = [78.8, 79.0, 72.4, 77.2]
cols = [OLL, OLL, LLA, LLA]
err = [[v - l for v, l in zip(vals, lo)], [h - v for v, h in zip(vals, hi)]]
xb = range(len(vals))
ax.bar(xb, vals, color=cols, width=0.62, zorder=2,
       yerr=err, capsize=8, error_kw=dict(ecolor=INK, lw=1.6))
for i, v in enumerate(vals):
    ax.text(i, v + 4.5, f"{v:.1f}%", ha="center", fontsize=14, fontweight="bold", color=INK)
ax.set_xticks(list(xb)); ax.set_xticklabels(labels, fontsize=11)
style_bar_ax(ax, ymax=90, ylabel="Task Success (%)")
ax.set_title("Task Success = tool 정답 · args 정답  (n=665/셀)", fontsize=14,
             color=INK, pad=12)
fig.text(0.055, 0.085,
         "A1 = A2 CI 완전 중첩 → 레이어는 Ollama에 통계적 중립 ·  B1 vs B2 비중첩 → llama.cpp엔 진짜 +5.0pp",
         fontsize=12.5, color=SLATE)

# chart B: latency
ax2 = axbox(fig, 0.56, 0.16, 0.40, 0.62)
grp = ["Ollama (A1)", "llama.cpp (B1)"]
mean_v = [1420, 1182]
p95_v = [2175, 1965]
import numpy as np
xx = np.arange(len(grp)); bw2 = 0.34
ax2.bar(xx - bw2 / 2, mean_v, bw2, label="mean", color=[OLL, LLA], zorder=2)
ax2.bar(xx + bw2 / 2, p95_v, bw2, label="p95", color=[OLL, LLA], alpha=0.5, zorder=2)
for i, (m, p) in enumerate(zip(mean_v, p95_v)):
    ax2.text(i - bw2 / 2, m + 60, f"{m}", ha="center", fontsize=13, fontweight="bold", color=INK)
    ax2.text(i + bw2 / 2, p + 60, f"{p}", ha="center", fontsize=12, color=SLATE)
ax2.set_xticks(xx); ax2.set_xticklabels(grp, fontsize=13)
style_bar_ax(ax2, ymax=2700, ylabel="latency (ms)")
ax2.set_title("추론 지연 — reasoning-off, GPU 풀 오프로드(-ngl 99)", fontsize=14, color=INK, pad=12)
ax2.legend(loc="upper right", frameon=False, fontsize=12)
fig.text(0.56, 0.085,
         "둘 다 reasoning-off(thinking 차이 아님) → ~240ms 격차는 서버 오버헤드 ·  llama.cpp mean 17%↓",
         fontsize=12.5, color=SLATE)
PAGES.append(fig)


# =============================================================================
# SLIDE 4 — 트레이드오프(카테고리) & 검증 레이어 결함 수정
# =============================================================================
fig = new_slide("Provider 트레이드오프 & 검증 레이어 결함 적발·수정", "§7.1 · §5.2", 4)

# chart C: per-category Ollama vs llama.cpp
ax = axbox(fig, 0.055, 0.17, 0.40, 0.60)
cats = ["kpi_\nacceptance", "disambig.", "negative_\ncontrol", "ambiguous", "missing_\nparam"]
oll = [22, 60, 81.4, 76, 51.7]
lla = [60, 80, 62.9, 54, 15]
xx = np.arange(len(cats)); bw3 = 0.38
ax.bar(xx - bw3 / 2, oll, bw3, label="Ollama", color=OLL, zorder=2)
ax.bar(xx + bw3 / 2, lla, bw3, label="llama.cpp", color=LLA, zorder=2)
for i, (o, l) in enumerate(zip(oll, lla)):
    ax.text(i - bw3 / 2, o + 2, f"{o:.0f}", ha="center", fontsize=10.5, color=INK)
    ax.text(i + bw3 / 2, l + 2, f"{l:.0f}", ha="center", fontsize=10.5, color=INK)
ax.set_xticks(xx); ax.set_xticklabels(cats, fontsize=10.5)
style_bar_ax(ax, ymax=100, ylabel="Task Success (%)")
ax.legend(loc="upper right", frameon=False, fontsize=12)
ax.set_title("카테고리별 강·약점 — 명확한 트레이드오프", fontsize=14, color=INK, pad=12)
fig.text(0.055, 0.09,
         "llama.cpp 우위: 추출형(kpi·disambig) ↔ Ollama 우위: 거절형(negative·ambiguous·missing)\n"
         "원인: llama.cpp 경로의 tool_choice:\"auto\" 편향 + 채팅 템플릿/샘플링 기본값 차이 (코드 레벨 규명)",
         fontsize=12.5, color=SLATE, va="top", linespacing=1.6)

# chart D: validation layer fix (Phase2A -> Phase2B) on A2
ax2 = axbox(fig, 0.56, 0.17, 0.40, 0.60)
fcats = ["negative_\ncontrol", "ambiguous", "missing_\nparam", "invalid_\nparam", "A2 전체"]
before = [2.9, 0.0, 0.0, 0.0, 54.3]
after = [81.4, 76.0, 51.7, 56.0, 75.9]
xx = np.arange(len(fcats)); bw4 = 0.38
ax2.bar(xx - bw4 / 2, before, bw4, label="수정 전 (broken)", color=RED, alpha=0.85, zorder=2)
ax2.bar(xx + bw4 / 2, after, bw4, label="수정 후 (fixed)", color=GREEN, zorder=2)
for i, (b, a) in enumerate(zip(before, after)):
    ax2.text(i - bw4 / 2, b + 2, f"{b:.0f}", ha="center", fontsize=10.5, color=INK)
    ax2.text(i + bw4 / 2, a + 2, f"{a:.0f}", ha="center", fontsize=10.5, color=INK)
ax2.set_xticks(xx); ax2.set_xticklabels(fcats, fontsize=10.5)
style_bar_ax(ax2, ymax=100, ylabel="Task Success (%)")
ax2.legend(loc="upper left", frameon=False, fontsize=12)
ax2.set_title("운영 레이어가 최고 모델을 -21pp 악화 → 수정", fontsize=14, color=INK, pad=12)
fig.text(0.56, 0.09,
         "Repair-retry가 거부(decline)를 강제로 tool 환각으로 변환 + Validator 범위검사 부재\n"
         "→ decline 종단 인정 + range-check 추가 ·  A2 54.3% → 75.9% (Wilson CI 비중첩, +21.6pp)",
         fontsize=12.5, color=SLATE, va="top", linespacing=1.6)
PAGES.append(fig)


# =============================================================================
# SLIDE 5 — Fine-tuning: 프롬프트 증류 (QLoRA SFT)
# =============================================================================
fig = new_slide("Fine-tuning — \"프롬프트 증류\" (QLoRA SFT)", "§5.2 · §6.8", 5)

# chart E: 3-condition
ax = axbox(fig, 0.055, 0.18, 0.37, 0.58)
conds = ["Base+Minimal\n(4줄)", "Base+Full\n(긴 운영 프롬프트)", "SFT+Minimal\n(4줄)"]
cv = [12, 49, 96]
cc = [GRAY, OLL, GREEN]
ax.bar(range(3), cv, color=cc, width=0.6, zorder=2)
for i, v in enumerate(cv):
    ax.text(i, v + 2.5, f"{v}%", ha="center", fontsize=16, fontweight="bold", color=INK)
ax.set_xticks(range(3)); ax.set_xticklabels(conds, fontsize=11.5)
style_bar_ax(ax, ymax=110, ylabel="Tool-routing 성공률 (%)")
ax.set_title("3-조건 held-out 평가 (n=100, 동일 서버)", fontsize=14, color=INK, pad=12)

# chart F: per-category SFT improvement
ax2 = axbox(fig, 0.48, 0.18, 0.30, 0.58)
scats = ["disambig.", "kpi_\nacceptance", "param 거부\n(invalid/missing)"]
sb = [30, 50, 0]
sa = [95, 100, 100]
xx = np.arange(len(scats)); bw5 = 0.38
ax2.bar(xx - bw5 / 2, sb, bw5, label="Base", color=GRAY, zorder=2)
ax2.bar(xx + bw5 / 2, sa, bw5, label="SFT", color=GREEN, zorder=2)
for i, (b, a) in enumerate(zip(sb, sa)):
    ax2.text(i - bw5 / 2, b + 2, f"{b}", ha="center", fontsize=11, color=INK)
    ax2.text(i + bw5 / 2, a + 2, f"{a}", ha="center", fontsize=11, color=INK)
ax2.set_xticks(xx); ax2.set_xticklabels(scats, fontsize=10.5)
style_bar_ax(ax2, ymax=115, ylabel="%")
ax2.legend(loc="upper center", frameon=False, fontsize=11, ncol=2)
ax2.set_title("핵심 카테고리 (4줄 프롬프트)", fontsize=14, color=INK, pad=12)

# right text panel
tx = 0.815
card(fig, tx - 0.01, 0.17, 0.195, 0.59, fc=LIGHT)
fig.text(tx, 0.73, "왜 증류인가", fontsize=17, fontweight="bold", color=INK)
fig.text(tx, 0.70,
         "역량이 가중치가 아니라\n긴 프롬프트 문자열에 있었다\n→ 유지보수·확장·추론비용 부채",
         fontsize=12.5, color=SLATE, va="top", linespacing=1.55)
fig.text(tx, 0.575, "데이터 / 학습", fontsize=17, fontweight="bold", color=INK)
fig.text(tx, 0.545,
         "450행(300/50/100), 9개 실제\ntool에 grounding, ToolRouter로\n450/450 검증 · 라벨 노이즈 0\n"
         "QLoRA r16/α32, NF4, 0.58%\nRTX 4060 Ti 8GB ~7분\neval-loss 0.0315 → 0.0029",
         fontsize=12.5, color=SLATE, va="top", linespacing=1.55)
fig.text(tx, 0.305, "배포", fontsize=17, fontweight="bold", color=INK)
fig.text(tx, 0.275,
         "merge→GGUF(q4_k_m 1.27GB)\n→ 베이스와 동일 런타임/플래그",
         fontsize=12.5, color=SLATE, va="top", linespacing=1.55)

fig.text(0.055, 0.10,
         "SFT+Minimal(96%) = Base+Full(49%)의 약 2배, Base+Minimal(12%)의 8배 — 라우팅이 프롬프트가 아닌 가중치에 ·  "
         "프롬프트 의존도: 베이스 49→12(-37pp) 붕괴, SFT는 96 유지",
         fontsize=12.5, color=SLATE, va="top")
PAGES.append(fig)


# =============================================================================
# SLIDE 6 — 사전 등록된 의사결정 규칙 & 결론
# =============================================================================
fig = new_slide("사전 등록된 의사결정 규칙 & 결론", "§6.7 · §8", 6)

fig.text(0.035, 0.83, "Fine-tuning 게이트 (실행 전 동결)", fontsize=20,
         fontweight="bold", color=INK)
rules = [
    ("레이어 효과 미미 (A2 = A1)", "베이스 충분 → fine-tune 생략, 프롬프트/스키마에 투자", GREEN),
    ("lift 대부분이 fallback", "제품이 결정론적 코드에 업혀있음 → 정직히 문서화", GRAY),
    ("1차 스키마↓ & fallback이 하드 카테고리 못 덮음", "fine-tune 정당화 → Phase 3", OLL),
]
for i, (cond, act, col) in enumerate(rules):
    y = 0.74 - i * 0.085
    fig.add_artist(Rectangle((0.035, y - 0.03), 0.006, 0.062, color=col,
                             transform=fig.transFigure))
    fig.text(0.05, y + 0.012, cond, fontsize=15, fontweight="bold", color=INK)
    fig.text(0.05, y - 0.016, act, fontsize=13.5, color=SLATE)

fig.text(0.035, 0.44,
         "실제 결과:  첫 분기 발동(A1 = A2).  수정 후 JSON parse 100% / 1차 스키마 94% 도달\n"
         "→ \"포맷 병목\" 가설 사망 → 정확도 목적의 fine-tuning 근거 무효화.",
         fontsize=15, color=INK, va="top", linespacing=1.6)
fig.text(0.035, 0.31,
         "남은 의미론적 잔여 2개를 가장 싼 레버로 해소:\n"
         "  • kpi_acceptance — 평문 2줄 추가  →  22% → 94%\n"
         "  • disambiguation — 서빙 플래그(reasoning-off)  →  63% → 91.7%",
         fontsize=15, color=SLATE, va="top", linespacing=1.7)

# right: conclusion card
cx = 0.55
card(fig, cx, 0.13, 0.41, 0.66, fc=NAVY, ec=NAVY)
fig.text(cx + 0.025, 0.74, "결론 — 엔지니어링 판단의 방어 가능성", fontsize=19,
         fontweight="bold", color="white")
concl = [
    ("-21pp 적발", "운영 레이어가 최고 모델을 악화시킴을\n2,660회 + Wilson CI로 적발·수정 (54.3→75.9%)"),
    ("무료 레버 우선", "\"약하니 fine-tune\" 본능을 프롬프트 2줄\n(KPI 22→94%)·서빙 플래그(63→91.7%)로 무효화"),
    ("증류로 재정의", "SFT 목표를 정확도가 아닌 프롬프트 의존 제거로\n재정의 → 49→96%, 의존 -37pp 제거"),
]
for i, (h, b) in enumerate(concl):
    y = 0.65 - i * 0.155
    fig.text(cx + 0.025, y, h, fontsize=16, fontweight="bold", color=LLA)
    fig.text(cx + 0.025, y - 0.055, b, fontsize=13, color="#e2e8f0", va="top", linespacing=1.45)
fig.text(cx + 0.025, 0.155,
         "측정이 본능을 이긴다 · 가장 싼 레버부터 · 모델≠시스템",
         fontsize=13.5, color="#cbd5e1", style="italic")
PAGES.append(fig)


# ---- write PDF ---------------------------------------------------------------
import os
out = os.path.join(os.path.dirname(__file__), "..", "PORTFOLIO_LLM_eval.pdf")
out = os.path.abspath(out)
with PdfPages(out) as pdf:
    for i, f in enumerate(PAGES):
        pdf.savefig(f, facecolor=f.get_facecolor())
        if os.environ.get("PREVIEW"):
            f.savefig(os.path.join(os.path.dirname(__file__), f"_preview_{i+1}.png"),
                      dpi=60, facecolor=f.get_facecolor())
        plt.close(f)
print("WROTE", out, "pages:", len(PAGES))
