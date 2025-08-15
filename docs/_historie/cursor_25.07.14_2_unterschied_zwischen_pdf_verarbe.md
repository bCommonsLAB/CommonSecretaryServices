# Unterschied zwischen PDF-Verarbeitungsmethoden
_Exported on 7/14/2025 at 17:37:32 GMT+2 from Cursor (1.2.4)_

---

**User**



Wenn ich dasselbe PDF einmal mit normaler Methode transformiere, dann ist hier im Result der ExtractedText und images_archive_data  Parameter gefüllt. Wenn ich es über LLM Methode transformiere, dann sind diese Felder@imageocr_processor.py  leer. Auch ImageArchiveData und ImageArchiveFileName ist leer. Wo liegt der Unterschied zwischen beiden Methoden? Bitte das Tippen der Bilder und das Archive nicht doppelt programmieren, sondern immer dieselben Komponenten wählen.
PDFProcessingResult(metadata=PDFMetadata(file_name='temp_c2a4de50-1238-49c4-bb81-ce8eb85575a1.pdf', file_size=71472, page_count=2, format='pdf', process_dir='cache\\pdf\\temp\\pdf\\4461b7909443786f1fc0d982fa1ebd41\\llm', image_paths=[], preview_paths=[], preview_zip=None, text_paths=['/api/pdf/text-content/cache/pdf/temp/pdf/4461b7909443786f1fc0d982fa1ebd41/llm/page_001.txt', '/api/pdf/text-content/cache/pdf/temp/pdf/4461b7909443786f1fc0d982fa1ebd41/llm/page_002.txt'], original_text_paths=['cache\\pdf\\temp\\pdf\\4461b7909443786f1fc0d982fa1ebd41\\llm\\page_001.txt', 'cache\\pdf\\temp\\pdf\\4461b7909443786f1fc0d982fa1ebd41\\llm\\page_002.txt'], text_contents=[(1, '# Musterpraktiken aus "Frei, Fair und Lebendig"\n\nHier ist eine Tabelle, die die 30 Musterpraktiken aus dem Buch "Frei, Fair und Lebendig" den kapital- oder machtgetriebenen Praktiken gegenüberstellt:\n\n| Musterpraktik des Commoning               | Kapital- oder machtgetriebene Praktik                     |\n|-------------------------------------------|----------------------------------------------------------|\n| 1. Gemeinsam Werte schaffen                | Individueller Profit über Gemeinschaft stellen            |\n| 2. Ressourcen teilen und pflegen          | Ressourcen privatisieren und ausbeuten                   |\n| 3. Partizipative Entscheidungsfindung     | Autoritäre oder hierarchische Entscheidungen             |\n| 4. Transparenz fördern                     | Intransparenz und Informationskontrolle                  |\n| 5. Wissen offen teilen                     | Wissen monopolisieren, Patente und geistiges Eigentum horten |\n| 6. Soziale Bindungen stärken               | Soziale Isolation und Konkurrenz fördern                  |\n| 7. Vertrauen aufbauen                      | Misstrauen säen, Überwachung einsetzen                    |\n| 8. Nachhaltigkeit priorisieren             | Kurzfristige Gewinne über langfristige Nachhaltigkeit setzen |\n| 9. Gemeinsame Regeln aushandeln           | Einseitige Regelsetzung durch Machtpositionen            |\n| 10. Vielfalt und Inklusion fördern        | Homogenität und Exklusion praktizieren                   |\n| 11. Lokale Autonomie unterstützen          | Zentralisierung von Macht und Kontrolle                   |\n| 12. Gemeinsame Verantwortung übernehmen    | Verantwortung delegieren oder vermeiden                   |\n| 13. Konflikte kooperativ lösen            | Konflikte eskalieren oder unterdrücken                   |\n| 14. Soziale Gerechtigkeit anstreben       | Soziale Ungleichheiten akzeptieren oder vertiefen        |\n| 15. Ökologische Achtsamkeit               | Umweltverschmutzung ignorieren, externe Kosten externalisieren |\n| 16. Gemeinsame Infrastruktur nutzen und pflegen | Infrastruktur privatisieren, Zugang beschränken         |\n| 17. Kollektives Lernen fördern             | Bildung und Wissen elitär halten                          |\n\n![Tabelle der Musterpraktiken](placeholder.jpg)'), (2, '# Wichtige Anforderungen\n\n1. **Kreativität und Innovation kollektiv nutzen**\n   - Innovation durch Wettbewerbsdruck kontrollieren\n\n2. **Zeit und Raum für Reflexion schaffen**\n   - Ständigen Druck und Zeitknappheit erzeugen\n\n3. **Gegenseitige Hilfe und Solidarität**\n   - Individualismus und Selbstinteresse betonen\n\n4. **Flexibilität und Anpassungsfähigkeit**\n   - Rigide Strukturen und Bürokratie aufrechterhalten\n\n5. **Gemeinsame Rituale und Kultur pflegen**\n   - Kulturelle Homogenisierung oder Kommerzialisierung\n\n6. **Grenzen und Ressourcen respektieren**\n   - Grenzen überschreiten, Ressourcen übernutzen\n\n7. **Empowerment und Selbstwirksamkeit**\n   - Abhängigkeiten schaffen, Entmündigung fördern\n\n8. **Offene Kommunikation und Dialog**\n   - Kommunikation kontrollieren, Zensur einsetzen\n\n9. **Gemeinsame Visionen und Ziele entwickeln**\n   - Einzelinteressen priorisieren, Gemeinwohl ignorieren\n\n10. **Soziale Resilienz stärken**\n    - Soziale Systeme anfällig machen durch Ungleichheit\n\n11. **Teilen von Verantwortung und Rollen**\n    - Machtkonzentration in wenigen Händen\n\n12. **Peer-Monitoring und Feedback**\n    - Externe Kontrolle, Überwachung und Misstrauen\n\n13. **Feiern und Anerkennen gemeinsamer Erfolge**\n    - Individuelle Leistungen hervorheben, Gemeinschaftserfolge ignorieren\n\n---\n\nDiese Tabelle illustriert, wie die Musterpraktiken des Commoning auf Kooperation, geteilte Verantwortung und gemeinschaftliche Werte abzielen, während kapital- oder machtgetriebene Praktiken oft durch Konkurrenz, Machtkonzentration und individuelle Profitorientierung gekennzeichnet sind. Durch diese Gegenüberstellung wird deutlich, dass Commoning eine Alternative bietet, die auf Nachhaltigkeit, Inklusion und gemeinschaftliches Wohlergehen fokussiert.')], extraction_method='llm'), extracted_text=None, ocr_text=None, process_id='eac6f1b7-d079-488f-961e-a374512436f7', processed_at='2025-07-14T12:37:04.699852+00:00', images_archive_data=None, images_archive_filename=None)

