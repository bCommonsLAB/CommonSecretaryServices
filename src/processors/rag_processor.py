"""
@fileoverview RAG Processor - Embedding-Prozessor für RAG

@description
RAG Processor für das Einbetten von Markdown-Dokumenten in Vektoren.
This processor handles:
- Markdown document chunking with structure awareness
- Embedding generation using a configurable embedding model (default: voyage-3-large)

Features:
- Contextualized chunk embeddings with voyage-3-large (oder konfiguriertem Modell)
- Markdown-aware chunking (respects headings, paragraphs)
- Configurable chunk size, overlap, and embedding dimensions

@module processors.rag_processor

@exports
- RAGProcessor: Class - RAG embedding processor

@usedIn
- src.api.routes.rag_routes: API endpoint für RAG-Embedding-Operationen

@dependencies
- External: voyageai - Voyage API client
- Internal: src.processors.base_processor - BaseProcessor base class
- Internal: src.core.models.rag - RAG models (RAGChunk, RAGEmbeddingResult, etc.)
- Internal: src.core.config - Configuration
- Internal: src.core.llm - LLM config infrastructure
"""
# pyright: reportMissingImports=false, reportUnknownMemberType=false

import os
import re
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
import time

try:
    import voyageai
except ImportError:
    voyageai = None

from src.core.models.rag import RAGChunk, RAGEmbeddingResult
from src.core.models.base import ProcessInfo
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.processors.base_processor import BaseProcessor
from src.core.config import Config
from src.core.llm import LLMConfigManager


