# opds-mirror

Mirror every book from one or more OPDS catalogs (Calibre content server,
Calibre-Web, or any OPDS 1.x catalog) into a folder tree:

```
<output_dir>/<Author>/<Title>/<Title>.<ext>
```

Every format a server offers is downloaded (EPUB, PDF, MOBI, AZW3, ...), unless
you already have that book in that format, in your existing library or from
another server. Re-running only fetches what's new.

## Install

Uses [uv](https://docs.astral.sh/uv/), which also fetches a suitable Python
(3.11 or newer) if you don't have one.

```sh
git clone https://github.com/talonius/opds-mirror
cd opds-mirror
uv sync
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
uv run opds-mirror -c config.toml sync --dry-run   # show what would download
uv run opds-mirror -c config.toml sync             # download
```

It reports what it's doing as it goes: each folder it checks, each book it
downloads or skips, and every few seconds a "still working" line with how far
it has got, for example:

```
INFO step 1 of 2: checking the books you already have
INFO scanning /books/library for the first time; every book gets hashed, which can take a while
INFO   ...library: 2140 books checked, 2140 new or changed hashed (1.9 GB), now in /books/library/Le Guin, Ursula K
INFO step 2 of 2: reading the catalogs and downloading new books
INFO reading catalog calibre (http://calibre.local:8080/opds)
INFO downloading 'The Dispossessed' (epub) from calibre
INFO   saved Ursula K. Le Guin/The Dispossessed/The Dispossessed.epub (412.3 KB)
INFO   ...calibre: 85 catalog pages read, 412 still queued, 3120 books found | this run: 40 downloaded, 3002 skipped, 0 failed
```

The first run is the slow one: it hashes every book in your library folders and
reads every page of every catalog. Later runs only hash new or changed files.

`uv run opds-mirror -c config.toml index` scans the library folders and updates the
duplicate index without downloading anything. `sync` does this itself at the
start of every run, so you only need `index` to check what it finds.

`-v` also logs every request and every file hashed. `-q` prints only warnings
and errors, which suits cron but means silence during a normal run. The exit code is 0
when everything worked and 1 if any file or server failed.

## Run it from cron

```cron
# Every night at 3:15
15 3 * * * /home/brian/.local/bin/uv run --project /home/brian/opds-mirror opds-mirror -q -c /home/brian/opds-mirror/config.toml sync
```

Use absolute paths, since cron doesn't start in your home folder and usually
can't find `uv` on its own (`which uv` shows where it is). After `uv sync`,
`/home/brian/opds-mirror/.venv/bin/opds-mirror` works too, without uv. With `-q`, the
command prints nothing unless something goes wrong, so cron only emails you
about real problems. Set `log_file` in the config for a full record of each
run (it rotates at 5 MB and keeps five old files).

If a run is still going when the next one starts (likely for the first, big
sync), the new one notices the lock in `<output_dir>/.opds-mirror/lock` and
exits straight away. The lock is released automatically if a run crashes.

Exit codes: 0 when everything worked (or another run was already going), 1 when
any file or server failed, 2 for a bad config.

## How it works

The crawler starts at each server's root feed and follows every navigation link
and "next page" link on the same host, visiting each page once. Every book entry
is recognised by its Atom id, so a book listed under "By Newest", "By Author"
and "By Tag" is only processed once. Downloads go to
`<output_dir>/.opds-mirror/tmp/` first and are moved into place only once
complete, so an interrupted run never leaves half a book behind. Feeds that
aren't OPDS (for example a page that wants a login) are skipped quietly.

Every catalog page is fetched on every run, because OPDS has no reliable way to
ask "what changed since last time". Book files are only downloaded once.

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
uv sync
uv run pytest
```