---

**Cursor**

Ich analysiere das Problem mit den fehlenden Bildern und dem Archiv bei der LLM-Methode. Lass mich zuerst den Code untersuchen, um die Unterschiede zu verstehen.


Jetzt schaue ich mir die spezifischen Unterschiede zwischen den Extraktionsmethoden an:


Jetzt schaue ich mir die native Extraktionsmethode an, um den Unterschied zu verstehen:


Jetzt schaue ich mir an, wo das Bilder-Archiv erstellt wird:


Jetzt habe ich das Problem identifiziert! Lass mich die Unterschiede zwischen den Extraktionsmethoden analysieren:

## Problem-Analyse

Das Problem liegt daran, dass bei der **LLM-Methode** (`EXTRACTION_LLM`) **keine Bilder generiert werden**, während bei der **nativen Methode** (`EXTRACTION_NATIVE`) Bilder generiert werden.

### Unterschiede zwischen den Methoden:

1. **Native Methode** (`EXTRACTION_NATIVE`):
   - Generiert Hauptbilder mit `_generate_main_image()`
   - Fügt Bilder zu `all_image_paths` und `metadata.image_paths` hinzu
   - Bilder werden später für das Archiv verwendet

2. **LLM-Methode** (`EXTRACTION_LLM`):
   - **Generiert KEINE Bilder** - nur Text-Extraktion
   - Keine Bildpfade in `metadata.image_paths`
   - Daher kein Archiv möglich

3. **OCR-Methode** (`EXTRACTION_OCR`):
   - Generiert Bilder für OCR-Verarbeitung
   - Fügt Bilder zu `metadata.image_paths` hinzu

4. **LLM_AND_OCR-Methode** (`EXTRACTION_LLM_AND_OCR`):
   - Generiert Bilder für Tesseract OCR
   - Fügt Bilder zu `metadata.image_paths` hinzu

## Lösung

