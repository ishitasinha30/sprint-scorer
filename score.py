#!/usr/bin/env python3
"""
Sprint Scorer — tool-agnostic sprint prioritization engine.

Works with any task tracking tool (ClickUp, Jira, Linear, Notion, spreadsheet).
Export your backlog to CSV using template.csv, run this script, get a ranked sprint plan.

Usage:
  python score.py tickets.csv
  python score.py tickets.csv --sprint "Sprint 27" --output results.md
  python score.py tickets.csv --config my_config.json

CSV columns (see template.csv for full reference):
  Required:  id, title, category
  Scored:    client_priority, ticket_type, severity, occurrence, chargeable,
             duration, teams_involved, dependencies, market
  Inferred:  if teams_involved is blank and assignee_ids is present,
             teams are resolved via config.json team_map

ClickUp users: pass --assignees to resolve teams from raw assignee IDs.
"""

import csv
import json
import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── defaults if config.json not found ────────────────────────────────────────

DEFAULT_CONFIG = {
    "bandwidth": {"backend": 170, "frontend": 185, "ai": 115, "qa": 175},
    "team_map": {},
    "weights": {
        "client_ticket":   {"client_priority": 0.20, "ticket_type": 0.05, "severity": 0.15, "occurrence": 0.15, "chargeable": 0.05, "effort": 0.35, "market": 0.05},
        "internal_ticket": {"ticket_owner": 0.20, "ticket_type": 0.05, "severity": 0.15, "occurrence": 0.15, "effort": 0.35, "chargeable": 0.05, "market": 0.05},
        "client_ask":      {"due_date_urgency": 0.30, "client_priority": 0.20, "ticket_status": 0.35, "effort": 0.15},
    },
    "effort_weights": {"duration": 0.40, "teams": 0.30, "dependencies": 0.30},
    "allocation": {"client_ticket": 0.50, "internal_ticket": 0.30, "client_ask": 0.10, "buffer": 0.10},
    "scores": {
        "client_priority":  {"high": 5, "medium": 3, "low": 1},
        "ticket_type":      {"regression": 5, "bug": 4, "enhancement": 3, "feature": 1},
        "severity":         {"critical": 5, "major": 4, "minor": 3, "low": 1},
        "occurrence":       {"frequent": 5, "multiple": 3, "once": 1},
        "chargeable":       {"chargeable": 5, "strategic": 3, "free": 1},
        "market":           {"usa": 5, "uk": 3, "europe": 1},
        "ticket_owner":     {"bd": 5, "tech": 4, "qa": 4, "marketing": 3, "design": 1},
        "due_date_urgency": {"critical": 5, "moderate": 3, "low": 1},
        "ticket_status":    {"ready": 5, "customer_review": 2, "to_do_design": 1},
        "duration":         {"<1day": 5, "1-3days": 3, ">3days": 1},
        "teams_involved":   {"1": 5, "2": 3, "3+": 1},
        "dependencies":     {"none": 5, "relates": 3, "blocks": 1},
    },
}

# ── keyword heuristics for inferring missing fields from ticket titles ────────

_BUG = ["fix","issue","error","not working","broken","unable","missing","not showing",
        "not coming","not loading","not visible","fails","failure","incorrect","wrong",
        "422","400","crash","empty","not updating","not responsive","invalid","overlap",
        "breaking","blank","disappear","duplicate","stale"]
_REGRESSION = ["regression","previously working","stopped working","broke after",
               "after release","after update","prod issue","prod |"]
_FEATURE = ["add ","create ","new ","integration","implement","build","setup",
            "hubspot","calendly","expose","migration","new feature"]
_CRITICAL = ["crash","not loading","data loss","down","blocked","unable to create",
             "prod issue","invalid phone","broken","prod |","mail not loading"]
_US = ["us ","usa","us dashboard","us demo","us cluster","midtown"]
_UK = ["uk","downing","fusion","vita","hfs","yourtribe","collegiate"]
_LARGE = ["integration","revamp","migration","calendly","hubspot","new feature",
          "create viewings","dashboard form"]
