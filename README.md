# STA 701S course website

Landing page for **STA 701S — Statistical Science Graduate Research Seminar**
at Duke University.

The site is deliberately lightweight and can be published with GitHub Pages.
The main content lives in `index.html`; site-wide styles live in
`assets/css/main.css`. There is no JavaScript or package installation step.

## Preview locally

From the repository root, run:

```sh
python3 -m http.server 4000
```

Then open <http://localhost:4000>.

## Updating the site

- Edit the seminar copy and semester calendar in `index.html`.
- Each meeting uses a semantic `<time>` element and an ordered speaker list;
  preserve the supplied speaker order when updating the calendar.
- Add talk titles, meeting time, and room only after those details are
  confirmed for the semester.

GitHub Pages can also render future Markdown pages through Jekyll.
