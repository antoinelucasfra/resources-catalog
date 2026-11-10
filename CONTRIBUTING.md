# Contributing to the Resources Catalog

The catalog at [antoinelucasfra.github.io/resources-catalog](https://antoinelucasfra.github.io/resources-catalog/) is a curated list of data science resources for R, Python, and beyond.

There are two ways to add a resource:

- **Suggest it**: use the ["Suggest" link](https://github.com/antoinelucasfra/resources-catalog/issues/new?template=suggest-resource.yml) in the site navbar, no fork or PR needed (see [Suggesting a resource](#suggesting-a-resource))
- **PR path**: fork the repo, edit `resources.txt`, open a pull request (see [Contributing via PR](#contributing-via-pr))

---

## Field Reference

Every entry in `resources.txt` is a YAML block. Five fields are required, two are optional:

```yaml
---
title: "Mastering Shiny"
type: "Book"
link: "https://mastering-shiny.org/"
language: "R"
category: "Shiny;Web Development"
description: "The online version of Mastering Shiny, a book that teaches you to build production-quality Shiny apps."
date: "2021-04-01"
---
```

| Field | Required | Description | Example |
|---|---|---|---|
| `title` | yes | Display name of the resource (max 120 chars) | `"Mastering Shiny"` |
| `type` | yes | Resource classification: one of the 12 values below | `"Book"` |
| `link` | yes | Full URL, no tracking parameters | `"https://mastering-shiny.org/"` |
| `language` | yes | Programming language(s) or `Other`: use `;` for multiple | `"R"`, `"R;Python"` |
| `category` | yes | Canonical topic(s): use `;` for multiple, no spaces around `;` | `"Shiny;Web Development"` |
| `description` | recommended | One or two sentences (max 300 chars); the card and search use it | `"The online version of ..."` |
| `date` | optional | ISO date: `YYYY-MM-DD`, `YYYY-MM`, or `YYYY` | `"2021-04-01"` |

Empty optional fields are omitted from the block, not written as `""`.

### Valid `type` values

`Blog` · `Book` · `Community` · `Course` · `Documentation` · `Other` · `Package` · `Paper` · `Repository` · `Tool` · `Video` · `Website`

Type describes the kind of resource, never where it is hosted: a book on GitHub is a `Book`, not a `Repository`.

### Valid `language` values

`R` · `Python` · `Other` · `French` · `JavaScript` · `Julia` · or a combination like `R;Python`

`Other` means the resource is not tied to a programming language (most websites, books, and papers). `French` marks French-language content and can be combined with a programming language.

### `category` conventions

- Only use values from the canonical topic list (see below); anything else fails CI
- Separate multiple topics with `;` and no surrounding spaces: `"Statistics;Bayesian"`
- `General` is the fallback for entries that fit nowhere else; prefer a real topic

### Topic vocabulary

`scripts/tags.toml` holds the whole vocabulary as a flat `topics = [...]` array. There are no aliases and no per-entry inventions: `scripts/lint.py` rejects any `category` value that is not in that array, so the catalog filter, the [topics page](https://antoinelucasfra.github.io/resources-catalog/topics.html), and CI all read the same values.

To propose a new topic, open a PR that adds it to `scripts/tags.toml` and re-tags the entries that need it (at least a handful, otherwise the cluster belongs under an existing topic). Run `uv run python lint.py` from `scripts/` before pushing.

---

## Suggesting a resource

Visitors don't need to fork the repo or write YAML. Clicking **Suggest** in the site navbar opens a GitHub issue form; filling it in and submitting triggers `.github/workflows/suggest.yml`, which runs `scripts/issue_to_pr.py` to validate the submission, fetch a real description for the URL, and open a pull request with the new entry appended to `resources.txt`. A maintainer reviews and merges it like any other PR.

Pick a `type` from the dropdown, the resource's programming language(s), and at least one `category` from the checkboxes: both are checked against the controlled vocabulary in `scripts/lint.py` and `scripts/tags.toml` (see Field Reference and Topic vocabulary above). The workflow also checks the URL is reachable and refuses to open a PR for a link that returns 404 or fails to resolve. Suggestions that fail validation, or whose URL is already in the catalog, get a comment explaining why and are closed automatically, no PR is opened.

### Regenerating the listing

The catalog data is generated from `resources.txt` by the R chunk in `index.qmd` and inlined in the page, then rendered in the browser by `assets/js/catalog.js`. After editing the source, rebuild the page:

```sh
quarto render
```

### Backfilling and normalizing the data

Two scripts keep `resources.txt` in shape. Both are safe to re-run.

`normalize.py` does the offline half (no HTTP): URL cleanup and tracking-parameter stripping, duplicate-URL merging, `type` remap, facet de-duplication, description cleanup, date validation.

`backfill.py` does the network half: filling missing or broken descriptions and missing dates from the linked page.

```sh
cd scripts/
uv sync
uv run python normalize.py            # dry run: report only
uv run python normalize.py --apply    # rewrite resources.txt
RESOURCES_PATH=../resources.txt uv run python backfill.py --mode both
RESOURCES_PATH=../resources.txt uv run python backfill.py --mode descriptions --force --urls URL1 URL2
uv run python lint.py --strict        # taxonomy + hygiene gate
```

Review `git diff resources.txt` before committing: the file is the product, and a silent rewrite is worse than a warning.

---

## Contributing via PR

If you want to suggest a resource and you are not the repo owner:

1. **Fork** the repository on GitHub
2. **Edit** `resources.txt`: add your block at the end of the file, following the exact format:

```yaml
---
title: "Your Resource Title"
type: "Blog"
link: "https://example.com/resource"
language: "R"
category: "Statistics;Data Science"
description: "A one-sentence description of what this resource is and who it is for."
---
```

3. **Check your block** against the field reference above: five fields are required, values must be double-quoted, multi-values use `;`
4. **Run the checks** (from `scripts/`): `uv run python lint.py` and `uv run python normalize.py` (dry run reports what it would tidy)
4. **Open a pull request** against `main` with a short description of what you are adding and why

Rules:
- One resource per PR is preferred for easy review
- The `description` field should be a genuine human-written sentence, not a template
- Do not hand-edit files in `docs/`. They are generated by `quarto render` and deployed by CI; the directory is not committed

---

## What NOT to do

- Never hand-edit `docs/`. It is generated on every `quarto render` and deployed by CI, so hand edits are never committed
- Never hardcode credentials, tokens, or email addresses in source files
- Never commit `.env` files or any file containing secrets
- Never run `git add .` without reviewing staged changes first