_QUICK = ["css","alignment","typo","colour","color","remove beta","rename",
          "tooltip","icon","placeholder","sidebar changes","checklist","logo"]


def _infer(name: str) -> dict:
    n = name.lower()

    for kw in _REGRESSION:
        if kw in n:
            tt = "regression"; break
    else:
        for kw in _BUG:
            if kw in n:
                tt = "bug"; break
        else:
            for kw in _FEATURE:
                if kw in n:
                    tt = "feature"; break
            else:
                tt = "enhancement"

    is_critical = any(kw in n for kw in _CRITICAL)
    sev = "critical" if is_critical else ("major" if tt in ("regression", "bug") else "minor")

    dur = ">3days" if (tt == "feature" or any(kw in n for kw in _LARGE)) else \
          "<1day"  if any(kw in n for kw in _QUICK) else "1-3days"

    mkt = "usa" if any(kw in n for kw in _US) else \
          "uk"  if any(kw in n for kw in _UK) else "uk"

    occ = "frequent" if tt == "regression" or is_critical else \
          "multiple" if tt == "bug" else "once"

    return {"ticket_type": tt, "severity": sev, "duration": dur,
            "market": mkt, "occurrence": occ}


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class Ticket:
    id: str
    title: str
    category: str
    raw: dict = field(default_factory=dict)
    priority_score: float = 0.0
    effort_score: float = 0.0
    reprio_score: float = 0.0
    bypassed: bool = False
    bypass_reason: str = ""


# ── scoring engine ────────────────────────────────────────────────────────────

