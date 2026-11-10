# ── Parse resources.txt (--- delimited YAML blocks) ─────────────────────
parse_resources_md <- function(path) {
  raw <- readLines(path, encoding = "UTF-8")
  sep_idx <- which(raw == "---")
  if (length(sep_idx) < 2) {
    return(tibble::tibble())
  }

  records <- vector("list", floor(length(sep_idx) / 2))
  for (i in seq_len(floor(length(sep_idx) / 2))) {
    start <- sep_idx[2 * i - 1] + 1L
    end <- sep_idx[2 * i] - 1L
    if (start > end) {
      next
    }
    parsed <- tryCatch(
      yaml::yaml.load(paste(raw[start:end], collapse = "\n")),
      error = function(e) NULL
    )
    if (!is.null(parsed)) records[[i]] <- parsed
  }
  records <- Filter(Negate(is.null), records)

  dplyr::bind_rows(lapply(records, function(record) {
    tibble::tibble(
      type = as.character(record$type %||% ""),
      title = as.character(record$title %||% ""),
      link = as.character(record$link %||% ""),
      language = as.character(record$language %||% ""),
      category = as.character(record$category %||% ""),
      description = as.character(record$description %||% ""),
      date = as.character(record$date %||% "")
    )
  }))
}

# "YYYY[-MM[-DD]]" -> Date, NA when unparseable; month-precision dates anchor on the 1st
as_catalog_date <- function(date_str) {
  if (is.na(date_str) || date_str == "") {
    return(as.Date(NA))
  }
  suppressWarnings(as.Date(
    sub("^(\\d{4}-\\d{1,2})$", "\\1-01", trimws(date_str)),
    format = "%Y-%m-%d"
  ))
}

split_values <- function(x) {
  if (is.na(x) || x == "") {
    return(character(0))
  }
  parts <- trimws(strsplit(x, ";", fixed = TRUE)[[1]])
  parts[nzchar(parts)]
}

# Liveness data written by scripts/link_health.py (--json). Missing file is
# normal (the check runs monthly in CI and a fresh clone has no data yet):
# every entry then reports state "unknown" and the UI shows no banner.
read_link_health <- function(path) {
  if (!file.exists(path)) {
    return(list())
  }
  parsed <- tryCatch(
    jsonlite::fromJSON(path, simplifyVector = FALSE),
    error = function(e) NULL
  )
  entries <- parsed$entries
  if (is.null(entries)) list() else entries
}

# One index entry per resource, emitted as JSON for index.qmd to inline in the
# page. Facets stay separate (type, languages, topics) so the browser can render
# one control per facet instead of a single flat category list. Undated entries
# emit `date: null` and sort last.
catalog_index_json <- function(
  resources,
  health_path = "scripts/reports/link-health.json"
) {
  health <- read_link_health(health_path)
  items <- lapply(seq_len(nrow(resources)), function(index) {
    row <- resources[index, ]
    entry <- health[[row$link]]
    date <- as_catalog_date(row$date)
    list(
      title = row$title,
      description = row$description,
      url = row$link,
      type = row$type,
      languages = I(split_values(row$language)),
      topics = I(split_values(row$category)),
      date = if (is.na(date)) NULL else format(date, "%Y-%m-%d"),
      # Raw value from resources.txt, so month-precision dates display as
      # "2021-04" instead of the first-of-month anchor used for sorting.
      datetext = row$date,
      status = if (is.null(entry) || is.null(entry$state)) {
        "unknown"
      } else {
        entry$state
      },
      checked = if (is.null(entry) || is.null(entry$checked_at)) {
        NULL
      } else {
        substr(entry$checked_at, 1, 10)
      }
    )
  })
  json <- as.character(jsonlite::toJSON(
    items,
    auto_unbox = TRUE,
    null = "null"
  ))
  # Scraped descriptions are untrusted: a literal "</script>" would end the
  # inline tag early. "<\/" is the JSON escape for the same character and is
  # the only sequence that can close it.
  gsub("</", "<\\/", json, fixed = TRUE)
}
