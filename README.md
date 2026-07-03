# Gen AI Course

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp env.template .env   # then fill in your real GROQ_API_KEY
```

Get a key at https://console.groq.com/keys.

## Structure

```
week-X/day-Y/
  task.py       # task code for that day
  report.md     # short writeup: task, approach, output, learnings
common/
  groq_client.py  # shared helper for calling the Groq API
```

## Running a day's task

```bash
source .venv/bin/activate
python week-1/day-1/task.py
```
