---
name: visualize
description: Chart JSON, CSV or XML data in a native window with fosset, and look at the charts yourself. Use when a task produces or inspects results worth seeing as charts, such as SQL query results, usage or metrics reports, benchmark and test timings, cost breakdowns, log aggregates, API responses with many records, or a comparison of options for a decision.
---

# Visualize data with fosset

The `visualize` tool from the fosset MCP server opens a chart window for the user and returns a numeric digest of every chart plus PNGs of the first few, so you and the user look at the same charts. It runs locally and makes no network calls of its own; what it returns to you is part of this session, like any other tool result.

## When to use it

- Results with more than a handful of rows or numbers: query output, metrics, timings, costs, counts per category, anything over time.
- Decisions: when comparing options (architectures, libraries, approaches, configs), write each option as a row with numeric scores or measurements per criterion, then chart it.
- Not for three numbers or fewer. Just state them.
- Reach for this before writing a plotting script. One call replaces reading the data, writing the script, running and fixing it, and opening the image. Write a script only when the user needs something fosset doesn't draw, like a pie, a map, two y axes or annotations.
- When the user invokes this skill with a file path, visualize that file.

## How to call it

1. If the data is already in a file, pass its absolute `path`.
2. If you have small results in context (under 100k characters), pass them as `data`: JSON (a list of objects with the same keys works best) or CSV. For anything bigger, write a file first.
3. The first time, leave `charts` empty unless the user asked for something specific. fosset picks sensible charts on its own.
4. If the picks miss what the user asked about, call again with `charts`. Each pick is `{kind, x, y, color, title}`:
   - `line`: x is a datetime or number column, y is one number column or empty to count rows, color is an optional category column.
   - `bar`: x is a category column, y is one number column or empty to count rows.
   - `scatter`: x and y are number columns.
   - `hist`: x is a number column.
   - `kpi`: y is 1 to 12 number columns, only for single row data.

   Use column names exactly as the digest lists them, with the kind it lists. A pick that doesn't fit gets dropped, and the result says why. Titles are short and in sentence case, like "Orders over time by status", and in the language the user works in. fosset's own picks have English titles, so when the user or their audience works in another language, pass your own picks with titles in that language, from the first call if you already know the columns. Don't put a time unit in titles; fosset picks the bucket.
5. Pass `labels` to give columns readable names with units, like `{"column": "mrr_eur", "label": "MRR (€)"}`.
6. Pass `show: false` to render without opening a window, for example to check the charts before showing the user.
7. Numbers follow the user's preference (see below), or their system's region. Pass `numbers`, like `"1.234,5"` or `"1,234.5"`, to override it for one call. The same setting reads numbers written out for people, like `"21.985.979 ₺"` or `"%44"`, so you don't need to clean them up first.

## Preferences

fosset reads `~/.config/fosset/config.toml`. When the user states a lasting preference, like "always write numbers the Turkish way", write it there once instead of passing it on every call:

```toml
[display]
numbers = "1.234,5"   # or "1,234.5". Leave it out to follow the system region
```

Leave the `[llm]` section alone; it's for the command line tool on its own, not this plugin. A broken value makes the tool return an error that names the file, so fix it there.

## After the call

Read the digest and look at the images, then tell the user the 2 to 4 things that stand out: trends, outliers, the biggest contributors, anything that answers their question. Quote the digest's numbers instead of estimating from the picture. If the result says the window writes numbers like 1.234,5, write them that way too. Keep it short; the user has the window.