class Scorer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sc  = cfg["scores"]
        self.ew  = cfg["effort_weights"]

    def _get(self, mapping_key: str, value: str, default: int = 1) -> int:
        m = self.sc.get(mapping_key, {})
        return m.get(str(value).strip().lower(), default)

    def effort(self, row: dict) -> float:
        dur  = self._get("duration",       row.get("duration", "1-3days"))
        dep  = self._get("dependencies",   row.get("dependencies", "none"))
        ti   = row.get("teams_involved", "1").strip()
        # normalise "3+" and any number ≥ 3
        try:
            n = int(ti.rstrip("+"))
            ti = "3+" if n >= 3 else str(n)
        except ValueError:
            ti = "1"
        teams = self._get("teams_involved", ti)
        return round(
            dur   * self.ew["duration"] +
            teams * self.ew["teams"] +
            dep   * self.ew["dependencies"],
            2
        )

    def _score_client(self, row: dict) -> float:
        w = self.cfg["weights"]["client_ticket"]
        return round(
            self._get("client_priority", row.get("client_priority","low"))  * w["client_priority"] +
            self._get("ticket_type",     row.get("ticket_type","enhancement")) * w["ticket_type"] +
            self._get("severity",        row.get("severity","minor"))        * w["severity"] +
            self._get("occurrence",      row.get("occurrence","once"))       * w["occurrence"] +
            self._get("chargeable",      row.get("chargeable","free"))       * w["chargeable"] +
            self.effort(row)                                                 * w["effort"] +
            self._get("market",          row.get("market","uk"))             * w["market"],
            2
        )

    def _score_internal(self, row: dict) -> float:
        w = self.cfg["weights"]["internal_ticket"]
        return round(
            self._get("ticket_owner",  row.get("ticket_owner","tech"))          * w["ticket_owner"] +
            self._get("ticket_type",   row.get("ticket_type","enhancement"))    * w["ticket_type"] +
            self._get("severity",      row.get("severity","minor"))             * w["severity"] +
            self._get("occurrence",    row.get("occurrence","once"))            * w["occurrence"] +
            self.effort(row)                                                    * w["effort"] +
            self._get("chargeable",    row.get("chargeable","free"))            * w["chargeable"] +
            self._get("market",        row.get("market","uk"))                  * w["market"],
            2
        )

    def _score_ask(self, row: dict) -> float:
        w = self.cfg["weights"]["client_ask"]
        return round(
            self._get("due_date_urgency", row.get("due_date_urgency","low"))   * w["due_date_urgency"] +
            self._get("client_priority",  row.get("client_priority","low"))    * w["client_priority"] +
            self._get("ticket_status",    row.get("ticket_status","to_do_design")) * w["ticket_status"] +
            self.effort(row)                                                   * w["effort"],
            2
        )

    def reprio(self, row: dict) -> float:
        """Higher = easier to remove from sprint mid-reprioritisation."""
        cp  = self._get("client_priority", row.get("client_priority", "low"))
        sev = self._get("severity",        row.get("severity", "low"))
        dep = self._get("dependencies",    row.get("dependencies", "none"))
        prog_map = {"not_started": 5, "in_progress": 3, "done": 0}
        prog = prog_map.get(row.get("progress", "not_started").strip().lower(), 5)
        inv_cp  = 6 - cp
        inv_sev = 6 - sev
        return round(min((inv_cp * 0.25) + (prog * 0.20) + (inv_sev * 0.15) +
                         (dep * 0.10) * 4, 5.0), 2)

    def bypass(self, row: dict) -> tuple:
        if str(row.get("bypass","")).lower() in ("true","yes","1"):
            return True, row.get("bypass_reason", "Manual bypass")
        cp  = row.get("client_priority","").lower()
        sev = row.get("severity","").lower()
        own = row.get("ticket_owner","").lower()
        dep = row.get("dependencies","").lower()
        if cp == "high" and sev == "critical":
            return True, "Client Priority=High + Severity=Critical"
        if own == "bd" and cp == "high":
            return True, "BD ticket + Client Priority=High"
        if dep == "blocks" and sev == "critical":
            return True, "Blocks other high-priority work"
        return False, ""

    def score(self, ticket: Ticket) -> Ticket:
        # Fill blanks via heuristics before scoring
        inferred = _infer(ticket.title)
        row = {**inferred, **{k: v for k, v in ticket.raw.items() if v}}

        bypassed, reason = self.bypass(row)
        ticket.bypassed      = bypassed
        ticket.bypass_reason = reason
        ticket.effort_score  = self.effort(row)
        ticket.reprio_score  = self.reprio(row)

        cat = ticket.category
        if   cat == "client_ticket":   ticket.priority_score = self._score_client(row)
        elif cat == "internal_ticket": ticket.priority_score = self._score_internal(row)
        elif cat == "client_ask":      ticket.priority_score = self._score_ask(row)
        else:                          ticket.priority_score = 0.0
        return ticket


# ── teams from assignee IDs ───────────────────────────────────────────────────

def resolve_teams(assignee_ids: str, team_map: dict) -> str:
    """Convert comma-separated assignee IDs to teams_involved string."""
    if not assignee_ids.strip():
        return ""
    ids = [i.strip() for i in assignee_ids.split(",")]
    teams = {team_map.get(i) for i in ids if team_map.get(i)}
    count = max(len(teams), 1)
    return "3+" if count >= 3 else str(count)


# ── CSV loader ────────────────────────────────────────────────────────────────

def load(path: str, team_map: dict) -> list:
    tickets = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            tid = row.get("id") or f"T{len(tickets)+1:03d}"
            cat = row.get("category","").lower()

            # resolve teams from assignee IDs if teams_involved blank
            if not row.get("teams_involved") and row.get("assignee_ids"):
                row["teams_involved"] = resolve_teams(row["assignee_ids"], team_map)

            tickets.append(Ticket(id=tid, title=row.get("title","(no title)"),
                                  category=cat, raw=row))
    return tickets


# ── sprint allocation ─────────────────────────────────────────────────────────

