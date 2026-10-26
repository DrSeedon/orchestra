import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPORT = (
    "id,subject,priority,status,opened,assignee\n"
    "T-1,Printer jams,low,open,2024-05-01 09:00,dana\n"
    "T-2,VPN drops,urgent,open,2024-05-03 08:30,\n"
    "T-3,New laptop,normal,closed,2024-04-20 10:00,lee\n"
    "T-4,Mailbox full,high,open,2024-04-29 12:00,\n"
    "T-5,Badge reader,normal,pending,2024-04-25 09:00,dana\n"
    "T-6,Slow wifi,normal,open,2024-05-02 11:59,\n"
    "T-7,Broken chair,urgent,open,2024-05-01 09:00,lee\n"
)

NOW = "2024-05-03 12:00"


def run(*args):
    return subprocess.run([sys.executable, "-m", "ticketdesk.escalate", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_escalation_with_default_hours(tmp_path):
    tickets = write(tmp_path / "tickets.csv", EXPORT)
    out = tmp_path / "escalations.json"
    r = run(tickets, NOW, str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "escalations": [
            {"id": "T-4", "priority": "high", "age": 96, "level": "director"},
            {"id": "T-1", "priority": "low", "age": 51, "level": "manager"},
            {"id": "T-7", "priority": "urgent", "age": 51, "level": "manager"},
            {"id": "T-6", "priority": "normal", "age": 24, "level": "lead"},
        ],
        "counts": {"lead": 1, "manager": 2, "director": 1},
    }


def test_escalation_hours_from_settings(tmp_path):
    tickets = write(tmp_path / "tickets.csv", EXPORT)
    settings = write(tmp_path / "settings.json", json.dumps({"escalation_hours": 50}))
    out = tmp_path / "escalations.json"
    r = run(tickets, NOW, str(out), "--settings", settings)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "escalations": [
            {"id": "T-4", "priority": "high", "age": 96, "level": "lead"},
            {"id": "T-1", "priority": "low", "age": 51, "level": "lead"},
            {"id": "T-7", "priority": "urgent", "age": 51, "level": "lead"},
        ],
        "counts": {"lead": 3, "manager": 0, "director": 0},
    }


def test_no_escalations(tmp_path):
    tickets = write(tmp_path / "tickets.csv", EXPORT)
    settings = write(tmp_path / "settings.json", json.dumps({"escalation_hours": 200, "high_hours": 8}))
    out = tmp_path / "escalations.json"
    r = run(tickets, NOW, str(out), "--settings", settings)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {"escalations": [], "counts": {"lead": 0, "manager": 0, "director": 0}}


def test_ticket_opened_after_now_exits_3(tmp_path):
    tickets = write(tmp_path / "tickets.csv", EXPORT + "T-8,Coffee machine,low,open,2024-05-04 09:00,\n")
    out = tmp_path / "escalations.json"
    r = run(tickets, NOW, str(out))
    assert r.returncode == 3
    assert not out.exists()


def test_bad_now_or_settings_exit_2(tmp_path):
    tickets = write(tmp_path / "tickets.csv", EXPORT)
    out = tmp_path / "escalations.json"
    r = run(tickets, "2024-05-03", str(out))
    assert r.returncode == 2
    settings = write(tmp_path / "settings.json", json.dumps({"escalation_hours": 0}))
    r = run(tickets, NOW, str(out), "--settings", settings)
    assert r.returncode == 2
    settings = write(tmp_path / "settings.json", json.dumps({"escalation_hours": "12"}))
    r = run(tickets, NOW, str(out), "--settings", settings)
    assert r.returncode == 2
    assert not out.exists()
