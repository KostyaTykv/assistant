from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

import pandas as pd
from flask import Flask, jsonify, render_template, request, abort


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
SHEET_NAME = "data"


# ====== Excel columns (must match your template) ======
COL_ROWTYPE = "RowType"
COL_SURVEY_TITLE = "SurveyTitle"
COL_SURVEY_DESC = "SurveyDescription"
COL_START_QID = "StartQuestionId"
COL_FINAL_TITLE = "FinalTitle"
COL_FINAL_TEXT = "FinalText"

COL_QID = "Id"
COL_Q_TITLE = "QuestionTitle"
COL_Q_TEXT = "QuestionText"
COL_Q_LONG = "LongText"
COL_HINTS = "Hints"
COL_TYPE = "Type"

COL_NEXTID = "NextId"

# Answer1..Answer10
# NextIfAnswer1..NextIfAnswer10


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _slugify(name: str) -> str:
    # stable id from filename: letters/numbers/_-
    base = os.path.splitext(os.path.basename(name))[0]
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^A-Za-z0-9_-]+", "", base)
    return base or "survey"


@dataclass(frozen=True)
class Option:
    idx: int
    text: str
    next_qid: Optional[str] = None


@dataclass(frozen=True)
class Question:
    qid: str
    qtype: str  # single/multi/text/number
    title: str
    text: str
    long_text: str
    hints: str
    options: List[Option]
    next_id: Optional[str]  # for multi/text/number


@dataclass(frozen=True)
class Survey:
    key: str              # derived from file name
    file_name: str        # displayed / debug
    title: str
    description: str
    start_qid: str
    final_title: str
    final_text: str
    questions: Dict[str, Question]


def load_survey_from_excel(filepath: str) -> Survey:
    df = pd.read_excel(filepath, sheet_name=SHEET_NAME)
    df.columns = [c.strip() for c in df.columns]

    required = {
        COL_ROWTYPE,
        COL_SURVEY_TITLE, COL_SURVEY_DESC, COL_START_QID, COL_FINAL_TITLE, COL_FINAL_TEXT,
        COL_QID, COL_Q_TITLE, COL_Q_TEXT, COL_Q_LONG, COL_HINTS, COL_TYPE,
        COL_NEXTID
    }
    # answers + nextif columns are optional but expected; we won't hard-fail if missing, but prefer to have them
    missing_core = sorted(required - set(df.columns))
    if missing_core:
        raise ValueError(f"{os.path.basename(filepath)}: missing columns in sheet '{SHEET_NAME}': {missing_core}")

    key = _slugify(filepath)

    # Meta row
    meta_rows = df[df[COL_ROWTYPE].astype(str).str.lower().str.strip() == "survey"]
    if meta_rows.empty:
        raise ValueError(f"{os.path.basename(filepath)}: no RowType=survey row found")
    m = meta_rows.iloc[0]

    title = _safe_str(m.get(COL_SURVEY_TITLE)) or key
    description = _safe_str(m.get(COL_SURVEY_DESC))
    start_qid = _safe_str(m.get(COL_START_QID))
    final_title = _safe_str(m.get(COL_FINAL_TITLE)) or "Готово"
    final_text = _safe_str(m.get(COL_FINAL_TEXT)) or "Спасибо! Ваши ответы:\n{answers}"

    # Questions
    qrows = df[df[COL_ROWTYPE].astype(str).str.lower().str.strip() == "question"].copy()
    questions: Dict[str, Question] = {}

    for _, r in qrows.iterrows():
        qid = _safe_str(r.get(COL_QID))
        if not qid:
            continue

        qtype = _norm(_safe_str(r.get(COL_TYPE)))
        if qtype not in {"single", "multi", "text", "number"}:
            raise ValueError(f"{os.path.basename(filepath)}: question {qid}: invalid Type='{qtype}'")

        opts: List[Option] = []
        next_id = _safe_str(r.get(COL_NEXTID)) or None

        # gather options
        for i in range(1, 11):
            a_col = f"Answer{i}"
            n_col = f"NextIfAnswer{i}"
            a = _safe_str(r.get(a_col))
            n = _safe_str(r.get(n_col))
            if a:
                opts.append(Option(idx=i, text=a, next_qid=n or None))

        # Validate by type
        if qtype in {"single", "multi"}:
            if not opts:
                raise ValueError(f"{os.path.basename(filepath)}: question {qid}: no answers provided (Answer1..Answer10)")
        if qtype == "single":
            # next per answer can be empty (means finish) — ok
            pass
        else:
            # multi/text/number use NextId (can be empty -> finish)
            # options for text/number should be empty; allow but ignore if accidentally filled
            pass

        questions[qid] = Question(
            qid=qid,
            qtype=qtype,
            title=_safe_str(r.get(COL_Q_TITLE)),
            text=_safe_str(r.get(COL_Q_TEXT)),
            long_text=_safe_str(r.get(COL_Q_LONG)),
            hints=_safe_str(r.get(COL_HINTS)),
            options=opts,
            next_id=next_id,
        )

    if not questions:
        raise ValueError(f"{os.path.basename(filepath)}: no questions found (RowType=question)")

    # start_qid fallback
    if not start_qid or start_qid not in questions:
        start_qid = next(iter(questions.keys()))

    return Survey(
        key=key,
        file_name=os.path.basename(filepath),
        title=title,
        description=description,
        start_qid=start_qid,
        final_title=final_title,
        final_text=final_text,
        questions=questions,
    )


