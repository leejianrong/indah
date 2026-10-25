# Gallery policy

This page says what the [demo gallery](gallery.md) lists, what an entry needs, and what
being listed does and does not mean.

## What the gallery lists

There are two kinds of entry.

- **Hosted demos** are the owner's own apps. They run inside the gallery itself, each
  under its own path, and you can open them in the browser with nothing to install.
- **Listed apps** are built with indah but hosted by someone else. They show as a card
  that links out to the app. indah runs nothing for a listed app: the code, the server
  and the data all belong to whoever hosts it.

## Who adds entries

For now the owner adds every entry. Community submissions are not open, and there is no
submission form or pull request flow. If that changes, this page will say so.

## What an entry needs

- a screenshot
- a link to the source
- the indah version it was built with
- a working HTTPS URL
- a short blurb in plain text

## What listing means

Listing is not an endorsement. It is not a promise that the app will stay up, and it is
not a safety review. Nobody has audited a listed app's code or what it does with the
data you give it. Treat it as you would any site you reach through a link.

## How links behave

A link to a listed app opens in a new tab with `rel="noopener noreferrer"`, so the
other site cannot reach back into the gallery. Listed apps are never embedded in an
iframe.

## Links that stop working

A scheduled check of listed links is planned (IND-192) and does not exist yet. The
intention is that an entry whose link stops working is marked "not responding", and
hidden if it stays that way.

## Reporting an entry or asking for removal

To report an entry, or to ask for yours to be removed, open an issue on
[GitHub](https://github.com/leejianrong/indah/issues) with the entry's name and what
the problem is. Please do not include private details in a public issue. Removal
requests from the app's author are honoured.
