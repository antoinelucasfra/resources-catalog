# Contributing to the Resources Catalog

The catalog at [antoinelucasfra.github.io/resources-catalog](https://antoinelucasfra.github.io/resources-catalog/) is a curated list of data science resources for R, Python, and beyond.

There are two ways to add a resource:

- **Suggest it**: use the ["Suggest" link](https://github.com/antoinelucasfra/resources-catalog/issues/new?template=suggest-resource.yml) in the site navbar, no fork or PR needed (see [Suggesting a resource](#suggesting-a-resource))
- **PR path**: fork the repo, edit `resources.txt`, open a pull request (see [Contributing via PR](#contributing-via-pr))

---

## Field Reference

Every entry in `resources.txt` is a YAML block with **6 required fields**:

```yaml
---
title: "Mastering Shiny"
type: "Book"
link: "https://mastering-shiny.org/"
language: "R"
category: "Shiny;Web Development"
description: "The online version of Mastering Shiny, a book that teaches you to build production-quality Shiny apps."
---
```

| Field | Required | Description | Example |
|---|---|---|---|
| `title` | yes | Display name of the resource | `"Mastering Shiny"` |
| `type` | yes | Resource classification: see valid values below | `"Book"` |
| `link` | yes | Full URL | `"https://mastering-shiny.org/"` |
| `language` | yes | Programming language(s): use `;` for multiple | `"R"` or `"R;Python"` |
| `category` | yes | Topical tags: use `;` for multiple, no spaces around `;` | `"Shiny;Web Development"` |
| `description` | yes | One or two sentences describing the resource (max 300 chars) | `"The online version of ..."` |

### Valid `type` values

`Blog` · `Book` · `Website` · `Package` · `Video` · `Paper` · `Course` · `Community` · `Newsletter` · `Conference` · `Forum` · `Journal` · `Repository` · `App` · `Cheatsheet` · `Documentation` · `Gallery` · `Game` · `Guide` · `Magazine` · `Platform` · `Slides` · `Social` · `Tool` · `Tutorial` · `Workshop`

### Valid `language` values

`R` · `Python` · `Other` · `French` · `JavaScript` · `Julia` · or a combination like `R;Python`

### `category` conventions

- Use existing category tags when possible (check the catalog category filter for current tags)
- Separate multiple tags with `;` and no surrounding spaces: `"Statistics;Mixed Models;GLMM"`
- Tags are case-sensitive as written in the file: use title case

### Tag vocabulary

The canonical topic list lives in `scripts/tags.toml` under `[topics]`: each entry is a topic name followed by the raw tag spellings that merge onto it. `category` values that aren't a topic name or a listed alias are invented tags, and CI's `scripts/lint.py` rejects them, so don't make up a new tag inline in a PR.

To propose a new topic (or a new alias for an existing one), open a PR that edits `scripts/tags.toml` alongside the resource entries that need it, and make sure `uv run python scripts/lint.py` passes. A new topic should cover more than one or two entries; smaller clusters belong as an alias on an existing topic instead.

`General` is the fallback tag for entries that don't fit anywhere else yet. Prefer reusing an existing alias over adding `General` or inventing a new topic, and when scoring or auto-tagging new entries, check `scripts/tags.toml` first.

---

## Suggesting a resource

Visitors don't need to fork the repo or write YAML. Clicking **Suggest** in the site navbar opens a GitHub issue form; filling it in and submitting triggers `.github/workflows/suggest.yml`, which runs `scripts/issue_to_pr.py` to validate the submission, fetch a real description for the URL, and open a pull request with the new entry appended to `resources.txt`. A maintainer reviews and merges it like any other PR.

Pick a `type` from the dropdown, the resource's programming language(s), and at least one `category` from the checkboxes: both are checked against the controlled vocabulary in `scripts/lint.py` and `scripts/tags.toml` (see Field Reference and Tag vocabulary above). Suggestions that fail validation, or whose URL is already in the catalog, get a comment explaining why and are closed automatically, no PR is opened.

### Regenerating the listing

`resources-items.yml` is generated from `resources.txt` by the R chunk in `index.qmd`. After editing the source, rebuild the page:

```sh
quarto render
```

### Backfilling descriptions on existing entries

The `backfill.py --mode descriptions` script replaces all auto-generated placeholder descriptions in `resources.txt` with real ones fetched from each URL. **Run this once locally**. It takes a while (~980 entries × ~0.5 s each).

```sh
# From the repo root
cd scripts/
uv sync
RESOURCES_PATH=../resources.txt uv run python backfill.py --mode descriptions
```

Progress is printed to stdout. When it finishes:

```sh
# Review changes before committing
git diff resources.txt

# If happy:
git add resources.txt
git commit -m "chore: backfill resource descriptions"
```

Then push through the normal branch → PR flow.

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

3. **Check your block** against the field reference above: all 6 fields are required, values must be double-quoted, multi-values use `;`
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