Ich werde die LLM-Methode so erweitern, dass sie auch Bilder generiert, damit das Archiv erstellt werden kann. Die Bilder werden für die LLM-Verarbeitung benötigt, aber nicht gespeichert. Ich werde die bestehende Bildgenerierung wiederverwenden.


```python
                    if EXTRACTION_LLM in methods_list:
                        # LLM-basierte OCR mit Markdown-Output
                        try:
                            # Generiere Hauptbild für LLM-Verarbeitung und Archiv
                            image_path = self._generate_main_image(page, page_num, extraction_dir)
                            all_image_paths.append(image_path)
                            metadata.image_paths.append(image_path)
                            
                            # Erstelle erweiterten Prompt basierend auf Kontext
                            custom_prompt = None
                            if context:
                                document_type = context.get('document_type')
                                language = context.get('language', 'de')
                                custom_prompt = self.image2text_service.create_enhanced_prompt(
                                    context=context,
                                    document_type=document_type,
                                    language=language
                                )
                            
                            # LLM-OCR für diese Seite
                            llm_text, llm_request = self.image2text_service.extract_text_from_pdf_page(
                                page=page,
                                page_num=page_num,
                                custom_prompt=custom_prompt,
                                logger=self.logger
                            )
                            
                            # LLM-Request zum Tracking hinzufügen
                            self.add_llm_requests([llm_request])
                            
                            # Text speichern
                            text_path = self.save_page_text(text=llm_text, page_num=page_num, process_dir=extraction_dir)
                            
                            # Metadaten aktualisieren
                            text_paths_list = list(metadata.text_paths)
                            text_paths_list.append(str(text_path))
                            
                            text_contents_list = list(metadata.text_contents)
                            text_contents_list.append((page_num + 1, llm_text))
                            
                            metadata = PDFMetadata(
                                file_name=metadata.file_name,
                                file_size=metadata.file_size,
                                page_count=metadata.page_count,
                                format=metadata.format,
                                process_dir=metadata.process_dir,
                                image_paths=metadata.image_paths,
                                preview_paths=metadata.preview_paths,
                                preview_zip=metadata.preview_zip,
                                text_paths=text_paths_list,
                                text_contents=text_contents_list,
                                extraction_method=metadata.extraction_method
                            )
                            
                            # Füge LLM-Text zum Gesamttext hinzu
                            full_text += f"\n--- Seite {page_num+1} ---\n{llm_text}"
                            
                            self.logger.debug(f"LLM-OCR für Seite {page_num+1} abgeschlossen")
                            
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            # Fallback auf native Extraktion
                            page_text_raw = page.get_text()
                            page_text = cast(str, page_text_raw)
                            fallback_text = f"LLM-OCR fehlgeschlagen, Fallback auf native Extraktion:\n\n{page_text}"
                            full_text += f"\n--- Seite {page_num+1} ---\n{fallback_text}"
```

Jetzt muss ich auch die `EXTRACTION_LLM_AND_NATIVE` Methode erweitern, damit sie Bilder generiert:


```python
                    if EXTRACTION_LLM_AND_NATIVE in methods_list:
                        # Kombiniere LLM-OCR mit nativer Text-Extraktion
                        # Native Text-Extraktion
                        page_text_raw = page.get_text()
                        page_text = cast(str, page_text_raw)
                        
                        # Generiere Hauptbild für LLM-Verarbeitung und Archiv
                        image_path = self._generate_main_image(page, page_num, extraction_dir)
                        all_image_paths.append(image_path)
                        metadata.image_paths.append(image_path)
                        
                        # LLM-OCR
                        try:
                            custom_prompt = None
                            if context:
                                document_type = context.get('document_type')
                                language = context.get('language', 'de')
                                custom_prompt = self.image2text_service.create_enhanced_prompt(
                                    context=context,
                                    document_type=document_type,
                                    language=language
                                )
                            
                            llm_text, llm_request = self.image2text_service.extract_text_from_pdf_page(
                                page=page,
                                page_num=page_num,
                                custom_prompt=custom_prompt,
                                logger=self.logger
                            )
                            
                            # LLM-Request zum Tracking hinzufügen
                            self.add_llm_requests([llm_request])
                            
                            # Kombiniere beide Texte
                            combined_text = f"=== Native Text ===\n{page_text}\n\n=== LLM Markdown ===\n{llm_text}"
                            
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            combined_text = f"=== Native Text ===\n{page_text}\n\n=== LLM-OCR Fehler ===\n{str(llm_error)}"
                        
                        # Text speichern
                        text_path = self.save_page_text(text=combined_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Metadaten aktualisieren
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((page_num + 1, combined_text))
                        
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                        # Füge kombinierten Text zum Gesamttext hinzu
                        full_text += f"\n--- Seite {page_num+1} ---\n{combined_text}"
```

