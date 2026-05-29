# Launch playbook

Order of operations once the arXiv announcement email lands
(`announce@arxiv.org` → look for `arXiv:2605.NNNNN`).

## Step 0 — substitute the arXiv ID everywhere

Every file in this dir has `<ARXIV_ID>` placeholders that need
the real ID pasted in once you have it. Fast: open each file
in your editor, find/replace `<ARXIV_ID>` → `2605.XXXXX`.

The ID arrives via email; the public URL is
`https://arxiv.org/abs/<ARXIV_ID>`.

## Step 1 — repo housekeeping (5 min)

Update `CITATION.cff` and the README to point to the paper:

```bash
# Edit CITATION.cff:
#   add `preferred-citation:` block with the arXiv reference,
#   plus a `doi:` line pointing to https://doi.org/10.48550/arXiv.<ARXIV_ID>

# Edit README.md hero:
#   add a "Cite this paper" line near the badges:
#   [![arXiv](https://img.shields.io/badge/arXiv-<ARXIV_ID>-b31b1b.svg)](https://arxiv.org/abs/<ARXIV_ID>)

# Commit + push.
```

(I will wire both for you in seconds once you paste the ID.)

## Step 2 — coordinated burst (45 min, do the next four in this order)

1. **Show HN post** (`02-show-hn.md`) — submit first; HN is the
   slowest medium and the front-page algorithm rewards early
   upvotes more than late ones.
2. **Twitter / X thread** (`01-tweet-thread.md`) — fire 5
   minutes after Show HN. Include the HN link in the last
   tweet so people boost the HN post.
3. **LinkedIn long-form** (`03-linkedin.md`) — 15 minutes
   after Twitter. Cross-link the Twitter thread.
4. **DMs in batches** (`04-dm-targets.md`) — last. Stagger over
   2-3 days; sending 20 DMs in the same hour looks like spam
   and several platforms will rate-limit you.

## Step 3 — engage every reply for the first 24 h

Show HN and X both reward fast author engagement. Set a 30-min
timer; refresh every 30 min for the first 6 hours, reply to
anything that isn't outright noise. Quality of the comment
thread is a stronger signal than upvote count.

## Step 4 — file the adapter PRs upstream (Day 2-3)

Per `docs/kickoff/PROJECT-PLAN.md` (week 4): file PRs into
mem0, Letta, Cognee with the AMP-compatible adapter. Open as
"Would you accept an AMP-compatible adapter?" issues first,
PRs second. This is the move that gets the maintainers'
attention.

## Step 5 — DM the targets in `04-dm-targets.md`

Once the public posts have ~24 hours of organic traction,
start the personalized DMs. Reference one piece of each
target's published work + the arXiv link. Stagger over 2-3
days.

## Anti-patterns to avoid

- **Do NOT** post to multiple subreddits within the same hour;
  Reddit treats cross-post velocity as spam. Stagger by 2+ hours.
- **Do NOT** quote tweet your own thread to "boost" it; X's
  algorithm penalizes self-quote loops.
- **Do NOT** DM 20 people in the same hour. Stagger.
- **Do NOT** edit the Show HN post after the first 30 minutes;
  the algorithm penalizes edits.
- **Do NOT** ask people to upvote. HN bans this; X / LinkedIn
  ignore it.
