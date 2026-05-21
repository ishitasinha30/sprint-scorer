# Sprint Scorer

A tool-agnostic sprint prioritization engine for product managers. Export your backlog from **any** task tracking tool — ClickUp, Jira, Linear, Notion, or a spreadsheet — and get a data-driven, ranked sprint plan in seconds.

Built on a weighted scoring matrix covering client priority, ticket type, severity, effort, market, and more.

---

## How it works

```mermaid
flowchart TD
    classDef input    fill:#6366f1,stroke:#4338ca,color:#fff,rx:6
    classDef process  fill:#0ea5e9,stroke:#0284c7,color:#fff,rx:6
    classDef decision fill:#f59e0b,stroke:#b45309,color:#000,rx:6
    classDef scoring  fill:#3b82f6,stroke:#1d4ed8,color:#fff,rx:6
    classDef bypass   fill:#ef4444,stroke:#b91c1c,color:#fff,rx:6
    classDef bucket   fill:#8b5cf6,stroke:#6d28d9,color:#fff,rx:6
    classDef output   fill:#10b981,stroke:#047857,color:#fff,rx:6

    IN[/"📋 Your Backlog
    ClickUp · Jira · Linear · Notion · CSV"/]:::input

    INFER["🔍 Auto-infer missing fields
    from ticket title keywords"]:::process

    CAT{"Ticket
    Category"}:::decision

    IN --> INFER --> CAT

    CAT -->|"client_ticket"| CT["🏢 Client Ticket
    ─────────────────
    Priority      20%
    Severity      15%
    Occurrence    15%
    Effort        35%
    Type           5%
    Chargeable     5%
    Market         5%"]:::scoring

    CAT -->|"internal_ticket"| IT["🔧 Internal Ticket
    ─────────────────
    Owner         20%
    Severity      15%
    Occurrence    15%
    Effort        35%
    Type           5%
    Chargeable     5%
    Market         5%"]:::scoring

    CAT -->|"client_ask"| CA["💬 Client Ask
    ─────────────────
    Status        35%
    Urgency       30%
    Priority      20%
    Effort        15%"]:::scoring

    CT & IT & CA --> BYP{"Auto-Bypass
    Check"}:::decision

    BYP -->|"Priority=High + Severity=Critical
    BD ticket + High Priority
    Blocks high-priority work
    bypass=true in CSV"| FORCE["⚡ Force Include
    skip scoring"]:::bypass

    BYP -->|"standard path"| RANK["📊 Rank by Score
    0–5 per parameter
    weighted sum → final score"]:::process

    FORCE & RANK --> ALLOC

    subgraph BUCKETS["📦 Sprint Allocation"]
        ALLOC["Fit to budget"] --> B1["🏢 Client Tickets · 50%"]:::bucket
        ALLOC --> B2["🔧 Internal Tickets · 30%"]:::bucket
        ALLOC --> B3["💬 Client Asks · 10%"]:::bucket
        ALLOC --> B4["🔄 Buffer · 10%"]:::bucket
    end

    B1 & B2 & B3 & B4 --> OUT[/"📝 Ranked Sprint Plan
    Markdown report · stdout"/]:::output
```

---

## Effort score breakdown

Effort is a composite sub-score that feeds into each ticket's final score at **35% weight**.

```mermaid
flowchart LR
    classDef factor fill:#0ea5e9,stroke:#0284c7,color:#fff,rx:6
    classDef out    fill:#f59e0b,stroke:#b45309,color:#000,rx:6

    D["⏱️ Duration
    ──────────
    &lt;1 day  → 5
    1–3 days → 3
    &gt;3 days  → 1
    ── weight: 40%"]:::factor

    T["👥 Teams Involved
    ──────────────
    1 team  → 5
    2 teams → 3
    3+ teams → 1
    ── weight: 30%"]:::factor

    DEP["🔗 Dependencies
    ──────────────
    none    → 5
    relates → 3
    blocks  → 1
    ── weight: 30%"]:::factor

    EFF["⚡ Effort Score
    ──────────────
    (D×0.4) + (T×0.3)
    + (DEP×0.3)
    ── 35% of total"]:::out

    D   --> EFF
    T   --> EFF
    DEP --> EFF
```

> Lower effort (quick, single-team, no blockers) scores higher — the model favours high-impact, low-friction tickets.

---

## Sprint budget

```mermaid
pie title Sprint Budget Allocation
    "🏢 Client Tickets" : 50
    "🔧 Internal Tickets" : 30
    "💬 Client Asks" : 10
    "🔄 Buffer" : 10
```

---

## Scoring values at a glance

```mermaid
flowchart LR
    classDef h fill:#10b981,stroke:#047857,color:#fff,rx:4
    classDef m fill:#f59e0b,stroke:#b45309,color:#000,rx:4
    classDef l fill:#ef4444,stroke:#b91c1c,color:#fff,rx:4

    subgraph PRI["Client Priority"]
        P1["High · 5"]:::h
        P2["Medium · 3"]:::m
        P3["Low · 1"]:::l
    end

    subgraph SEV["Severity"]
        S1["Critical · 5"]:::h
        S2["Major · 4"]:::h
        S3["Minor · 3"]:::m
        S4["Low · 1"]:::l
    end

    subgraph TYP["Ticket Type"]
        T1["Regression · 5"]:::h
        T2["Bug · 4"]:::h
        T3["Enhancement · 3"]:::m
        T4["Feature · 1"]:::l
    end

    subgraph CHG["Chargeable"]
        C1["Chargeable · 5"]:::h
        C2["Strategic · 3"]:::m
        C3["Free · 1"]:::l
    end

    subgraph MKT["Market"]
        M1["USA · 5"]:::h
        M2["UK · 3"]:::m
        M3["Europe · 1"]:::l
    end
```

