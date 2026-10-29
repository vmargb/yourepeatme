import json
from datetime import datetime

import streamlit as st

import db
import scheduler

st.set_page_config(page_title="yourepeatme", layout="wide")
ss = st.session_state

LABELS = {
    "independent": "Independent: little or no difficulty",
    "partial": "Partial: missed or misimplemented important details",
    "needed_help": "Needed help: required a hint or significant assistance",
    "could_not_reproduce": "Could not reproduce: no workable reconstruction",
}
LANGS = {"c++": "cpp", "c#": "csharp", "js": "javascript", "clojure": "clojure"}


@st.cache_resource
def get_conn():
    return db.connect()


def lang(name):
    n = name.strip().lower()
    return LANGS.get(n, n) or None


def fmt_secs(s):
    return f"{s // 60}m {s % 60}s"


def flash(msg):
    ss["flash"] = msg


def show_flash():
    if ss.get("flash"):
        st.success(ss.pop("flash"))


def end_session(c, sid):
    db.finish_session(c, sid)
    ss["summary_id"] = sid
    st.rerun()


def show_summary(c, sid):
    s = db.session_summary(c, sid)
    st.subheader("Session summary")
    a, b, d = st.columns(3)
    a.metric("Completed", s["completed"])
    b.metric("Time spent", fmt_secs(s["seconds"]))
    d.metric("Remaining in queue", s["remaining"])


def start_form(c):
    budget = st.number_input("Time budget (minutes)", 5, 240, 25, 5)
    queue = scheduler.build_queue(db.list_problems(c), budget, db.now())
    if not queue:
        st.info("Nothing due. Add problems in the Library or come back later.")
        return
    st.write(f"{len(queue)} problem(s) queued, about {sum(p['estimated_minutes'] for p in queue)} min.")
    if st.button("Start session", type="primary"):
        db.create_session(c, budget, [p["id"] for p in queue])
        ss.pop("summary_id", None)
        st.rerun()


def study_view(c):
    sess = db.active_session(c)
    if not sess:
        if ss.get("summary_id"):
            show_summary(c, ss["summary_id"])
            st.divider()
        start_form(c)
        return

    sid = sess["id"]
    items = db.session_items(c, sid)
    pending = [i for i in items if i["status"] == "pending"]
    if not pending:
        end_session(c, sid)
    done = len(items) - len(pending)
    st.progress(done / len(items), text=f"{done} of {len(items)} done")
    if st.button("Finish early"):
        end_session(c, sid)

    cur = pending[0]
    pid, lg = cur["problem_id"], lang(cur["language"])
    if ss.get("cur") != (sid, pid):
        ss.update(cur=(sid, pid), stage="study", attempt="")
        db.start_item(c, sid, pid)

    st.header(cur["title"])

    if ss.stage == "study":
        st.code(cur["reference_code"], language=lg)
        if cur["explanation"]:
            st.markdown(cur["explanation"])
        if st.button("Hide example and reconstruct", type="primary"):
            ss.stage = "reconstruct"
            st.rerun()

    elif ss.stage == "reconstruct":
        st.caption("Write the solution from memory.")
        text = st.text_area("Your solution", ss.attempt, height=400, key=f"box_{pid}")
        a, b = st.columns(2)
        if a.button("Reveal and compare", type="primary"):
            ss.attempt, ss.stage = text, "compare"
            st.rerun()
        if b.button("Back to example"):
            ss.attempt, ss.stage = text, "study"
            st.rerun()

    else:
        left, right = st.columns(2)
        with left:
            st.markdown("**Reference**")
            st.code(cur["reference_code"], language=lg)
            if cur["explanation"]:
                st.markdown(cur["explanation"])
        with right:
            st.markdown("**Your attempt**")
            st.code(ss.attempt or "# (empty)", language=lg)
        outcome = st.radio("How did it go?", scheduler.OUTCOMES, index=None,
                           format_func=LABELS.get, key=f"out_{pid}")
        notes = st.text_input("Notes (optional)", key=f"note_{pid}")
        a, b = st.columns(2)
        if a.button("Complete review", type="primary", disabled=outcome is None):
            db.complete_review(c, sid, pid, outcome, ss.attempt, notes)
            st.rerun()
        if b.button("Back to reconstruct"):
            ss.stage = "reconstruct"
            st.rerun()


def library_view(c):
    show_flash()
    t_list, t_edit, t_io = st.tabs(["Problems", "Add / edit", "Import / export"])

    with t_list:
        q = st.text_input("Search (title, tags, language)").lower()
        f1, f2 = st.columns(2)
        imps = f1.multiselect("Importance", ["low", "normal", "high"])
        archived = f2.checkbox("Show archived")
        now = db.now()
        rows = []
        for p in db.list_problems(c, archived):
            if q and q not in f"{p['title']} {p['tags']} {p['language']}".lower():
                continue
            if imps and p["importance"] not in imps:
                continue
            if not p["active"]:
                nxt = "Archived"
            elif p["stage"] < 0:
                nxt = "New"
            elif scheduler.is_due(p, now):
                nxt = "Due"
            else:
                nxt = p["next_review_at"][:10]
            rows.append({"Title": p["title"], "Language": p["language"], "Tags": p["tags"],
                         "Importance": p["importance"], "Next review": nxt,
                         "Last reviewed": (p["last_reviewed_at"] or "")[:10]})
        st.dataframe(rows, hide_index=True)

    with t_edit:
        probs = db.list_problems(c, True)
        names = {p["id"]: p["title"] + ("" if p["active"] else " (archived)") for p in probs}
        sel = st.selectbox("Problem", [None, *names], format_func=lambda i: "New problem" if i is None else names[i])
        p = next((x for x in probs if x["id"] == sel), {})
        imp = ["low", "normal", "high"]
        with st.form(f"form_{sel}"):
            title = st.text_input("Title", p.get("title", ""))
            language = st.text_input("Language", p.get("language", "Python"))
            code = st.text_area("Reference code", p.get("reference_code", ""), height=300)
            expl = st.text_area("Explanation", p.get("explanation", ""), height=150)
            tags = st.text_input("Tags (comma-separated)", p.get("tags", ""))
            c1, c2 = st.columns(2)
            importance = c1.selectbox("Importance", imp, imp.index(p.get("importance", "normal")))
            mins = c2.number_input("Estimated minutes", 1, 120, p.get("estimated_minutes", 5))
            if st.form_submit_button("Save", type="primary"):
                if not title.strip() or not code.strip():
                    st.error("Title and reference code are required.")
                else:
                    db.save_problem(c, dict(title=title.strip(), language=language.strip() or "Python",
                                            reference_code=code, explanation=expl, tags=tags.strip(),
                                            importance=importance, estimated_minutes=int(mins)), sel)
                    flash("Saved.")
                    st.rerun()
        if sel and st.button("Restore" if not p["active"] else "Archive"):
            db.set_active(c, sel, not p["active"])
            flash("Updated.")
            st.rerun()

    with t_io:
        st.download_button("Export backup (JSON)", json.dumps(db.export_data(c), indent=2),
                           f"yourepeatme-backup-{datetime.now():%Y%m%d}.json", "application/json")
        up = st.file_uploader("Restore from backup", type="json")
        ok = st.checkbox("I understand this replaces all current data")
        if st.button("Restore", disabled=not (up and ok)):
            try:
                db.import_data(c, json.load(up))
                ss.pop("cur", None)
                flash("Backup restored.")
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")


st.sidebar.title("yourepeatme")
view = st.sidebar.radio("View", ["Study", "Library"], label_visibility="collapsed")
(study_view if view == "Study" else library_view)(get_conn())
