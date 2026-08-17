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
- See [CONTRIBUTING.md](CONTRIBUTING.md) for the browser-only student process.

## Validate submissions locally

Run the dependency-free unit tests with:

```sh
python3 -m unittest discover -s tests -v
```

The GitHub Actions submission check also validates PDF structure and renders
every page with `qpdf` and Poppler before a slides pull request can be merged.

## Maintainer merge checklist

- Confirm that **Validate submission** passed on the current pull-request head.
- Confirm that the pull-request author is the student assigned to the record
  ID. The repository validates the record and file path, but GitHub accounts
  are not automatically mapped to student identities.
- Review any requested human escalation, then squash-merge the pull request.

## Optional AI review

The **Review title and abstract (AI)** workflow is advisory and must be started
manually by a maintainer for a specific pull-request number. It reads only the
submitted title and abstract, uses a fixed rubric and strict structured output,
posts one clearly labeled comment, and never approves or merges a pull request.
API errors and uncertain results request human review.

To enable it:

1. Create a dedicated OpenAI project API key with an appropriate spending
   limit.
2. In this repository, open **Settings → Secrets and variables → Actions → New
   repository secret** and create `OPENAI_API_KEY`. Never commit the key, put it
   in a pull request, or paste it into chat.
3. After a title-and-abstract pull request passes deterministic validation,
   open **Actions → Review title and abstract (AI) → Run workflow**, leave the
   branch as `main`, and enter the pull-request number.

The default model is `gpt-5.6-terra`. To choose another compatible Responses
API model, create the repository variable `OPENAI_REVIEW_MODEL`; no variable is
needed for the default.

GitHub Pages can also render future Markdown pages through Jekyll.
