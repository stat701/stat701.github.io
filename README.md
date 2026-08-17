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
and Poppler before a slides pull request can be merged. PDFs are not sent to
OpenAI; the deterministic parser and renderer are the required technical gate.

## Maintainer merge checklist

- Confirm that **Validate submission** passed on the current pull-request head.
- Confirm that the pull-request author is the student assigned to the record
  ID. The repository validates the record and file path, but GitHub accounts
  are not automatically mapped to student identities.
- For a title-and-abstract pull request, keep it open until the automatic AI
  comment appears or the AI workflow explicitly requests human review.
- Review any requested human escalation, then squash-merge the pull request.

## Automatic AI review

After **Validate submission** succeeds, the **Review title and abstract (AI)**
workflow runs automatically for a title-and-abstract pull request. It reads
only the submitted title and abstract together with the immutable year in
program, uses a fixed year-aware rubric and strict structured output, posts one
clearly labeled comment, and never approves or merges a pull request. PDF and
ordinary maintainer pull requests are skipped. API errors and uncertain results
request human review. Manual dispatch remains available as a maintainer
fallback.

Once a successful review comment is recorded, the workflow remembers the exact
Git blob it reviewed. Normal re-runs for that file version do not make another
OpenAI request. A substantive edit creates a new blob and receives fresh
feedback. The workflow queue serializes review runs, though no external API can
promise transactional exactly-once billing if a runner is interrupted between
the API response and recording its GitHub comment.

To enable it:

1. Create a dedicated OpenAI project API key with an appropriate spending
   limit.
2. In this repository, open **Settings → Secrets and variables → Actions → New
   repository secret** and create `OPENAI_API_KEY`. Never commit the key, put it
   in a pull request, or paste it into chat.
3. No routine action is needed. After deterministic validation succeeds, the
   trusted default-branch workflow reviews an eligible metadata submission.
   To retry a failed service call manually, open **Actions → Review title and
   abstract (AI) → Run workflow**, leave the branch as `main`, and enter the
   pull-request number.

The default model is `gpt-5.6-terra`. To choose another compatible Responses
API model, create the repository variable `OPENAI_REVIEW_MODEL`; no variable is
needed for the default. Keep a conservative project spending limit on the API
key because the repository accepts public fork pull requests.

GitHub Pages can also render future Markdown pages through Jekyll.
