# STA 701S course website

Landing page for **STA 701S — Statistical Science Graduate Research Seminar**
at Duke University.

The site is deliberately lightweight and ready for GitHub Pages. The main
content lives in `index.html`; site-wide styles live in
`assets/css/main.css`. There is no JavaScript or package installation step.

## Preview locally

From the repository root, run:

```sh
python3 -m http.server 4000
```

Then open <http://localhost:4000>.

## Updating the site

- Edit the evergreen seminar copy and links in `index.html`.
- Keep semester-specific details—organizer, meeting time, room, and speaker
  schedule—in a separate page or repository so the landing page stays current.
- Add new public seminar repositories to the
  [`stat701` organization](https://github.com/stat701); the homepage already
  links to the organization repository list.

GitHub Pages can also render future Markdown pages through Jekyll.
