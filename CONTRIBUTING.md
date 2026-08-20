# Submit a STA 701S presentation

Each speaker makes two separate submissions through GitHub:

1. Submit a title and abstract as soon as possible.
2. Submit the final slides as one PDF before the presentation.

After your title and abstract receive feedback, choose either public or
private slide delivery by commenting `/slides public` or `/slides private` on
your title pull request. Public slides follow the workflow below. A private
choice creates a private repository for your talk, where you upload the PDF
for instructor review; private slides are never copied to this public site.

You will use GitHub's website for both submissions. You will not submit code,
and you do not need command-line Git.

## What kind of talk should I prepare?

Each presentation should be no more than 20 minutes. We will then use 10–15
minutes for discussion, questions, and constructive feedback.

Your topic should reflect your stage in the program:

- Third-year students should develop and present an idea that may grow into a
  research project.
- Fourth- and fifth-year students should present their research in progress or
  completed work.

For every speaker, the central goal is to give the seminar an accessible
introduction to the problem, area, and main ideas. Provide enough motivation
and context for a broad statistical audience to participate in the discussion;
do not try to compress a paper into a dense technical treatise.

## Before you begin

- Create a free [GitHub account](https://github.com/signup) if you do not
  already have one.
- Find your assigned record ID on the seminar calendar. It will look like
  `fall-2026-01`. Use your own ID everywhere below.
- You do **not** need access to the `stat701` GitHub organization. Because this
  repository is public, GitHub will create a personal fork when you propose
  your first change. A fork is simply the copy GitHub uses to prepare your pull
  request.
- Everything submitted here is public, including your title, abstract, PDF,
  pull-request discussion, and revision history. Do not include a NetID, email
  address, private data, or material that cannot be shared publicly.
- Both the public title-and-abstract submission and the public PDF are sent to
  OpenAI for advisory reviews. Do not include confidential, sensitive,
  private, restricted, or unpublished material that you are not permitted to
  share with that service.
- Your first pull request may show that its GitHub Actions workflow is waiting
  for maintainer approval. You do not need to fix this or request repository
  access; the instructor will handle it.

## First pull request: title and abstract

Your first pull request must edit only your existing talk file:

```text
_talks/fall-2026-01.md
```

Replace `fall-2026-01` with your assigned record ID.

1. On the [STA 701S calendar](https://stat701.github.io/), find your name and
   select **Submit title and abstract**. Sign in to GitHub if prompted.
2. GitHub will open your assigned Markdown file in its web editor. If GitHub
   explains that it will create a fork, continue; no organization access is
   required.
3. In the block between the two `---` lines, change only the empty `title`
   value. Keep the quotation marks. For example:

   ```yaml
   title: "A clear and informative talk title"
   ```

4. Below the second `---` line, replace the instructional HTML comment with
   your abstract. Write it as ordinary prose for a broad statistical audience:
   identify the problem or area, explain why it matters, state the central
   idea, and tell the audience what they should expect to learn. Do not change
   `record_id`, `speaker`, `date`, `order`, `year_in_program`, or `semester`.
5. Select **Commit changes…** or **Propose changes**. Use a short commit message
   such as `Add title and abstract for fall-2026-01`.
6. Continue to **Create pull request**. Set the pull-request title to
   `Title and abstract: fall-2026-01`, complete the checklist, and submit it to
   `stat701/stat701.github.io`.

The deterministic checks run first. The instructor then verifies that the
GitHub account belongs to the scheduled student and manually launches
**Register student and review**. This securely associates your record with your
stable GitHub account ID and runs the first advisory title-and-abstract review.
The association is not based only on your username, so changing your GitHub
username later does not transfer the record to someone else.

The final file should have this general shape:

```markdown
---
record_id: fall-2026-01
speaker: "Speaker Name"
date: 2026-08-31
order: 1
year_in_program: 3
semester: fall-2026
title: "A clear and informative talk title"
---

This is the abstract. It explains the statistical idea, why it is interesting,
and what the audience should expect to learn.
```

The example values are illustrative. Preserve all identifying and scheduling
values already present in your assigned file.

You may revise this file on the same pull-request branch while the pull request
is open. Once the instructor has registered your account, eligible new versions
from that account are recognized and reviewed automatically. After the title
and abstract are merged, the published record is locked against later student
edits. Contact the instructor if a correction is needed.

## Second pull request: PDF slides

Make the slides submission as a separate pull request. It must add exactly one
file:

```text
assets/slides/fall-2026/fall-2026-01.pdf
```

Both the filename and the part before `.pdf` must match your assigned record ID
exactly. Only PDF is accepted; do not upload PowerPoint, Keynote, HTML, LaTeX,
Quarto, images, source files, or code. The PDF must be no larger than 25 MiB,
which is GitHub's limit for browser uploads.

1. Wait until the title-and-abstract pull request has been merged.
2. Open your personal fork, normally at
   `https://github.com/YOUR-USERNAME/stat701.github.io`.
3. If GitHub shows **Sync fork**, select it and then select **Update branch**.
   Make sure the branch selector shows `main`.
4. Open `assets`, then `slides`, then `fall-2026`.
5. Select **Add file → Upload files**.
6. Upload exactly one PDF named with your record ID, for example
   `fall-2026-01.pdf`.
7. Commit the upload directly to `main` in your personal fork. Then select
   **Contribute → Open pull request** in your fork.
8. Confirm that the base repository is `stat701/stat701.github.io`, the base
   branch is `main`, and the pull request contains only your one PDF.
9. Set the pull-request title to `Slides: fall-2026-01`, complete the checklist,
   and create the pull request.

Open the slides pull request from the same GitHub account that the instructor
registered from your title-and-abstract pull request. A PDF submitted from a
different account is rejected before any AI review runs.

After the PDF is merged, the website will automatically make the presentation
entry clickable. The published PDF is then locked against later student
replacement. While the slides pull request remains open, you may replace the
PDF on the same branch in response to feedback; each permitted new version from
your registered account is recognized automatically. Contact the instructor if
a correction is needed after merge. Do not edit the calendar, HTML, or your
talk file to add a link.

## Automated checks and review

GitHub runs checks on each pull request.

- For your first title-and-abstract submission, the checks confirm that only
  your assigned file changed, the protected scheduling fields stayed
  unchanged, and both a substantive title and abstract are present. The first
  AI review does **not** run automatically: the instructor verifies your
  identity, registers your account, and launches it. The advisory review then
  evaluates whether the title and abstract are coherent, motivating,
  appropriate to your year in the program, and framed as an accessible
  introduction rather than a dense technical summary. It does not judge
  novelty or factual correctness. Later eligible revisions by your registered
  account are reviewed automatically.
- For a slides submission, the checks confirm that the pull request adds only
  the correctly named PDF, that it is unencrypted and contains no JavaScript or
  embedded files, and that every page can be opened and rendered. This
  deterministic technical check is separate from a semantic review that sends
  the PDF to OpenAI. That reviewer approaches the slides as a statistically
  literate first-year statistics PhD student who can read graduate textbooks
  and strong papers but is not a specialist in the topic. Its short feedback
  focuses on usefulness, accessibility, narrative, visual appeal, confusing
  slides, and slides with an overwhelming amount of on-screen mathematics. It
  does not certify correctness or grade the talk.

Each exact Markdown or PDF file version receives at most one AI attempt. A new
file version can receive one new review. If the reviewer is uncertain, cannot
read the file, suspects that correctness or specialist domain judgment is
needed, detects a possible confidentiality concern, or encounters a service
failure, it escalates the submission to the instructor instead of retrying that
same version automatically.

If a check asks for a revision, edit the same file on the same branch in your
fork and commit the correction. The existing pull request updates
automatically; do not open a replacement pull request.

If an automated review is uncertain or cannot evaluate the submission, it asks
for human review. If a PDF cannot be opened or rendered, the required check
fails and a maintainer inspects the problem. Human review is not a rejection:
the instructor will either approve the submission or explain what needs to
change. Registration and AI comments never approve or merge a pull request.
The instructor reviews and approves every merge after the required checks or
human review are complete.

## Common problems

- **The pull request shows several changed files:** close it without merging,
  update your fork from `main`, and prepare a new pull request containing only
  your assigned Markdown file or only your assigned PDF.
- **The checks say a scheduling field changed:** restore every front-matter
  value except `title` to the value on the course repository's `main` branch.
- **The checks say a published file is locked:** contact the instructor. Do
  not open another student pull request to change a merged title, abstract, or
  PDF.
- **The PDF check fails:** export the presentation again as a standard,
  unencrypted PDF, verify that it opens locally, and replace the PDF in the
  same pull-request branch.
- **GitHub says workflows need approval:** wait for the instructor. This is
  normal for a first external pull request and does not mean that you need
  organization access.
- **The account-ownership check fails:** make sure the pull request was opened
  from the same GitHub account that the instructor registered. Contact the
  instructor rather than using another account.
- **The website still does not show the update:** confirm that the pull request
  was merged. The public site updates after the merged change is deployed.
