# Resources Catalog

A curated and searchable catalog of 1,000+ data science resources for R, Python, and beyond. Filter by type, topic, language, and link status.

**Browse it live:** [antoinelucasfra.github.io/resources-catalog](https://antoinelucasfra.github.io/resources-catalog/)

Part of [antoinelucasfra.github.io](https://antoinelucasfra.github.io) — extracted from the portfolio site into its own project so curation and portfolio content can evolve independently.

## How it works

- `resources.txt` is the source of truth: one YAML block per resource (`title`, `type`, `link`, `language`, `category`, plus optional `description` and `date`)
- Vocabularies are closed lists in code: 12 `type` values in `scripts/utils.py`, 6 `language` values, and 38 `category` topics in `scripts/tags.toml`; `scripts/lint.py` rejects anything else
- `resources.R` parses the file and `index.qmd` inlines it as JSON at render time (nothing generated is committed)
- `assets/js/catalog.js` renders that index client-side: type/topic/language facets, link-status chips, deep-linkable filters, grid/list views, and a copy-ready citation per entry — no framework, no build step
- `topics.qmd` lists the same topics, types, and languages with live entry counts, so the page and the filters cannot disagree
- CI (`.github/workflows/publish.yml`) renders the site and deploys it to GitHub Pages on every push to `main`
- A monthly job (`.github/workflows/link-health.yml`) checks every link for liveness, opens a single "Link health report" issue, and commits `scripts/reports/link-health.json` so the catalog can show verified/dead/unknown link status; retiring a dead link is a manual decision via `scripts/retire.py --link <url>`

## Adding a resource

Use the **Suggest** tab in the site navbar to open a GitHub issue form; a bot validates the submission and opens a pull request automatically. To add a resource directly, edit `resources.txt` and open a pull request. Each entry is a small YAML block:

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full field reference, the suggestion workflow, and backfilling tools.

## Keeping the data clean

All scripts run from `scripts/` with `uv`:

| Command | What it does |
|---|---|
| `uv run python lint.py [--strict]` | Taxonomy gate: closed-list `type`/`language`/`category`, duplicate links, tracking parameters, description hygiene |
| `uv run python normalize.py [--apply]` | Offline cleanup: URL normalization, duplicate-URL merging, `type` remap, facet de-duplication, date validation (dry run by default) |
| `uv run python backfill.py --mode both` | Network fill: descriptions and dates from the linked pages |
| `uv run python link_health.py --url URL` | Check one URL; `--json` writes the snapshot the catalog reads |
| `uv run python retire.py --link URL` | Remove a retired resource |

## Local development

Requirements: R (4.4+), Quarto (1.9+), and R packages `here`, `yaml`, `tibble`, `dplyr`, `rlang`, `jsonlite`.

```sh
quarto render   # writes docs/ (gitignored)
```

See CONTRIBUTING.md for the field reference, the suggestion workflow, and the maintenance scripts.

## License

Site content: [CC BY NC SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0).
