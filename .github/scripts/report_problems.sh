#!/usr/bin/env bash
# Opens a GitHub issue when a workflow run recovered from a problem or failed.
# Usage: report_problems.sh <job-status>   (needs GH_TOKEN with issues: write)
# At most one "pipeline-health" issue is open at a time; later problems are added
# as comments to it, at most one comment every 6 hours, so a repeating problem
# can't flood your inbox.
set -euo pipefail

status="$1"
problems_file="pipeline_problems.md"
run_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"

if [ "$status" = "success" ] && [ ! -s "$problems_file" ]; then
  exit 0
fi

body="**Workflow:** ${GITHUB_WORKFLOW} — [run log](${run_url})"$'\n\n'
if [ "$status" != "success" ]; then
  body+="The run **failed** (${status}). The next scheduled run will try again; see the run log for the error."$'\n\n'
fi
if [ -s "$problems_file" ]; then
  body+="**What happened:**"$'\n'"$(cat "$problems_file")"$'\n\n'
fi
body+="Close this issue once you've had a look; a new one opens if problems come back."

gh label create pipeline-health --color d93f0b --description "Automated pipeline alerts" --force >/dev/null

existing=$(gh issue list --label pipeline-health --state open --json number --jq '.[0].number // empty')
if [ -z "$existing" ]; then
  gh issue create --title "Wait-time pipeline needs attention" --label pipeline-health --body "$body"
  exit 0
fi

last=$(gh issue view "$existing" --json comments,createdAt \
  --jq '([.createdAt] + [.comments[].createdAt]) | max')
if [ $(( $(date +%s) - $(date -d "$last" +%s) )) -gt 21600 ]; then
  gh issue comment "$existing" --body "$body"
fi