---

## Quickstart

```bash
# 1. Fill in your tickets
cp template.csv my_sprint.csv
# Edit my_sprint.csv with your backlog tickets

# 2. Configure your team
# Edit config.json — add team members, set bandwidth, adjust weights

# 3. Run
python score.py my_sprint.csv --sprint "Sprint 27"

# 4. Save as markdown
python score.py my_sprint.csv --sprint "Sprint 27" --output sprint27.md
```

---

## Example output

Scored sprint plan for a fictional e-commerce app (Shopify-style):

```
## Client Tickets (50%)

| # | ID     | Title                                              | Score  | Effort          |
|---|--------|----------------------------------------------------|--------|-----------------|
| 1 | SH-204 | Checkout page freezing on mobile Safari            |  4.32  | 5.0 (Low)       |
| 2 | SH-198 | Order confirmation emails not sending              |  4.18  | 4.2 (Low)       |
| 3 | SH-211 | Discount codes returning 422 on apply              |  4.05  | 3.0 (Medium)    |
| 4 | SH-187 | Product search returning wrong results for EU store|  3.91  | 3.6 (Medium)    |
| 5 | SH-220 | Inventory count not updating after bulk import     |  3.85  | 3.0 (Medium)    |

## Internal Tickets (30%)

| # | ID     | Title                                              | Score  | Effort          |
|---|--------|----------------------------------------------------|--------|-----------------|
| 1 | SH-301 | Improve error logging on payment webhooks          |  3.20  | 4.2 (Low)       |
| 2 | SH-289 | Refactor duplicate endpoints in orders API         |  3.02  | 4.2 (Low)       |
| 3 | SH-310 | Upgrade Node.js to v20 across backend services     |  2.41  | 3.6 (Medium)    |

## Auto-Included (Bypass)

| ID     | Title                                              | Reason                            |
|--------|----------------------------------------------------|-----------------------------------|
| SH-191 | Payments down — all transactions failing at checkout | Priority=High + Severity=Critical |
```

---

## CSV columns

| Column | Required | Description |
|--------|----------|-------------|
| `id` | Yes | Ticket ID from your tool |
| `title` | Yes | Ticket name/description |
| `category` | Yes | `client_ticket` / `internal_ticket` / `client_ask` |
| `client_priority` | Scored | `high` / `medium` / `low` |
| `ticket_type` | Scored | `regression` / `bug` / `enhancement` / `feature` |
| `severity` | Scored | `critical` / `major` / `minor` / `low` |
| `occurrence` | Scored | `frequent` / `multiple` / `once` |
| `chargeable` | Scored | `chargeable` / `strategic` / `free` |
| `duration` | Scored | `<1day` / `1-3days` / `>3days` |
| `teams_involved` | Scored | `1` / `2` / `3+` — or leave blank if using `assignee_ids` |
| `assignee_ids` | Optional | Pipe-separated assignee IDs (e.g. `87653460\|87653461`). Mapped to teams via `config.json` |
| `dependencies` | Scored | `none` / `relates` / `blocks` |
| `market` | Scored | `usa` / `uk` / `europe` |
| `ticket_owner` | Internal only | `bd` / `tech` / `qa` / `marketing` / `design` |
| `due_date_urgency` | Client ask only | `critical` / `moderate` / `low` |
| `ticket_status` | Client ask only | `ready` / `customer_review` / `to_do_design` |
| `progress` | Optional | `not_started` / `in_progress` / `done` |
| `bypass` | Optional | `true` to skip scoring and auto-include |
| `bypass_reason` | Optional | Reason for bypass |

> **Blank fields are fine.** The scorer infers missing values from the ticket title using keyword heuristics. The more fields you fill in, the more accurate the score.

---

## config.json

```json
{
  "bandwidth": {
    "backend": 170,
    "frontend": 185,
    "ai": 115,
    "qa": 175
  },
  "team_map": {
    "87653460": "backend",
    "87653461": "frontend"
  },
  "allocation": {
    "client_ticket": 0.50,
    "internal_ticket": 0.30,
    "client_ask": 0.10,
    "buffer": 0.10
  }
}
```

**`team_map`**: Map assignee IDs from your tool to team names. Used to calculate `teams_involved` automatically from `assignee_ids`. Get IDs from your tool's API or export.

---

## Exporting from your tool

| Tool | How to export |
|------|--------------|
| **ClickUp** | List view → Export → CSV |
| **Jira** | Backlog → Export Issues → CSV |
| **Linear** | Issues → Export → CSV |
| **Notion** | Database → Export → CSV |
| **Spreadsheet** | Save as CSV |

After export, map your tool's column names to the template columns. Unscored fields are inferred automatically.

---

## Requirements

Python 3.8+. No external dependencies — standard library only.