def allocate(tickets: list, cfg: dict) -> dict:
    total = sum(cfg["bandwidth"].values())
    alloc = cfg["allocation"]
    buckets = {k: {"pct": v, "hours": int(total * v), "tickets": []}
               for k, v in alloc.items()}
    for t in tickets:
        key = "buffer" if t.bypassed else t.category
        if key in buckets:
            buckets[key]["tickets"].append(t)
    for key in ("client_ticket","internal_ticket","client_ask"):
        buckets[key]["tickets"].sort(key=lambda x: x.priority_score, reverse=True)
    return buckets, total


# ── markdown renderer ─────────────────────────────────────────────────────────

EFFORT_LABEL = {(4.0, 5.1): "Low effort", (3.0, 4.0): "Medium effort",
                (2.0, 3.0): "High effort", (0.0, 2.0): "Very high — consider splitting"}

def effort_label(score: float) -> str:
    for (lo, hi), label in EFFORT_LABEL.items():
        if lo <= score < hi:
            return label
    return "Unknown"

def render(sprint: str, buckets: dict, total: int, cfg: dict) -> str:
    bw = cfg["bandwidth"]
    lines = [
        f"# {sprint} — Sprint Scoring Report\n",
        "## Team Bandwidth\n",
        "| Team | Hours |", "|------|-------|",
    ] + [f"| {t.title()} | {h}h |" for t, h in bw.items()] + [
        f"| **Total** | **{total}h** |", "",
        "## Allocation\n",
        "| Bucket | % | Hours |", "|--------|---|-------|",
        f"| Client Tickets | 50% | {buckets['client_ticket']['hours']}h |",
        f"| Internal Tickets | 30% | {buckets['internal_ticket']['hours']}h |",
        f"| Client Asks | 10% | {buckets['client_ask']['hours']}h |",
        f"| Buffer | 10% | {buckets['buffer']['hours']}h |", "",
    ]

    labels = {"client_ticket": "Client Tickets (50%)",
              "internal_ticket": "Internal Tickets (30%)",
              "client_ask": "Client Asks (10%)"}

    for key, label in labels.items():
        lines.append(f"## {label}\n")
        rows = buckets[key]["tickets"]
        if not rows:
            lines.append("_No tickets._\n"); continue
        lines += ["| # | ID | Title | Score | Effort | Reprio |",
                  "|---|----|-------|-------|--------|--------|"]
        for i, t in enumerate(rows, 1):
            lines.append(f"| {i} | `{t.id}` | {t.title} | **{t.priority_score}** | "
                         f"{t.effort_score} ({effort_label(t.effort_score)}) | {t.reprio_score} |")
        lines.append("")

    bypass = buckets["buffer"]["tickets"]
    lines.append("## Auto-Included (Bypass)\n")
    if bypass:
        lines += ["| ID | Title | Reason |", "|----|-------|--------|"]
        for t in bypass:
            lines.append(f"| `{t.id}` | {t.title} | {t.bypass_reason} |")
    else:
        lines.append("_None._")

    lines += ["", "---",
              "_Sprint Scorer — works with ClickUp, Jira, Linear, or any CSV export._"]
    return "\n".join(lines)


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Sprint Scorer")
    p.add_argument("csv",             help="Path to tickets CSV")
    p.add_argument("--sprint",        default="Sprint", help="Sprint label")
    p.add_argument("--config",        default="config.json", help="Config file path")
    p.add_argument("--output",        default=None, help="Save report to .md file")
    args = p.parse_args()

    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else DEFAULT_CONFIG

    print(f"\nLoading: {args.csv}")
    tickets = load(args.csv, cfg.get("team_map", {}))
    print(f"Tickets: {len(tickets)}")

    scorer = Scorer(cfg)
    tickets = [scorer.score(t) for t in tickets]

    buckets, total = allocate(tickets, cfg)
    report = render(args.sprint, buckets, total, cfg)

    print("\n" + "="*60 + "\n" + report + "\n" + "="*60)

    if args.output:
        Path(args.output).write_text(report)
        print(f"\nSaved: {args.output}")


if __name__ == "__main__":
    main()
