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
| `assets/bcoop-logo.svg` | b*coop-Logo (Sprechblase, Blau `#6eafc7`, Punkte Rosa `#f3a2af`), Füllfarben als Attribute statt CSS-Klassen, viewBox eng um die Sprechblase. Erscheint auf dem Balken der Projektseiten der Standardmarke und auf dem Umschlag |

Ein neues Partial ist eine Datei. Der Seitentyp `text` wählt `text/<template>.html`,
fehlt die Datei, gilt `text/default.html`.

Schrift tauschen: TTF-Dateien nach `fonts/` legen, in den beiden `@font-face`-Regeln und in
`html { font-family }` von `print.css` den echten Familiennamen der neuen Schrift eintragen.
WeasyPrint bettet die Schrift als Subset ein.

Windows-Entwicklung: WeasyPrint lädt dort mit fremden GTK-DLLs keine `@font-face`-Dateien
und nimmt stumm Systemschriften. Abhilfe: eine Fontconfig-Datei, die diesen Ordner kennt,
und in `print.css` als `font-family` der echte Familienname der Schrift (bereits „Jost“; Fontconfig
ersetzt unbekannte Namen stumm durch Systemschriften, ein Fallback in der Liste hilft nicht):

```xml
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>C:/pfad/zum/repo/templates/booklet/bcoop-heft-120/fonts</dir>
  <dir>C:/Windows/Fonts</dir>
  <cachedir>C:/pfad/zu/einem/cache</cachedir>
</fontconfig>
```

Vor dem Start `FONTCONFIG_FILE` auf diese Datei und `WEASYPRINT_DLL_DIRECTORIES` auf einen
Ordner mit den Pango-DLLs setzen. Im Linux-Container ist das nicht nötig.
