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

For an instructor-approved slot swap, keep each speaker's record ID and file,
and exchange only the `date` and `order` fields in a separate same-repository
pull request. The instructor's scheduling override accepts permutations of
existing slots while preserving every other field and the talk content.
Student pull requests cannot change scheduling fields. Both the calendar and
`schedule.json` sort by date and then presentation order, so record IDs need
not follow chronological order. Submission links, account registration, and
slide delivery settings stay attached to the same record IDs.

## Validate submissions locally

Run the dependency-free unit tests with:

```sh
python3 -m unittest discover -s tests -v
```

The GitHub Actions submission check also validates PDF structure, rejects
encryption, JavaScript, and embedded files, and renders every page with `qpdf`
and Poppler before a slides pull request can be merged. This deterministic
technical gate is separate from the advisory semantic review described below.
For public submissions, qpdf's warnings-only exit status continues through the
remaining security and rendering checks; errors and timeouts still fail.
A trusted follow-up workflow posts or updates a PDF diagnostic comment with
the detected defect, supported explanation, and student action. It binds a
bounded report artifact to the validation run and current single-PDF PR before
commenting, and never executes files from the student branch.

## Public or private slide delivery

The student chooses exactly one slide-delivery option in the
title-and-abstract pull-request checklist before instructor review. When the
instructor merges that title pull request, the workflow reads the checklist.
A registered student or the instructor can also comment `/slides public` or
`/slides private` while that pull request is open. The title and abstract
remain public either way. Public delivery uses the normal PDF pull request and
website link. Private delivery creates one private repository named
`private-slides-<record-id>` in the organization, invites the registered
student with write access, and marks the public calendar entry as "Private
slide delivery; no public PDF is available." without copying or linking the
PDF.

The `choose-slide-mode.yml` workflow requires an organization administrator
token stored as the Actions secret `ORG_REPO_ADMIN_TOKEN`. The token must be
able to create private repositories in the `stat701` organization and manage
collaborators. Do not use or print the token in logs. The public repository's
`_data/slide_modes.yml` contains only delivery modes, never private slide
content.

For a merged title PR whose setup failed or whose choice was corrected, the
instructor can open **Actions → Choose slide delivery mode → Run workflow**,
use `main`, and enter the title PR number. The retry checks that the instructor
merged the PR and that its author owns the assigned record. Repository files
are installed before the student is invited. Confirm that the repository is
private and that GitHub lists either the registered student as a collaborator
or a pending invitation to that account.

The private repository template asks the student to accept the invitation with
the registered GitHub account, create a branch in the private repository,
upload one root-level `<record-id>.pdf`, open a pull request to that private
repository's `main` branch, and revise on the same branch if needed. Private
repositories currently rely on manual instructor merge policy rather than
enforced branch protection. Private-slide pull requests receive technical PDF
validation for a readable, root-level record-ID PDF that is 25 MiB or smaller,
has 1 to 200 pages, and contains no attachments or JavaScript. They also
receive instructor review; they are not sent to OpenAI.

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
- For a private-slide repository, confirm that the pull request targets that
  repository's `main` branch from a student-created branch, contains one
  root-level record-ID PDF, and passes the private PDF validation workflow.
  Review and merge it manually; this policy is not locked by branch protection
  in the generated private repository.
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

For public slides, deterministic PDF inspection first checks that the file is
safe to open and that every page renders. A separate semantic review then sends
the PDF to OpenAI. The reviewer adopts the perspective of a statistically
literate first-year statistics PhD student: comfortable with graduate
textbooks and high-quality papers, but not a specialist in the speaker's area.
Feedback is brief and concentrates on whether the presentation is accessible,
coherent, visually usable, and valuable to that audience, especially calling
out particularly confusing slides or screens overwhelmed by mathematics. It
does not certify factual or mathematical correctness, research ownership,
novelty, or presentation delivery. Private-slide pull requests use only the
technical PDF check and instructor review.

All submissions and pull-request discussions in this public repository are
public, and titles/abstracts plus public-slide PDFs are sent to OpenAI for
these reviews. Students must not submit confidential, sensitive, private, or
restricted material to the public repository or to OpenAI-reviewed workflows.

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
