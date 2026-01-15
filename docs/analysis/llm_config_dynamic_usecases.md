# Analyse: `/llm-config` dynamisch statt hardcoded

## Problem
Die Dashboard-Seite `src/dashboard/templates/llm_config.html` rendert die Use-Case-Konfiguration aktuell **hardcoded**
(Transcription, Image2Text, OCR PDF, Chat Completion). Zusätzlich ist im JS eine feste Liste `useCases = [...]` hinterlegt.
Dadurch erscheinen neue Use-Cases (z.B. `transformer_xxl`) **nicht automatisch**, obwohl Backend/DB sie bereits kennen.

## Ziel
Use-Case-Konfiguration soll dynamisch werden:
- Neue Use-Cases sollen ohne Template-Änderung in der UI auftauchen.
- Provider/Model-Auswahl pro Use-Case soll weiterhin funktionieren (AJAX Model-Laden, Speichern via API).

## Varianten
### Variante A (empfohlen): Enum-gesteuert
- Backend liefert `all_use_cases = [uc.value for uc in UseCase]`
- Template rendert Schleife über `all_use_cases`
- JS nutzt dieselbe Liste (aus Jinja `tojson`)

**Pro:** robust, keine DB-Abhängigkeit, neue Use-Cases erscheinen automatisch.  
**Contra:** UI zeigt evtl. Use-Cases, die selten genutzt werden.

### Variante B: DB-gesteuert
- Use-Cases nur aus MongoDB `llm_use_case_config` bzw. config manager.

**Pro:** UI ist „clean“.  
**Contra:** Neue Use-Cases sind unsichtbar, bis initial angelegt.

### Variante C: Hybrid
- Enum-Liste als Soll + DB als Ist; UI markiert fehlende Konfiguration.

**Pro:** beste UX.  
**Contra:** mehr Aufwand.

## Entscheidung
Wir implementieren Variante A, weil sie am wenigsten fehleranfällig ist und „automatisch sichtbar“ garantiert.






