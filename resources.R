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

# Emit one native-listing item per resource (contents: resources-items.yml).
# Facets (type, languages, topics) all become categories so the native
# filter UI covers them; undated entries omit `date` and sort last.
write_listing_items <- function(resources, path) {
  items <- lapply(seq_len(nrow(resources)), function(index) {
    row <- resources[index, ]
    categories <- unique(c(row$type, split_values(row$language), split_values(row$category)))
    categories <- categories[!is.na(categories) & nzchar(categories)]
    item <- list(
      title = row$title,
      description = row$description,
      link = row$link,
      categories = as.list(categories)
    )
    date <- as_catalog_date(row$date)
    if (!is.na(date)) {
      item$date <- format(date, "%Y-%m-%d")
      # Milliseconds since epoch for the native date sort (List.js reads
      # the data-listing-date-sort attribute the template emits for it)
      item$datesort <- sprintf("%.0f", as.numeric(date) * 86400000)
    }
    item
  })
  writeLines(yaml::as.yaml(items), path)
  invisible(path)
}
