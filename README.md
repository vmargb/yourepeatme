# About

An experimental app for testing worked-example and fading theories. Each review starts with a worked example and explanation, followed by an attempt to reproduce the solution from memory. You can then compare your attempt with the original and record how well you did. Each example maybe also optionally use adaptive-fading to gradually retrieve more steps.

Problems are scheduled for review based on your performance, using a simple interval. Sessions use a time budget, and each problem appears at most once per session. Missed sessions do not force you to cram overdue problems into your next session. Everything is stored locally in SQLite, with no account required.

## Running locally

Requires Python 3.12 or later.

```bash
python -m venv .venv
pip install -r requirements.txt
streamlit run app.py
```