Jetzt muss ich auch das Problem mit dem `extracted_text` Feld beheben. Bei der LLM-Methode wird der Text in `full_text` gespeichert, aber das `extracted_text` Feld wird nur gesetzt, wenn `EXTRACTION_NATIVE` oder `EXTRACTION_BOTH` in der Methodenliste ist. Ich muss das erweitern:


Jetzt muss ich die Logik für das `extracted_text` Feld erweitern, damit es auch bei LLM-Methoden gesetzt wird:


```python
                # Erstelle Endergebnis
                result = PDFProcessingResult(
                    metadata=metadata,
                    extracted_text=result_text if (EXTRACTION_NATIVE in methods_list or 
                                                  EXTRACTION_BOTH in methods_list or 
                                                  EXTRACTION_LLM in methods_list or 
                                                  EXTRACTION_LLM_AND_NATIVE in methods_list or 
                                                  EXTRACTION_LLM_AND_OCR in methods_list) else None,
                    ocr_text=ocr_text if EXTRACTION_OCR in methods_list or EXTRACTION_BOTH in methods_list else None,
                    process_id=self.process_id,
                    images_archive_data=images_archive_data,
                    images_archive_filename=images_archive_filename
                )
```

Jetzt muss ich auch die Linter-Fehler beheben, die durch die PyMuPDF-Typen entstehen:


```python
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            # Fallback auf native Extraktion
                            page_text_raw = page.get_text()  # type: ignore
                            page_text = cast(str, page_text_raw)
                            fallback_text = f"LLM-OCR fehlgeschlagen, Fallback auf native Extraktion:\n\n{page_text}"
                            full_text += f"\n--- Seite {page_num+1} ---\n{fallback_text}"
                    
                    if EXTRACTION_LLM_AND_NATIVE in methods_list:
                        # Kombiniere LLM-OCR mit nativer Text-Extraktion
                        # Native Text-Extraktion
                        page_text_raw = page.get_text()  # type: ignore
                        page_text = cast(str, page_text_raw)
```

---

**User**

Aber generiert jede Methode ihre eignen Bilder? können wir diese nicht zentralisieren? Die unterschiedliche Methode bezieht sich ja nur auf die Auswertung. Bilder brauchen wir in response unabhängig von Methode.

---

**Cursor**

Sie haben absolut recht! Das ist eine sehr gute Beobachtung. Die Bildgenerierung sollte zentralisiert werden, da sie unabhängig von der Extraktionsmethode erfolgen sollte. Jede Methode generiert derzeit ihre eigenen Bilder, was zu Code-Duplikation und Inkonsistenz führt.

Lassen Sie mich das refaktorieren, um eine zentrale Bildgenerierung zu implementieren:


