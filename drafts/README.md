# Draft files

One CSV per season, named after the year. This is the only place picks live —
no Python editing.

## Filling one in during the draft

Open `2026.csv` in a spreadsheet or a text editor. Each player already has six
blank rows. Type the team next to the player as each pick happens:

```csv
player,team
Sean,Ohio State
Sean,
```

Order doesn't matter — fill rows in whatever order picks come in. Rows with a
blank team are ignored, so a half-finished file loads fine and scores whatever
is filled so far.

Picks are read once at startup, so the site won't notice edits until it
restarts. Locally that means restarting uvicorn (`--reload` watches Python
files, not CSVs); in production it means the deploy that ships the commit.

**Team names must match CFBD exactly.** Copy them from `fbs_teams_2026.txt`,
which lists all 138 FBS teams by conference. The ones that bite:

| Type this | Not this |
|---|---|
| `San José State` | `San Jose State` |
| `Miami (OH)` | `Miami OH`, `Miami Ohio` |
| `Miami` | `Miami (FL)`, `Miami FL` |
| `Ole Miss` | `Mississippi` |
| `Texas A&M` | `Texas A and M` |
| `App State` | `Appalachian State` |
| `UMass` | `Massachusetts` |

## Check it before it goes live

```bash
python scripts/validate_draft.py 2026
```

Catches misspelled teams (with suggestions), the same team drafted twice, and
rosters that aren't six deep. A typo here fails silently on the website — the
team just scores zero all season — so run this before committing.

## Adding a player, or a whole new season

Add rows with a new name in the `player` column. For a new season, add
`2027.csv` with the same two columns; the season dropdown, standings, parlay
and history pages all pick it up with no code changes.
