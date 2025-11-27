RAG Embed-Text Endpoint – Designüberlegungen
===========================================

Ziel
----
Ein neuer API-Endpunkt soll Markdown **als reinen Text** entgegennehmen, diesen mit der bestehenden RAG-Pipeline in strukturierte Chunks inkl. Embeddings verarbeiten und **ohne Speicherung in MongoDB** an den Client zurückgeben. Der Client kann die Chunks samt Embeddings in einer eigenen Datenbank speichern und für einen externen Retriever verwenden.

Varianten
---------
1. **Direkter Reuse von `embed_document` mit Flag für „ohne Storage“**  
   - `embed_document` erhält ein Flag `store_in_db: bool`, das bei `False` die Mongo-Operationen überspringt.  
   - Pro: Wenig Duplikation, nur eine zentrale Implementierung.  
   - Contra: Signaturänderung einer bestehenden, bereits genutzten Methode; erhöhtes Risiko für Seiteneffekte.

2. **Neue Hilfsfunktion für Embedding-Erzeugung, die von beiden Wegen genutzt wird**  
   - Extraktion der gemeinsamen Logik (Chunking, Embedding-Aufruf, Zusammenbau von `RAGEmbeddingResult`) in eine private Methode (`_create_embedding_result`).  
   - `embed_document` ruft diese Methode auf und speichert zusätzlich in MongoDB.  
   - Ein neuer API-orientierter Weg ruft die gleiche Methode auf, gibt das Ergebnis aber nur zurück.  
   - Pro: Saubere Trennung von „Berechnung“ und „Persistenz“, keine Duplikation der Kernlogik.  
   - Contra: Erfordert Refactoring eines bereits funktionierenden Pfads.

3. **Komplett separater, „in-memory“ Pfad mit eigener Logik**  
   - Neue Methode `embed_document_for_client` mit kopierter Logik aus `embed_document`, aber ohne DB-Zugriff.  
   - Neuer Endpoint nutzt ausschließlich diese Methode.  
   - Pro: Minimale Änderungen an bestehendem Codepfad, geringes Risiko für Regressionen.  
   - Contra: Duplizierte Logik (Chunking + Embedding), etwas schlechtere Wartbarkeit.

Entscheidung
------------
Für den ersten Schritt wählen wir **Variante 3 (separater In-Memory-Pfad)**:

- Der bestehende `embed_document`-Pfad bleibt unverändert, inklusive Persistenz in MongoDB.  
- Eine neue Methode `embed_document_for_client` im `RAGProcessor` kapselt denselben Berechnungspfad, verzichtet aber vollständig auf Datenbankzugriffe.  
- Ein neuer Endpoint (z.B. `POST /api/rag/embed-text`) nimmt Markdown als JSON-String entgegen, ruft `embed_document_for_client` auf und gibt ein `RAGEmbeddingResult` in der bereits etablierten Response-Struktur zurück (`status`, `request`, `process`, `data`).  

Diese Lösung hält die Änderungen am existierenden Verhalten minimal, erfüllt den neuen Anwendungsfall (Client-verwaltete Speicherung) und kann später bei Bedarf in Richtung Variante 2 refaktoriert werden, falls weitere RAG-Endpunkte hinzukommen.




