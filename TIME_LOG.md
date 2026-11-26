# Time log

Clock times are taken with `date` on the machine (IST) when a stage starts and stops.
Anything not captured that way is marked as such rather than estimated.

| Stage | Start | Stop | Minutes | Notes |
|---|---|---|---|---|
| Ideation before this session | not captured | not captured | – | To be filled in by Harshvardhan. |
| Read brief, check SDK docs, questions | not captured | 15:59 | – | First timestamp taken at 15:59, after the brief and SDK docs were read. |
| Decisions on open questions, plan written, plan reviewed and approved | 15:59 | 16:50 | 51 | Includes Harshvardhan's review time. |
| Task 0: repo, plan, ADR, logs | 16:50 | 16:51 | 1 | |
| Task 1: PRD | 16:51 | 16:53 | 2 | Stops when the PRD is committed; review time is logged separately. |
| PRD review, questions about resources and prompts | 16:53 | 17:14 | 21 | Harshvardhan reviewing; AI answering. |
| Task 2: tech spec | 17:14 | 17:16 | 2 | Includes PRD revision 1. |
| Tech spec review | 17:16 | 17:51 | 35 | Harshvardhan reviewing. |
| Task 3: architecture, tag spec-v1 | 17:51 | 17:52 | 1 | |
| Architecture review | 17:52 | 17:59 | 7 | Harshvardhan reviewing. |
| Task 4: scaffold, SDK check | 17:59 | 18:01 | 2 |  |
| Task 5: money, rules, errors | 18:01 | 18:02 | 1 |  |
| Task 6: schema, db, seed | 18:02 | 18:03 | 1 |  |
| Task 7: identity | 18:03 | 18:04 | 1 |  |
| Task 8: service reads | 18:04 | 18:05 | 1 |  |
| Task 9: service writes | 18:05 | 18:07 | 2 |  |
| Task 10: MCP tools | 18:07 | 18:08 | 1 |  |
| Task 11: stdio end-to-end and multi-process tests | 18:08 | 18:13 | 5 | Includes 5 repeat runs and 3 deliberate breaks of the guard. |
| Task 12: random-sequence invariant test | 18:13 | 18:15 | 2 |  |
| Task 13: traceability script | 18:15 | 18:17 | 2 |  |
| Task 14: demo script and README | 18:17 | 18:18 | 1 |  |
| Task 15: fresh-clone verification and final writeup | 18:18 | 18:20 | 2 |  |
| Other work, not part of the submission | 18:20 | 19:05 | – | Not counted. Listed so the gap in times is explained. |
| Fix found in review: rules tests compare whole tables; fresh-clone re-run; notes updated | 19:05 | 19:06 | 1 | |

## Totals

| Part | Minutes |
|---|---|
| Recorded span of the build, 15:59 to 18:20 | 141 |
| Review, decisions and questions (the three review rows plus the planning row) | 114 |
| AI writing specs, code, tests and the writeup (task rows) | 27 |
| Before 15:59 (ideation, reading the brief, checking SDK docs) | not captured |

Task rows are short because each is the AI's working time by the machine clock.
114 + 27 = 141, the recorded span of the build. The later fix found in review took a further 1 minutes.
