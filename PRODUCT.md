# PRODUCT

**User.**
- Venture partners, studio operators and scouts who passed on, or watched die, ideas that were early rather than wrong.
- Second audience: founders deciding whether to re-attempt a dead category, and the search and AI-answer engines that cite "why did X fail" pages.

**Painful job.** "Which of the ideas we passed on (or watched die) has unlocked, and what exactly changed?" Today this rests on partner memory and sector analysts. PitchBook, CB Insights and Harmonic track companies, not category timing, and nobody scores timing calls in public.

**Promise.** For any dead startup category, in five seconds, you get:
- what killed it;
- whether that constraint has crossed, shown on a live public metric;
- who died proving demand;
- a dated call that resolves in public and cannot be quietly edited.

**Wedge.** Publish first, then build:
- a free public board of dated, falsifiable calls, including no-go calls and "I don't know";
- a private re-look screen that runs in the browser on a fund's own passed deals;
- each call page is a citable, shareable search answer.

**Why now.**
- Competitive windows have compressed: founding to $100M fell from about 7 years to 2, so the human notice-validate-recruit loop is now slower than the window.
- Legal and regulatory unlocks (E5) are scheduled in public, but nobody maps them onto category space.
- A forward-registered track record only accrues in calendar time, so the clock should start now.

**Activation metric.** `relook_match`: a visitor runs the re-look screen and at least one of their deals matches a category. That is the fund job, and the step that precedes a paid report. Secondary signals: `share` (a call shared, embedded or cited) and `ledger_verify`. Events are instrumented in `site/assets/app.js` and count once `IL_GOATCOUNTER` is set.

**First revenue event.** A fund requests a private re-look report on its full pass archive, through the `IL_RELOOK_REPORT_URL` slot hosted off GitHub Pages (Pages is non-commercial). Later: the E5 regulatory feed.

**What v1 deliberately won't do.**
- Upload or store anyone's decks (confidential third-party material).
- Score individual companies, or make predictions about them.
- Let a model decide verdicts.
- Scrape the market or run the linguistic index (falsified).
- Touch the fund vehicle (Investment Advisers Act, Reg D).
- Give investment advice.