```python
                for page_num in range(page_count):
                    page = pdf[page_num]  # Zugriff auf PDF-Seite
                    page_start = time.time()
                    
                    # ZENTRALE BILDGENERIERUNG - unabhängig von der Extraktionsmethode
                    # Generiere Vorschaubilder, falls gewünscht
                    if EXTRACTION_PREVIEW in methods_list or EXTRACTION_PREVIEW_AND_NATIVE in methods_list:
                        # Vorschaubilder generieren
                        preview_path = self._generate_preview_image(page, page_num, extraction_dir)
                        all_preview_paths.append(preview_path)
                        metadata.preview_paths.append(preview_path)
                    
                    # Generiere Hauptbilder für alle Methoden (wird für Archiv und Visualisierung benötigt)
                    image_path = self._generate_main_image(page, page_num, extraction_dir)
                    all_image_paths.append(image_path)
                    metadata.image_paths.append(image_path)
                    
                    # Verarbeite jede gewünschte Extraktionsmethode
                    if EXTRACTION_NATIVE in methods_list or EXTRACTION_PREVIEW_AND_NATIVE in methods_list:
                        # Native Text-Extraktion
                        page_text_raw = page.get_text()  # type: ignore # PyMuPDF Methode
                        page_text = cast(str, page_text_raw)
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                        # Textdaten speichern
                        text_path = self.save_page_text(text=page_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Da PDFMetadata jetzt unveränderlich ist, sammeln wir die Inhalte in temporären Listen
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((int(page_num + 1), str(f"{page_text}")))
                        
                        # Neue PDFMetadata-Instanz erstellen mit aktualisierten text_contents und text_paths
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                    if EXTRACTION_OCR in methods_list:
                        # OCR durchführen - verwende das bereits generierte Hauptbild
                        # OCR mit ImageOCR Processor (nutzt Caching)
                        try:
                            # Verwende den ImageOCR Processor für OCR mit Caching
                            ocr_result = await self.imageocr_processor.process(
                                file_path=str(image_path),  # Verwende das bereits generierte Bild
                                template=None,  # Kein Template für PDF-Seiten
                                context=context,
                                extraction_method="ocr",
                                use_cache=use_cache,  # Cache-Nutzung vom PDF-Processor übernehmen
                                file_hash=None  # Hash wird vom ImageOCR Processor berechnet
                            )
                            
                            if ocr_result.data and ocr_result.data.extracted_text:
                                page_ocr = str(ocr_result.data.extracted_text)
                                
                                # OCR-Text speichern
                                text_path = self.save_page_text(page_ocr, page_num, extraction_dir)
                                
                                # Da PDFMetadata jetzt unveränderlich ist, müssen wir eine neue Instanz erstellen
                                text_paths_list = list(metadata.text_paths)
                                text_paths_list.append(str(text_path))
                                
                                text_contents_list = list(metadata.text_contents)
                                text_contents_list.append((page_num + 1, page_ocr))
                                
                                metadata = PDFMetadata(
                                    file_name=metadata.file_name,
                                    file_size=metadata.file_size,
                                    page_count=metadata.page_count,
                                    format=metadata.format,
                                    process_dir=metadata.process_dir,
                                    image_paths=metadata.image_paths,
                                    preview_paths=metadata.preview_paths,
                                    preview_zip=metadata.preview_zip,
                                    text_paths=text_paths_list,
                                    text_contents=text_contents_list,
                                    extraction_method=metadata.extraction_method
                                )
                                
                                ocr_text += f"\n--- Seite {page_num+1} ---\n{page_ocr}"
                                self.logger.debug(f"OCR für Seite {page_num+1} mit ImageOCR Processor abgeschlossen")
                            else:
                                self.logger.warning(f"Kein OCR-Text für Seite {page_num+1} extrahiert")
                                page_ocr = ""
                                
                        except Exception as ocr_error:
                            self.logger.error(f"Fehler bei OCR für Seite {page_num+1}: {str(ocr_error)}")
                            page_ocr = ""
                    
                    if EXTRACTION_LLM in methods_list:
                        # LLM-basierte OCR mit Markdown-Output
                        try:
                            # Erstelle erweiterten Prompt basierend auf Kontext
                            custom_prompt = None
                            if context:
                                document_type = context.get('document_type')
                                language = context.get('language', 'de')
                                custom_prompt = self.image2text_service.create_enhanced_prompt(
                                    context=context,
                                    document_type=document_type,
                                    language=language
                                )
                            
                            # LLM-OCR für diese Seite
                            llm_text, llm_request = self.image2text_service.extract_text_from_pdf_page(
                                page=page,
                                page_num=page_num,
                                custom_prompt=custom_prompt,
                                logger=self.logger
                            )
                            
                            # LLM-Request zum Tracking hinzufügen
                            self.add_llm_requests([llm_request])
                            
                            # Text speichern
                            text_path = self.save_page_text(text=llm_text, page_num=page_num, process_dir=extraction_dir)
                            
                            # Metadaten aktualisieren
                            text_paths_list = list(metadata.text_paths)
                            text_paths_list.append(str(text_path))
                            
                            text_contents_list = list(metadata.text_contents)
                            text_contents_list.append((page_num + 1, llm_text))
                            
                            metadata = PDFMetadata(
                                file_name=metadata.file_name,
                                file_size=metadata.file_size,
                                page_count=metadata.page_count,
                                format=metadata.format,
                                process_dir=metadata.process_dir,
                                image_paths=metadata.image_paths,
                                preview_paths=metadata.preview_paths,
                                preview_zip=metadata.preview_zip,
                                text_paths=text_paths_list,
                                text_contents=text_contents_list,
                                extraction_method=metadata.extraction_method
                            )
                            
                            # Füge LLM-Text zum Gesamttext hinzu
                            full_text += f"\n--- Seite {page_num+1} ---\n{llm_text}"
                            
                            self.logger.debug(f"LLM-OCR für Seite {page_num+1} abgeschlossen")
                            
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            # Fallback auf native Extraktion
                            page_text_raw = page.get_text()  # type: ignore # PyMuPDF Methode
                            page_text = cast(str, page_text_raw)
                            fallback_text = f"LLM-OCR fehlgeschlagen, Fallback auf native Extraktion:\n\n{page_text}"
                            full_text += f"\n--- Seite {page_num+1} ---\n{fallback_text}"
                    
                    if EXTRACTION_LLM_AND_NATIVE in methods_list:
                        # Kombiniere LLM-OCR mit nativer Text-Extraktion
                        # Native Text-Extraktion
                        page_text_raw = page.get_text()  # type: ignore # PyMuPDF Methode
                        page_text = cast(str, page_text_raw)
                        
                        # LLM-OCR
                        try:
                            custom_prompt = None
                            if context:
                                document_type = context.get('document_type')
                                language = context.get('language', 'de')
                                custom_prompt = self.image2text_service.create_enhanced_prompt(
                                    context=context,
                                    document_type=document_type,
                                    language=language
                                )
                            
                            llm_text, llm_request = self.image2text_service.extract_text_from_pdf_page(
                                page=page,
                                page_num=page_num,
                                custom_prompt=custom_prompt,
                                logger=self.logger
                            )
                            
                            # LLM-Request zum Tracking hinzufügen
                            self.add_llm_requests([llm_request])
                            
                            # Kombiniere beide Texte
                            combined_text = f"=== Native Text ===\n{page_text}\n\n=== LLM Markdown ===\n{llm_text}"
                            
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            combined_text = f"=== Native Text ===\n{page_text}\n\n=== LLM-OCR Fehler ===\n{str(llm_error)}"
                        
                        # Text speichern
                        text_path = self.save_page_text(text=combined_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Metadaten aktualisieren
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((page_num + 1, combined_text))
                        
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                        # Füge kombinierten Text zum Gesamttext hinzu
                        full_text += f"\n--- Seite {page_num+1} ---\n{combined_text}"
                    
                    if EXTRACTION_LLM_AND_OCR in methods_list:
                        # Kombiniere LLM-OCR mit Tesseract OCR
                        llm_text = ""
                        tesseract_text = ""
                        
                        # LLM-OCR
                        try:
                            custom_prompt = None
                            if context:
                                document_type = context.get('document_type')
                                language = context.get('language', 'de')
                                custom_prompt = self.image2text_service.create_enhanced_prompt(
                                    context=context,
                                    document_type=document_type,
                                    language=language
                                )
                            
                            llm_text, llm_request = self.image2text_service.extract_text_from_pdf_page(
                                page=page,
                                page_num=page_num,
                                custom_prompt=custom_prompt,
                                logger=self.logger
                            )
                            
                            # LLM-Request zum Tracking hinzufügen
                            self.add_llm_requests([llm_request])
                            
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            llm_text = f"LLM-OCR Fehler: {str(llm_error)}"
                        
                        # Tesseract OCR - verwende das bereits generierte Hauptbild
                        try:
                            ocr_result = await self.imageocr_processor.process(
                                file_path=str(image_path),  # Verwende das bereits generierte Bild
                                template=None,
                                context=context,
                                extraction_method="ocr",
                                use_cache=use_cache,
                                file_hash=None
                            )
                            
                            if ocr_result.data and ocr_result.data.extracted_text:
                                tesseract_text = str(ocr_result.data.extracted_text)
                            
                        except Exception as ocr_error:
                            self.logger.error(f"Fehler bei Tesseract OCR für Seite {page_num+1}: {str(ocr_error)}")
                            tesseract_text = f"Tesseract OCR Fehler: {str(ocr_error)}"
                        
                        # Kombiniere beide OCR-Ergebnisse
                        combined_ocr_text = f"=== LLM Markdown ===\n{llm_text}\n\n=== Tesseract OCR ===\n{tesseract_text}"
                        
                        # Text speichern
                        text_path = self.save_page_text(text=combined_ocr_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Metadaten aktualisieren
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((page_num + 1, combined_ocr_text))
                        
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                        # Füge kombinierten Text zum OCR-Text hinzu
                        ocr_text += f"\n--- Seite {page_num+1} ---\n{combined_ocr_text}"
                    
                    if EXTRACTION_BOTH in methods_list:
                        # Beide Extraktionsmethoden (native + OCR)
                        # Native Text-Extraktion
                        page_text_raw = page.get_text()  # type: ignore # PyMuPDF Methode
                        page_text = cast(str, page_text_raw)
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                        # Textdaten speichern
                        text_path = self.save_page_text(text=page_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Da PDFMetadata jetzt unveränderlich ist, sammeln wir die Inhalte in temporären Listen
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((int(page_num + 1), str(f"{page_text}")))
                        
                        # Neue PDFMetadata-Instanz erstellen mit aktualisierten text_contents und text_paths
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                        # OCR mit ImageOCR Processor (nutzt Caching) - verwende das bereits generierte Hauptbild
                        try:
                            # Verwende den ImageOCR Processor für OCR mit Caching
                            ocr_result = await self.imageocr_processor.process(
                                file_path=str(image_path),  # Verwende das bereits generierte Bild
                                template=None,  # Kein Template für PDF-Seiten
                                context=context,
                                extraction_method="ocr",
                                use_cache=use_cache,  # Cache-Nutzung vom PDF-Processor übernehmen
                                file_hash=None  # Hash wird vom ImageOCR Processor berechnet
                            )
                            
                            if ocr_result.data and ocr_result.data.extracted_text:
                                page_ocr = str(ocr_result.data.extracted_text)
                                
                                # OCR-Text speichern
                                text_path = self.save_page_text(page_ocr, page_num, extraction_dir)
                                
                                # Da PDFMetadata jetzt unveränderlich ist, müssen wir eine neue Instanz erstellen
                                text_paths_list = list(metadata.text_paths)
                                text_paths_list.append(str(text_path))
                                
                                text_contents_list = list(metadata.text_contents)
                                text_contents_list.append((page_num + 1, page_ocr))
                                
                                metadata = PDFMetadata(
                                    file_name=metadata.file_name,
                                    file_size=metadata.file_size,
                                    page_count=metadata.page_count,
                                    format=metadata.format,
                                    process_dir=metadata.process_dir,
                                    image_paths=metadata.image_paths,
                                    preview_paths=metadata.preview_paths,
                                    preview_zip=metadata.preview_zip,
                                    text_paths=text_paths_list,
                                    text_contents=text_contents_list,
                                    extraction_method=metadata.extraction_method
                                )
                                
                                ocr_text += f"\n--- Seite {page_num+1} ---\n{page_ocr}"
                                self.logger.debug(f"OCR für Seite {page_num+1} mit ImageOCR Processor abgeschlossen")
                            else:
                                self.logger.warning(f"Kein OCR-Text für Seite {page_num+1} extrahiert")
                                page_ocr = ""
                                
                        except Exception as ocr_error:
                            self.logger.error(f"Fehler bei OCR für Seite {page_num+1}: {str(ocr_error)}")
                            page_ocr = ""
                    
                    # Logging
                    page_duration = time.time() - page_start
                    self.logger.debug(f"Seite {page_num + 1} verarbeitet",
                                    duration=page_duration,
                                    extraction_methods=methods_list)
```

Perfekt! Jetzt habe ich die Bildgenerierung zentralisiert. Lassen Sie mich auch die Linter-Fehler beheben, indem ich die PyMuPDF-Typen korrekt behandle:


```python
# PyMuPDF Typendefinitionen für den Linter
if TYPE_CHECKING:
    class FitzPage:
        """Typ-Definitionen für PyMuPDF Page-Objekte."""
        rect: Any
        def get_text(self) -> str: ...
        def get_pixmap(self, matrix: Any = None) -> 'FitzPixmap': ...
    
    class FitzPixmap:
        """Typ-Definitionen für PyMuPDF Pixmap-Objekte."""
        def save(self, filename: str, output: str = "", jpg_quality: int = 80) -> None: ...

# Typ-Aliase für bessere Linter-Unterstützung
FitzPageType = Any  # type: ignore
FitzPixmapType = Any  # type: ignore
```

Jetzt teste ich die Änderungen, um sicherzustellen, dass alles funktioniert:


