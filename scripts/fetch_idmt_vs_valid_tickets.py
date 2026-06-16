"""
Fetch the IDMT Value-Stream usable ticket cohort (L6).

Applies the 5-filter funnel from the EDA notebook in a single Cypher query and
writes the resulting ticket keys to a text file (one key per line, sorted).

Pipeline:
    L2  IDMT-* AND issueType='Engagement Request'
        AND creationDateEpoch >= since-date
    L3  status NOT IN {Cancelled, Blocked, New Request}
    L4  has >=1 inwardIssuesMetaData entry ending in '__implemented by'
    L5  the linked key resolves to a JIRA node with issueType='Theme'
        AND its status is not 'Cancelled'
    L6  that Theme's businessValueStreams matches \\{VSR\\d+\\}\\s*$

Connection settings are read from environment variables (.env via python-dotenv
if installed; otherwise plain os.environ):
    NEO4J_URI       e.g. bolt://10.237.49.117:7687
    NEO4J_USER      e.g. neo4j
    NEO4J_PASSWORD
    NEO4J_DATABASE  default 'neo4j'

Usage:
    python scripts/fetch_idmt_vs_valid_tickets.py
    python scripts/fetch_idmt_vs_valid_tickets.py --output output_prod/idmt_vs_valid_ticket_keys.txt
    python scripts/fetch_idmt_vs_valid_tickets.py --since 2023-01-01 --stdout
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from neo4j import GraphDatabase

DEFAULT_SINCE_DATE = "2023-01-01"
DEFAULT_OUTPUT = "output_prod/idmt_vs_valid_ticket_keys.txt"
IDMT_KEY_PREFIX = "IDMT-"
SOURCE_ISSUE_TYPE = "Engagement Request"
THEME_ISSUE_TYPE = "Theme"
EXCLUDE_STATUSES = ["Blocked", "Cancelled", "New Request"]   # ER (L3) status exclusion
THEME_EXCLUDE_STATUSES = ["Cancelled"]                       # Theme (L5) status exclusion
INWARD_LINK_TYPE = "implemented by"
VSR_REGEX = r".*\{VSR\d+\}\s*$"

CYPHER = """
MATCH (er:JIRA)
WHERE er.key STARTS WITH $prefix
  AND er.issueType = $source_issue_type
  AND er.creationDateEpoch >= $since_epoch
  AND NOT er.status IN $exclude_statuses
WITH er,
  [m IN coalesce(er.inwardIssuesMetaData, [])
     WHERE m ENDS WITH ('__' + $link_type)
     | split(m, '__')[0]] AS linked_keys
WHERE size(linked_keys) > 0
UNWIND linked_keys AS linked_key
MATCH (theme:JIRA {key: linked_key})
WHERE theme.issueType = $theme_type
  AND NOT theme.status IN $theme_exclude_statuses
  AND theme.businessValueStreams IS NOT NULL
  AND theme.businessValueStreams =~ $vsr_regex
RETURN DISTINCT er.key AS ticket_key
ORDER BY ticket_key
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since", default=DEFAULT_SINCE_DATE,
                   help=f"Inclusive lower bound on creation date, YYYY-MM-DD (default {DEFAULT_SINCE_DATE})")
    p.add_argument("--output", "-o", default=DEFAULT_OUTPUT,
                   help=f"Output file path (default {DEFAULT_OUTPUT})")
    p.add_argument("--stdout", action="store_true",
                   help="Also print ticket keys to stdout (one per line)")
    p.add_argument("--no-file", action="store_true",
                   help="Skip writing the output file (use with --stdout)")
    return p.parse_args()


def to_epoch(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def fetch_valid_tickets(since_date: str) -> list[str]:
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    if not (uri and user and password):
        sys.exit("ERROR: NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD must be set "
                 "(in env or .env)")

    params = {
        "prefix": IDMT_KEY_PREFIX,
        "source_issue_type": SOURCE_ISSUE_TYPE,
        "since_epoch": to_epoch(since_date),
        "exclude_statuses": EXCLUDE_STATUSES,
        "link_type": INWARD_LINK_TYPE,
        "theme_type": THEME_ISSUE_TYPE,
        "theme_exclude_statuses": THEME_EXCLUDE_STATUSES,
        "vsr_regex": VSR_REGEX,
    }

    print(f"Connecting to {uri}  (database={database})", file=sys.stderr)
    print(f"Filters: prefix={IDMT_KEY_PREFIX!r}  issueType={SOURCE_ISSUE_TYPE!r}  "
          f"created>={since_date}  excludeStatus={EXCLUDE_STATUSES}  "
          f"linkType={INWARD_LINK_TYPE!r}  themeType={THEME_ISSUE_TYPE!r}  "
          f"themeExcludeStatus={THEME_EXCLUDE_STATUSES}",
          file=sys.stderr)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            result = session.run(CYPHER, params)
            return [record["ticket_key"] for record in result]
    finally:
        driver.close()


def main() -> int:
    args = parse_args()
    keys = fetch_valid_tickets(args.since)
    print(f"Found {len(keys):,} L6 usable ticket keys", file=sys.stderr)

    if not args.no_file:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(keys) + ("\n" if keys else ""), encoding="utf-8")
        print(f"wrote -> {out_path}", file=sys.stderr)

    if args.stdout:
        for k in keys:
            print(k)

    return 0


if __name__ == "__main__":
    sys.exit(main())
