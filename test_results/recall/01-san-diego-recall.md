# Recall Test 1: "san diego"

**Query:** `/recall "san diego"`
**Memory store:** 336 entries (129 Foobat weekly archives 2001-2010, 193 Oqodo threads 2013-2017, 14 seed entries)
**Time:** 3m 21s

## Search Phase

- `rlm recall "san diego" --deep` returned 20 matching entries (all Foobat weekly archives)
- Deep search scanned content of all 336 entries to find keyword matches
- All 20 results scored equally (score 2), so no ranking signal from index alone

## Subagent Dispatch

4 waves of 4 subagents each (16 total dispatches):

| Wave | Entries Checked | Findings |
|------|----------------|----------|
| 1 | 2005, 2004, 2009, 2010 | 0 matches |
| 2 | mid-2004, sep-2004, jun-2004, may-2004 | 0 matches |
| 3 | mar-2008, jun-2005, feb-2005, apr-2004 | 1 match found |
| 4 | feb-2005-b, jan-2005, oct-2004, oct-2004-b | 1 match found |

Then checked remaining 4 entries in wave 5: 2 more matches found.

## Results

5 San Diego mentions found across 2004-2009:

1. **User C on San Diego's protest scene** (Apr 2004) — "In San Diego the protest community is far small and immobile, this is a military town."
2. **User D's mailing address** (Oct 2004) — Posts a San Diego address during a political discussion.
3. **User C playing basketball in SD heat** (May 2008) — Planning basketball in "the hot San Diego heat."
4. **User M's Google AdWords advice** (Jul 2008) — Suggests narrowing ad location to "San Diego, or Southern California."
5. **Music recommendation** (Feb 2009) — User E recommends "BrokenBeat in San Diego, CA."

## Synthesis Quality

The system correctly:
- Found scattered mentions across different time periods and contexts
- Attributed each mention to the correct user
- Noticed a cross-cutting pattern: "User C seems to have been based there"

## Performance Notes

- 16 subagent dispatches across 4 waves is high — caused by large weekly Foobat archives (some 100K+ chars)
- First wave returned empty because subagents had to search massive entries
- Finer ingestion granularity (daily vs weekly) would improve precision
- A grep-first approach before subagent dispatch could skip entries without actual keyword matches