class RAGProcessor(BaseProcessor[RAGEmbeddingResult]):
    """
    RAG-Prozessor für Embedding von Markdown-Dokumenten.
    
    Verarbeitet Markdown-Dokumente, erstellt Embeddings mit einem konfigurierten
    Embedding-Modell (Standard: voyage-3-large) und gibt die Chunks mit
    Embeddings zurück. Es findet keine Speicherung in MongoDB und keine Query-
    Verarbeitung mehr statt.
    """
    
    def __init__(
        self,
        resource_calculator: ResourceCalculator,
        process_id: Optional[str] = None,
        parent_process_info: Optional[ProcessInfo] = None
    ):
        """
        Initialisiert den RAGProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        super().__init__(
            resource_calculator=resource_calculator,
            process_id=process_id,
            parent_process_info=parent_process_info
        )
        
        try:
            # Konfiguration laden
            config = Config()
            processor_config = config.get('processors', {})
            rag_config = processor_config.get('rag', {})
            
            # Voyage API Konfiguration
            voyage_api_key = os.getenv('VOYAGE_API_KEY') or rag_config.get('voyage_api_key')
            if not voyage_api_key:
                raise ProcessingError(
                    "VOYAGE_API_KEY nicht gefunden. Bitte setzen Sie die Umgebungsvariable "
                    "oder konfigurieren Sie 'processors.rag.voyage_api_key' in config.yaml"
                )
            
            # Voyage Client initialisieren
            if voyageai is None:
                raise ProcessingError(
                    "voyageai Paket nicht installiert. Bitte installieren Sie es mit: pip install voyageai"
                )
            
            self.voyage_client = voyageai.Client(api_key=voyage_api_key)
            
            # RAG-spezifische Konfiguration
            # Embedding-Defaults aus LLM-Config (Use-Case EMBEDDING) lesen und mit
            # processors.rag.* zusammenführen.
            self.llm_config_manager = LLMConfigManager()
            default_embedding_model, _default_embedding_provider, default_embedding_dims = (
                self.llm_config_manager.get_embedding_defaults()
            )

            self.embedding_model: str = rag_config.get(
                'embedding_model',
                default_embedding_model or 'voyage-3-large'
            )
            self.embedding_dimensions: int = rag_config.get(
                'embedding_dimensions',
                default_embedding_dims or 2048
            )
            self.chunk_size: int = rag_config.get('chunk_size', 1000)
            self.chunk_overlap: int = rag_config.get('chunk_overlap', 200)
            
            self.logger.info("RAGProcessor initialisiert", extra={
                "embedding_model": self.embedding_model,
                "embedding_dimensions": self.embedding_dimensions,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap
            })
            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des RAGProcessors", error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")
    
    def _chunk_markdown(
        self,
        text: str,
        document_id: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None
    ) -> List[RAGChunk]:
        """
        Zerlegt Markdown-Text in Chunks unter Berücksichtigung der Struktur.
        
        Args:
            text: Der Markdown-Text
            document_id: Die Dokument-ID
            chunk_size: Größe der Chunks (Standard aus Config)
            chunk_overlap: Overlap zwischen Chunks (Standard aus Config)
            
        Returns:
            List[RAGChunk]: Liste der Chunks
        """
        # Verwende explizite None-Prüfung, damit chunk_overlap=0 nicht überschrieben wird
        chunk_size = chunk_size if chunk_size is not None else self.chunk_size
        chunk_overlap = chunk_overlap if chunk_overlap is not None else self.chunk_overlap
        
        if chunk_size <= 0:
            raise ValueError("Chunk-Größe muss positiv sein")
        if chunk_overlap < 0:
            raise ValueError("Chunk-Overlap darf nicht negativ sein")
        if chunk_overlap >= chunk_size:
            raise ValueError("Chunk-Overlap muss kleiner als Chunk-Größe sein")
        
        chunks: List[RAGChunk] = []
        
        # Teile Text in Absätze auf (doppelte Zeilenumbrüche)
        paragraphs = re.split(r'\n\n+', text)
        
        current_chunk_text: List[str] = []
        current_chunk_length = 0
        current_heading: Optional[str] = None
        chunk_index = 0
        start_char = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # Prüfe ob Absatz eine Überschrift ist
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', para)
            if heading_match:
                # Überschrift gefunden - speichere als Kontext
                current_heading = heading_match.group(2).strip()
                # Überschrift zum aktuellen Chunk hinzufügen
                if current_chunk_text:
                    # Überschrift am Anfang des nächsten Chunks einfügen
                    para = f"{para}\n\n"
                else:
                    para = f"{para}\n\n"
            
            para_length = len(para)
            
            # Wenn Absatz allein zu groß ist, teile ihn weiter
            if para_length > chunk_size:
                # Speichere aktuellen Chunk falls vorhanden
                if current_chunk_text:
                    chunk_text = '\n\n'.join(current_chunk_text)
                    end_char = start_char + len(chunk_text)
                    chunks.append(RAGChunk(
                        text=chunk_text,
                        chunk_index=chunk_index,
                        document_id=document_id,
                        heading_context=current_heading,
                        start_char=start_char,
                        end_char=end_char,
                        metadata={}
                    ))
                    chunk_index += 1
                    start_char = end_char
                    current_chunk_text = []
                    current_chunk_length = 0
                
                # Teile großen Absatz in kleinere Teile
                words = para.split()
                temp_text: List[str] = []
                temp_length = 0
                
                for word in words:
                    word_with_space = word + ' '
                    word_length = len(word_with_space)
                    
                    if temp_length + word_length > chunk_size:
                        if temp_text:
                            chunk_text = ' '.join(temp_text)
                            end_char = start_char + len(chunk_text)
                            chunks.append(RAGChunk(
                                text=chunk_text,
                                chunk_index=chunk_index,
                                document_id=document_id,
                                heading_context=current_heading,
                                start_char=start_char,
                                end_char=end_char,
                                metadata={}
                            ))
                            chunk_index += 1
                            start_char = end_char
                            temp_text = []
                            temp_length = 0
                    
                    temp_text.append(word)
                    temp_length += word_length
                
                # Rest als neuen Chunk
                if temp_text:
                    current_chunk_text = temp_text
                    current_chunk_length = temp_length
                continue
            
            # Prüfe ob Absatz in aktuellen Chunk passt
            if current_chunk_length + para_length + 2 <= chunk_size:  # +2 für \n\n
                current_chunk_text.append(para)
                current_chunk_length += para_length + 2
            else:
                # Aktuellen Chunk speichern
                if current_chunk_text:
                    chunk_text = '\n\n'.join(current_chunk_text)
                    end_char = start_char + len(chunk_text)
                    chunks.append(RAGChunk(
                        text=chunk_text,
                        chunk_index=chunk_index,
                        document_id=document_id,
                        heading_context=current_heading,
                        start_char=start_char,
                        end_char=end_char,
                        metadata={}
                    ))
                    chunk_index += 1
                    
                    # Overlap: Nimm letzten Teil des vorherigen Chunks
                    if chunk_overlap > 0 and len(chunk_text) > chunk_overlap:
                        overlap_text = chunk_text[-chunk_overlap:]
                        current_chunk_text = [overlap_text, para]
                        current_chunk_length = len(overlap_text) + para_length + 2
                        start_char = end_char - chunk_overlap
                    else:
                        current_chunk_text = [para]
                        current_chunk_length = para_length
                        start_char = end_char
                else:
                    current_chunk_text = [para]
                    current_chunk_length = para_length
        
        # Letzten Chunk speichern
        if current_chunk_text:
            chunk_text = '\n\n'.join(current_chunk_text)
            end_char = start_char + len(chunk_text)
            chunks.append(RAGChunk(
                text=chunk_text,
                chunk_index=chunk_index,
                document_id=document_id,
                heading_context=current_heading,
                start_char=start_char,
                end_char=end_char,
                metadata={}
            ))
        
        return chunks
    
    def _estimate_tokens(self, text: str) -> int:
        """
        Schätzt die Anzahl der Tokens für einen Text.
        
        Verwendet eine konservative Schätzung basierend auf Zeichenanzahl.
        Die Schätzung ist bewusst konservativ, um sicher unter dem API-Limit zu bleiben.
        
        Basierend auf Tests: Die tatsächliche Token-Anzahl kann bis zu 12% höher sein
        als die Schätzung, daher verwenden wir eine sehr konservative Schätzung.
        
        Args:
            text: Der zu schätzende Text
            
        Returns:
            Geschätzte Token-Anzahl (konservativ überschätzt)
        """
        # Sehr konservative Schätzung: 1 Token ≈ 2.2 Zeichen
        # Basierend auf Tests mit voyage-3-large: tatsächliche Token-Anzahl kann
        # bis zu 12% höher sein als geschätzt. Daher verwenden wir 2.2 Zeichen pro Token
        # für eine sichere Überschätzung.
        return int(len(text) / 2.2)
    
    def _split_into_batches(
        self,
        texts: List[str],
        max_tokens_per_batch: int = 120000
    ) -> List[List[str]]:
        """
        Teilt eine Liste von Texten in Batches auf, sodass jeder Batch
        unter dem Token-Limit bleibt.
        
        Verwendet einen Sicherheitspuffer, um sicherzustellen, dass die tatsächliche
        Token-Anzahl das Limit nicht überschreitet, auch wenn die Schätzung leicht abweicht.
        
        Args:
            texts: Liste der Texte
            max_tokens_per_batch: Maximale Token-Anzahl pro Batch (Standard: 120000)
            
        Returns:
            Liste von Batches (jeder Batch ist eine Liste von Texten)
        """
        # Sicherheitspuffer: Verwende nur 85% des Limits, um Ungenauigkeiten
        # in der Token-Schätzung zu kompensieren
        # Die Schätzung kann bis zu 12% niedriger sein als die tatsächliche Token-Anzahl,
        # daher verwenden wir einen größeren Puffer für Sicherheit
        safety_buffer = 0.85
        effective_max_tokens = int(max_tokens_per_batch * safety_buffer)
        
        batches: List[List[str]] = []
        current_batch: List[str] = []
        current_batch_tokens = 0
        
        for text in texts:
            text_tokens = self._estimate_tokens(text)
            
            # Wenn der Text allein das Limit überschreitet, loggen wir eine Warnung
            # aber fügen ihn trotzdem hinzu (kann nicht weiter aufgeteilt werden)
            if text_tokens > effective_max_tokens:
                self.logger.warning(
                    f"Text überschreitet Batch-Limit ({text_tokens} > {effective_max_tokens} Tokens). "
                    "Wird trotzdem verarbeitet, könnte fehlschlagen."
                )
            
            # Prüfe ob Text in aktuellen Batch passt (mit Sicherheitspuffer)
            if current_batch_tokens + text_tokens <= effective_max_tokens:
                current_batch.append(text)
                current_batch_tokens += text_tokens
            else:
                # Aktuellen Batch speichern und neuen starten
                if current_batch:
                    batches.append(current_batch)
                current_batch = [text]
                current_batch_tokens = text_tokens
        
        # Letzten Batch hinzufügen
        if current_batch:
            batches.append(current_batch)
        
        return batches
    
    def _generate_embeddings(
        self,
        texts: List[str],
        input_type: str = "document",
        model: Optional[str] = None,
        dimensions: Optional[int] = None
    ) -> List[List[float]]:
        """
        Generiert Embeddings für eine Liste von Texten mit dem konfigurierten Embedding-Modell.
        
        Teilt große Batches automatisch auf, um das Token-Limit von 120.000 Tokens pro Batch
        nicht zu überschreiten.
        
        Args:
            texts: Liste der Texte zum Einbetten
            input_type: Typ des Inputs ("document" oder "query")
            model: Optionales Modell (überschreibt Standard)
            dimensions: Optionale Embedding-Dimensionen (überschreibt Standard)
            
        Returns:
            List[List[float]]: Liste der Embeddings (in derselben Reihenfolge wie texts)
        """
        if not texts:
            return []
        
        try:
            # Effektives Embedding-Modell wählen: explizit angefordert oder Default.
            effective_model: str = model or self.embedding_model
            # Effektive Embedding-Dimensionen wählen: explizit angefordert oder Default.
            effective_dimensions: int = dimensions if dimensions is not None else self.embedding_dimensions

            # Voyage API Limit: 120.000 Tokens pro Batch
            # Teile Texte in Batches auf, falls nötig
            # Verwende einen Sicherheitspuffer von 85% (102.000 Tokens) um Ungenauigkeiten
            # in der Token-Schätzung zu kompensieren
            # Die Schätzung kann bis zu 12% niedriger sein als die tatsächliche Token-Anzahl
            max_tokens_per_batch = 120000
            safety_buffer = 0.85
            effective_max_tokens = int(max_tokens_per_batch * safety_buffer)
            
            # Für Queries ist das Limit normalerweise kein Problem (nur 1 Text)
            # Aber für Dokumente mit vielen Chunks kann es relevant sein
            if input_type == "document" and len(texts) > 1:
                # Schätze Token-Anzahl für alle Texte
                total_tokens = sum(self._estimate_tokens(text) for text in texts)
                
                if total_tokens > effective_max_tokens:
                    # Aufteilen in Batches (mit Sicherheitspuffer)
                    self.logger.info(
                        f"Text-Batch überschreitet Token-Limit ({total_tokens} > {effective_max_tokens}). "
                        f"Teile in kleinere Batches auf (Sicherheitspuffer: {safety_buffer*100}%, "
                        f"effektives Limit: {effective_max_tokens} Tokens)."
                    )
                    batches = self._split_into_batches(texts, max_tokens_per_batch)
                    
                    # Verarbeite jeden Batch separat
                    # WICHTIG: Die Reihenfolge wird beibehalten - alle Embeddings werden
                    # in der ursprünglichen Reihenfolge der Texte gesammelt
                    all_embeddings: List[List[float]] = []
                    for i, batch in enumerate(batches):
                        batch_tokens = sum(self._estimate_tokens(text) for text in batch)
                        self.logger.info(
                            f"Verarbeite Batch {i+1}/{len(batches)} "
                            f"({len(batch)} Texte, geschätzt ~{batch_tokens} Tokens, "
                            f"Limit: {effective_max_tokens})"
                        )
                        
                        # Voyage API: Dimensionen werden als 'output_dimension' Parameter übergeben
                        # Für voyage-3-large sind 256, 512, 1024, 2048 unterstützt
                        response: Any = self.voyage_client.embed(  # type: ignore
                            texts=batch,
                            model=effective_model,
                            input_type=input_type,
                            output_dimension=effective_dimensions
                        )
                        # Embeddings in der richtigen Reihenfolge hinzufügen
                        # (jeder Batch behält die Reihenfolge der Texte bei)
                        all_embeddings.extend(response.embeddings)  # type: ignore
                    
                    self.logger.info(
                        f"Alle Batches verarbeitet: {len(all_embeddings)} Embeddings generiert"
                    )
                    return all_embeddings
            
            # Normale Verarbeitung (kein Batch-Splitting nötig)
            # Voyage API: Dimensionen werden als 'output_dimension' Parameter übergeben
            response: Any = self.voyage_client.embed(  # type: ignore
                texts=texts,
                model=effective_model,
                input_type=input_type,
                output_dimension=effective_dimensions
            )
            return response.embeddings  # type: ignore
                
        except Exception as e:
            self.logger.error("Fehler bei der Embedding-Generierung", error=e)
            raise ProcessingError(f"Fehler bei der Embedding-Generierung: {str(e)}")
    
    async def embed_document_for_client(
        self,
        text: str,
        document_id: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        embedding_model: Optional[str] = None,
        embedding_dimensions: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RAGEmbeddingResult:
        """
        Bettet ein Markdown-Dokument ein und gibt das Ergebnis zurück.
        
        Diese Methode ist für Clients gedacht, die die Chunks und Embeddings selbst
        persistieren möchten (z.B. in einer eigenen Vector-Datenbank). Es findet
        keine Speicherung im Backend statt.
        """
        start_time = time.time()
        
        try:
            # Effektives Embedding-Modell bestimmen (Client-Wahl oder Default).
            effective_embedding_model: str = embedding_model or self.embedding_model
            # Effektive Embedding-Dimensionen bestimmen (Client-Wahl oder Default).
            effective_embedding_dimensions: int = embedding_dimensions if embedding_dimensions is not None else self.embedding_dimensions
            # Dokument-ID generieren falls nicht vorhanden
            if not document_id:
                document_id = str(uuid.uuid4())
            
            # Chunking durchführen
            self.logger.info("Starte Chunking (client)", extra={"document_id": document_id})
            chunks = self._chunk_markdown(text, document_id, chunk_size, chunk_overlap)
            self.logger.info(f"Chunking abgeschlossen (client): {len(chunks)} Chunks erstellt")
            
            if not chunks:
                raise ProcessingError("Keine Chunks erstellt")
            
            # Embeddings generieren
            self.logger.info(
                "Starte Embedding-Generierung (client)",
                extra={
                    "chunk_count": len(chunks),
                    "embedding_model": effective_embedding_model,
                    "embedding_dimensions": effective_embedding_dimensions
                }
            )
            chunk_texts = [chunk.text for chunk in chunks]
            embeddings = self._generate_embeddings(
                chunk_texts,
                input_type="document",
                model=effective_embedding_model,
                dimensions=effective_embedding_dimensions
            )
            
            if len(embeddings) != len(chunks):
                raise ProcessingError(
                    f"Anzahl der Embeddings ({len(embeddings)}) stimmt nicht mit "
                    f"Anzahl der Chunks ({len(chunks)}) überein"
                )
            
            # Tatsächliche Dimensionen aus dem ersten Embedding ermitteln
            # (falls die API andere Dimensionen zurückgibt als angefordert)
            actual_dimensions: int = len(embeddings[0]) if embeddings else effective_embedding_dimensions
            
            # Warnung, falls die Dimensionen nicht übereinstimmen
            if actual_dimensions != effective_embedding_dimensions:
                self.logger.warning(
                    f"Dimensionen stimmen nicht überein: "
                    f"Angefordert: {effective_embedding_dimensions}, "
                    f"Tatsächlich: {actual_dimensions}. "
                    f"Verwende tatsächliche Dimensionen."
                )
            
            # Embeddings zu Chunks hinzufügen
            chunks_with_embeddings: List[RAGChunk] = []
            for i, chunk in enumerate(chunks):
                chunk_dict = chunk.to_dict()
                chunk_dict['embedding'] = embeddings[i]
                chunks_with_embeddings.append(RAGChunk.from_dict(chunk_dict))
            
            # Ergebnis erstellen (nur in-memory, keine DB)
            # Verwende die tatsächlich zurückgegebenen Dimensionen
            result = RAGEmbeddingResult(
                document_id=document_id,
                chunks=chunks_with_embeddings,
                total_chunks=len(chunks_with_embeddings),
                embedding_dimensions=actual_dimensions,
                embedding_model=effective_embedding_model,
                created_at=datetime.now().isoformat(),
                metadata=metadata or {}
            )
            
            duration = time.time() - start_time
            self.logger.info(
                "Embedding (client) abgeschlossen",
                extra={
                    "document_id": document_id,
                    "chunks": len(chunks_with_embeddings),
                    "duration_seconds": duration
                }
            )
            
            return result
        
        except Exception as e:
            self.logger.error("Fehler beim Embedding (client)", error=e)
            raise ProcessingError(f"Fehler beim Embedding (client): {str(e)}")
    

