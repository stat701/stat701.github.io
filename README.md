# STA 701S course website

Landing page for **STA 701S — Statistical Science Graduate Research Seminar**
at Duke University.

The site is deliberately lightweight and is published with GitHub Pages.
The main layout lives in `index.html`; site-wide styles live in
`assets/css/main.css`. Jekyll builds the calendar from the Markdown records in
`_talks/`. There is no client-side JavaScript.

## Preview locally

Because the calendar uses Jekyll collections and Liquid, a plain HTTP server
will show the unrendered template. Preview with a local Jekyll installation:

```sh
bundle install
bundle exec jekyll serve
```

Then open <http://localhost:4000>.

## Updating the site

- Edit seminar copy and calendar rendering in `index.html`.
- Each scheduled speaker has one instructor-created file in `_talks/`. The
  immutable front matter supplies the date, order, speaker, and year.
- Students submit a title and abstract by editing only their assigned talk
  file, then submit a single predictably named PDF in a separate pull request.
- The site automatically shows merged titles and abstracts and links a PDF
  when the expected file exists under `assets/slides/`.
- After either submission is merged, student fork pull requests cannot edit the
  published metadata or replace the published PDF. A maintainer can still make
  a reviewed correction from a same-repository branch.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for the browser-only student process.

## Validate submissions locally

Run the dependency-free unit tests with:

```sh
python3 -m unittest discover -s tests -v
```

The GitHub Actions submission check also validates PDF structure, rejects
encryption, JavaScript, and embedded files, and renders every page with `qpdf`
and Poppler before a slides pull request can be merged. This deterministic
technical gate is separate from the advisory semantic review described below.

## Maintainer merge checklist

- On a student's first title-and-abstract pull request, confirm that
  **Validate submission** passed and verify that the pull-request author is the
  scheduled student. A first-time external contributor may also need a
  maintainer to approve the GitHub Actions run.
- Open **Actions → Register student and review → Run workflow**, leave the
  workflow branch as `main`, and enter that pull-request number. This one
  trusted action binds the record to the author's stable numeric GitHub account
  ID and runs the first advisory title-and-abstract review. Launch it only after
  checking the student's identity.
- Wait for the advisory review comment. Ask for a revision or handle a human
  escalation when appropriate, then approve and merge the pull request
  yourself.
- For later revisions by that registered account, including revisions in an
  open title pull request and the later slides pull request, confirm that the
  current-head validation and advisory review have completed. A different
  GitHub account must not be treated as the registered student.
- Every pull request still requires instructor review and approval before it
  is merged; registration and AI feedback never approve or merge anything.

## Account registration and advisory AI review

The first title-and-abstract submission for a record is deliberately not sent
to OpenAI automatically. After deterministic validation, the instructor
verifies the student's GitHub identity and manually launches **Register student
and review**. The workflow records the author's stable numeric GitHub account
ID, rather than relying only on a changeable username, and then runs the first
title-and-abstract review. Students need only their own GitHub account; they do
not need organization or repository access.

Bindings are stored as append-only, Actions-bot-authored comments in the
locked [student account registry issue](https://github.com/stat701/stat701.github.io/issues/7).
Keep that issue open and locked, preserve its exact title, and do not edit or
delete its machine-generated comments. The registration workflow briefly
unlocks it only long enough for the Actions bot to append a comment, then
relocks it; all ownership checks fail closed if the ledger cannot be verified.

Once registered, new versions pushed to that open title pull request, the
student's later PDF pull request, and permitted revisions to that PDF are
recognized and reviewed automatically only when the pull-request author has the
registered account ID. Identity is checked before an OpenAI request. A title
review considers the title, abstract, and immutable year in program using the
course's year-aware rubric.

For slides, deterministic PDF inspection first checks that the file is safe to
open and that every page renders. A separate semantic review then sends the PDF
to OpenAI. The reviewer adopts the perspective of a statistically literate
first-year statistics PhD student: comfortable with graduate textbooks and
high-quality papers, but not a specialist in the speaker's area. Feedback is
brief and concentrates on whether the presentation is accessible, coherent,
visually usable, and valuable to that audience, especially calling out
particularly confusing slides or screens overwhelmed by mathematics. It does
not certify factual or mathematical correctness, research ownership, novelty,
or presentation delivery.

All repository submissions and pull-request discussions are public, and both
titles/abstracts and PDFs are sent to OpenAI for these reviews. Students must
not submit confidential, sensitive, private, or restricted material.

Each exact submitted file blob receives at most one AI attempt. Re-running a
workflow for the same version does not request another review; changing the
file creates a new blob eligible for one new attempt. An unreadable submission,
low-confidence response, suspected correctness or domain-expertise problem,
possible confidentiality concern, or service failure is escalated to the
instructor instead of being silently retried. AI feedback remains advisory.

To enable it:

1. Create a dedicated OpenAI project API key with an appropriate spending
   limit.
2. In this repository, open **Settings → Secrets and variables → Actions → New
   repository secret** and create `OPENAI_API_KEY`. Never commit the key, put it
   in a pull request, or paste it into chat.
3. For each student's first title-and-abstract pull request, run **Register
   student and review** only after verifying identity. Eligible revisions and
   slides from that registered account are handled automatically. A failed AI
   attempt is sent to human review rather than retried on the same file blob.

The default model is `gpt-5.6-terra`. To choose other compatible Responses API
models, use the repository variable `OPENAI_REVIEW_MODEL` for title/abstract
reviews and `OPENAI_PDF_REVIEW_MODEL` for slide reviews; neither variable is
needed for the default. Keep a conservative project spending limit on the API
key because the repository accepts public fork pull requests.

GitHub Pages can also render future Markdown pages through Jekyll.