def load_all_surveys(data_dir: str) -> Dict[str, Survey]:
    surveys: Dict[str, Survey] = {}
    if not os.path.isdir(data_dir):
        return surveys

    for name in os.listdir(data_dir):
        if not name.lower().endswith(".xlsx"):
            continue
        if name.startswith("~$"):  # excel temp
            continue

        path = os.path.join(data_dir, name)
        try:
            s = load_survey_from_excel(path)
            # ensure unique key
            key = s.key
            if key in surveys:
                key = f"{key}_{len(surveys)+1}"
                s = Survey(
                    key=key,
                    file_name=s.file_name,
                    title=s.title,
                    description=s.description,
                    start_qid=s.start_qid,
                    final_title=s.final_title,
                    final_text=s.final_text,
                    questions=s.questions,
                )
            surveys[s.key] = s
        except Exception as e:
            # Fail fast is usually better, but to keep UI alive:
            # you can comment next line if you want strict startup
            raise

    return surveys


app = Flask(__name__)
SURVEYS = load_all_surveys(DATA_DIR)


def get_survey_or_404(key: str) -> Survey:
    s = SURVEYS.get(key)
    if not s:
        abort(404)
    return s


@app.get("/")
def index():
    # cards from all files
    items = sorted(SURVEYS.values(), key=lambda x: x.title.lower())
    return render_template("index.html", surveys=items)


@app.get("/s/<survey_key>")
def survey_page(survey_key: str):
    s = get_survey_or_404(survey_key)
    return render_template("survey.html", survey=s)


@app.get("/api/s/<survey_key>/q/<qid>")
def api_get_question(survey_key: str, qid: str):
    s = get_survey_or_404(survey_key)
    q = s.questions.get(qid)
    if not q:
        return jsonify({"ok": False, "error": "question_not_found"}), 404

    return jsonify({
        "ok": True,
        "survey_key": s.key,
        "qid": q.qid,
        "type": q.qtype,
        "title": q.title,
        "text": q.text,
        "long_text": q.long_text,
        "hints": q.hints,
        "options": [{"idx": opt.idx, "text": opt.text} for opt in q.options],
    })


def _answers_to_text(answers: List[dict]) -> str:
    # pretty result
    lines = []
    for a in answers:
        qtitle = a.get("question_title") or a.get("qid") or "Вопрос"
        aval = a.get("value_text") or ""
        lines.append(f"{qtitle}: {aval}")
    return "\n".join(lines)


@app.post("/api/s/<survey_key>/answer")
def api_answer(survey_key: str):
    s = get_survey_or_404(survey_key)
    data = request.get_json(silent=True) or {}

    qid = _safe_str(data.get("qid"))
    answers = data.get("answers") or []

    if not qid:
        return jsonify({"ok": False, "error": "bad_request"}), 400

    q = s.questions.get(qid)
    if not q:
        return jsonify({"ok": False, "error": "question_not_found"}), 404

    qtype = q.qtype

    next_qid: Optional[str] = None
    value_text = ""

    if qtype == "single":
        option_idx = data.get("option_idx")
        if not isinstance(option_idx, int):
            return jsonify({"ok": False, "error": "bad_request"}), 400

        opt = next((o for o in q.options if o.idx == option_idx), None)
        if not opt:
            return jsonify({"ok": False, "error": "invalid_option"}), 400

        value_text = opt.text
        next_qid = opt.next_qid  # may be None -> finish

    elif qtype == "multi":
        option_idxs = data.get("option_idxs")
        if not isinstance(option_idxs, list) or not all(isinstance(x, int) for x in option_idxs):
            return jsonify({"ok": False, "error": "bad_request"}), 400
        option_idxs = sorted(set(option_idxs))
        chosen = [o.text for o in q.options if o.idx in option_idxs]
        if not chosen:
            return jsonify({"ok": False, "error": "no_selection"}), 400

        value_text = ", ".join(chosen)
        next_qid = q.next_id  # one next for multi

    elif qtype == "text":
        v = _safe_str(data.get("value"))
        if not v:
            return jsonify({"ok": False, "error": "empty_value"}), 400
        value_text = v
        next_qid = q.next_id

    elif qtype == "number":
        v = data.get("value")
        # allow int/float as number
        if not isinstance(v, (int, float)):
            # if sent as string - try parse
            vs = _safe_str(v)
            try:
                v = float(vs)
            except Exception:
                return jsonify({"ok": False, "error": "bad_number"}), 400
        value_text = str(v)
        next_qid = q.next_id

    else:
        return jsonify({"ok": False, "error": "unsupported_type"}), 500

    # append answer
    answers = list(answers)
    answers.append({
        "qid": qid,
        "question_title": q.title,
        "question_text": q.text,
        "type": qtype,
        "value_text": value_text,
    })

    # finish?
    if not next_qid:
        answers_text = _answers_to_text(answers)
        final_text = (s.final_text or "").replace("{answers}", answers_text)
        return jsonify({
            "ok": True,
            "finished": True,
            "final_title": s.final_title,
            "final_text": final_text,
            "answers": answers,
        })

    if next_qid not in s.questions:
        return jsonify({"ok": False, "error": "next_question_missing", "next_qid": next_qid}), 500

    return jsonify({
        "ok": True,
        "finished": False,
        "next_qid": next_qid,
        "answers": answers,
    })


@app.get("/result")
def result_page():
    return render_template("result.html")


if __name__ == "__main__":
    # debug=True удобно в разработке (автоперезапуск)
    app.run(host="0.0.0.0", port=8000, debug=True)
