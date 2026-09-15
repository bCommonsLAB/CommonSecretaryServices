# Template `bcoop-heft-120`

Jinja2-Partials und Druck-CSS für das b*coop Projektheft, 120 × 120 mm, randlos.
Gerendert von `src/processors/booklet/render.py` mit WeasyPrint.

| Datei | Seite |
|---|---|
| `base.html` | Rahmen, erzeugt je Thema die CSS-Klassen aus `tokens.py` |
| `print.css` | Maße, Schrift, Layout aller Seitentypen |
| `cover.html` | Umschlag |
| `text/default.html`, `text/intro.html`, `text/outro.html`, `text/impressum.html` | Textseiten |
| `divider.html` | Zwischenblatt |
| `project.html` | Projektseite nach der Figma-Schablone |
| `blank.html` | Leerseite |
| `back.html` | Rückseite |
| `fonts/` | Jost Regular und Bold, SIL Open Font License (`OFL.txt`), Platzhalter für Ageo |

Ein neues Partial ist eine Datei. Der Seitentyp `text` wählt `text/<template>.html`,
fehlt die Datei, gilt `text/default.html`.

Schrift tauschen: TTF-Dateien nach `fonts/` legen und die beiden `@font-face`-Regeln
in `print.css` anpassen. WeasyPrint bettet die Schrift als Subset ein.
