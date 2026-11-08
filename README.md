# opds-mirror

Mirror every book from one or more OPDS catalogs (Calibre content server,
Calibre-Web, or any OPDS 1.x catalog) into a folder tree:

```
<output_dir>/<Author>/<Title>/<Title>.<ext>
```

Every format a server offers is downloaded (EPUB, PDF, MOBI, AZW3, ...), unless
you already have that book in that format, in your existing library or from
another server. Re-running only fetches what's new.

> Status: step 2 of 3. Crawling, downloading and duplicate detection work.
> Cron hardening (lock file, log file) is next.

## Install

Needs Python 3.11 or newer.

```sh
git clone https://github.com/talonius/opds-mirror
cd opds-mirror
python -m venv .venv
.venv/bin/pip install .
```

## Configure

Copy `config.example.toml` to `config.toml` and edit it. List one `[[servers]]`
block per server. Both Calibre and Calibre-Web serve their catalog at `/opds`:

```toml
output_dir = "~/Books/opds-mirror"

[[servers]]
name = "calibre"
url = "http://calibre.local:8080/opds"

[[servers]]
name = "calibre-web"
url = "http://calibre-web.local:8083/opds"
```

Add `library_dirs` to point at folders of books you already have (a Calibre
library folder works well). Books found there are never downloaded again:

```toml
library_dirs = ["~/Calibre Library", "/mnt/nas/ebooks"]
```

A Calibre content server with several libraries needs one block per library,
with `?library_id=<library name>` on the end of the URL.

## Run

```sh
.venv/bin/opds-mirror -c config.toml sync --dry-run   # show what would download
.venv/bin/opds-mirror -c config.toml sync             # download
```

`opds-mirror -c config.toml index` scans the library folders and updates the
duplicate index without downloading anything. `sync` does this itself at the
start of every run, so you only need `index` to check what it finds.

`-v` logs every request, `-q` logs only warnings and errors. The exit code is 0
when everything worked and 1 if any file or server failed.

## How it works

The crawler starts at each server's root feed and follows every navigation link
and "next page" link on the same host, visiting each page once. Every book entry
is recognised by its Atom id, so a book listed under "By Newest", "By Author"
and "By Tag" is only processed once. Downloads go to
`<output_dir>/.opds-mirror/tmp/` first and are moved into place only once
complete, so an interrupted run never leaves half a book behind.

## Duplicate detection

Before and after each download, the book is checked against an index of every
file in your `library_dirs` and in the mirror itself
(`<output_dir>/.opds-mirror/index.sqlite`; set `index_path` to move it).

A file is a duplicate when the **same format** already exists with:

- the same **ISBN** (from the catalog, or read from inside EPUB, MOBI and AZW3
  files), or
- the same **author and title**, ignoring case, accents, punctuation, a leading
  "The/A/An", and author order ("Doe, Jane & John Roe" matches "John Roe & Jane
  Doe"). For files with no readable metadata, the author and title come from the
  `Author/Title/` folder names, as in a Calibre library.

A file with exactly the same contents (**SHA-256 hash**) is a duplicate whatever
its format or name.

The ISBN and author+title checks happen before downloading, using the catalog's
own listing, so known books aren't fetched at all. Calibre's feed doesn't include
ISBNs, so for Calibre the ISBN check happens after download, from inside the file.
Duplicates found after download are deleted.

So with an EPUB of a book in your library, the mirror still downloads its PDF.
When a second server offers a new format of a book already in the mirror, the
file goes into the existing folder.

Every download link handled is remembered, so a duplicate isn't downloaded and
thrown away again on every run. After removing books from your library, run
`sync --recheck` to look at those links again.

Library files are only re-hashed when their size or modification time changes,
so after the first scan this is quick.

## Development

```sh
pip install -e '.[dev]'
pytest
```
