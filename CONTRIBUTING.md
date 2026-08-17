# Submit a STA 701S presentation

Each speaker makes two separate submissions through GitHub:

1. Submit a title and abstract as soon as possible.
2. Submit the final slides as one PDF before the presentation.

You will use GitHub's website for both submissions. You will not submit code,
and you do not need command-line Git.

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
- A maintainer may send the public title and abstract to OpenAI for an optional
  automated review. Do not include confidential or sensitive information.

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
   your abstract. Write the abstract as ordinary prose. Do not change
   `record_id`, `speaker`, `date`, `order`, `year_in_program`, or `semester`.
5. Select **Commit changes…** or **Propose changes**. Use a short commit message
   such as `Add title and abstract for fall-2026-01`.
6. Continue to **Create pull request**. Set the pull-request title to
   `Title and abstract: fall-2026-01`, complete the checklist, and submit it to
   `stat701/stat701.github.io`.

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

## Second pull request: PDF slides

Make the slides submission as a separate pull request. It must add exactly one
file:

```text
assets/slides/fall-2026/fall-2026-01.pdf
```

Both the filename and the part before `.pdf` must match your assigned record ID
exactly. Only PDF is accepted; do not upload PowerPoint, Keynote, HTML, LaTeX,
Quarto, images, source files, or code.

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

After the PDF is merged, the website will automatically make the presentation
entry clickable. Do not edit the calendar, HTML, or your talk file to add a
link.

## Automated checks and review

GitHub runs checks on each pull request.

- For a title-and-abstract submission, the checks confirm that only your
  assigned file changed, the protected scheduling fields stayed unchanged,
  and both a substantive title and abstract are present. A maintainer may also
  run an optional automated review of whether the title and abstract are
  coherent, agree with one another, and clearly describe an interesting
  statistical idea for a statistics Ph.D. seminar. It does not require you to
  present your own research, and it does not judge novelty or factual
  correctness.
- For a slides submission, the checks confirm that the pull request adds only
  the correctly named PDF and that the file can be opened and rendered.

If a check asks for a revision, edit the same file on the same branch in your
fork and commit the correction. The existing pull request updates
automatically; do not open a replacement pull request.

If an automated review is uncertain or cannot evaluate the submission, it asks
for human review. If a PDF cannot be opened or rendered, the required check
fails and a maintainer inspects the problem. Human review is not a rejection:
the instructor will either approve the submission or explain what needs to
change. A maintainer merges the pull request after the required checks or human
review are complete.

## Common problems

- **The pull request shows several changed files:** close it without merging,
  update your fork from `main`, and prepare a new pull request containing only
  your assigned Markdown file or only your assigned PDF.
- **The checks say a scheduling field changed:** restore every front-matter
  value except `title` to the value on the course repository's `main` branch.
- **The PDF check fails:** export the presentation again as a standard,
  unencrypted PDF, verify that it opens locally, and replace the PDF in the
  same pull-request branch.
- **The website still does not show the update:** confirm that the pull request
  was merged. The public site updates after the merged change is deployed.
