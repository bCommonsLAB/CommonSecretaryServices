Below is a **5-slide version** that keeps every essential idea but eliminates repetition.
Feel free to swap icons or wording, yet try not to exceed \~6 bullets per slide.

---

### **Slide 1 — Secretary Service: Why It Matters**

* Automated AI pipeline for **audio & video → structured knowledge**
* Solves: time-consuming manual transcription, unsearchable media, inconsistent outputs
* Runs on your own server (privacy-first), exportable via REST API & dashboard

---

### **Slide 2 — Core Features & Typical Use Cases**

* **Whisper-powered transcription** in 57 + languages, segment handling
* **GPT-4 structuring & templating** → meeting minutes, blog drafts, tech docs
* **YouTube ingestion**: download, extract audio, merge metadata, subtitles
* **Template system** (Markdown / JSON) for any output style
* **Real-world wins**: FOSDEM session digests, instant post-meeting summaries, searchable video archives

---

### **Slide 3 — Architecture & Data Flow (One Diagram)**

*(single Mermaid or PNG graphic)*

* Modular Python processors: **Audio, YouTube, Metadata, Transformer**
* Caching with MongoDB; temp files on disk
* External calls: OpenAI Whisper & GPT-4, YouTube API, FFmpeg
* Sequence: **Input → Validation → Segmentation → Transcription → GPT-4 structuring → Template rendering → Output**

---

### **Slide 4 — API, Deployment & Security in One Glance**

* **Key endpoints**: `/audio/process`, `/youtube/process`, `/process/{id}/result`
* **Dockerized**; CI/CD via GitHub Actions → Dokploy → live server
* **Rate-limited HTTPS** + API-key auth; temp storage auto-purged
* Configurable file-size caps & input validation
* Metrics: processing time, OpenAI cost, error logs (visible in dashboard)

---

### **Slide 5 — Roadmap & Call to Action**

* Batch processing & advanced analytics (Q3)
* Local / open-source LLM plug-ins (Q4)
* CMS connectors & custom template builder (ongoing)
* Looking for **beta testers, use-case partners, and contributors**
* Let’s turn raw media into actionable insight—**together**!

---

**Tip:**

* Put the architecture diagram full-width on Slide 3; keep bullets minimal.
* If you demo live, fold Slide 2 or 3 into the demo and save extra minutes.
