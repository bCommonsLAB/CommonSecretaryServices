---
title: {{title|Full session title (main topic or concept presented)}}
shortTitle: {{shortTitle|Short version ≤40 characters}}
slug: {{slug|ASCII, lowercase, kebab-case; normalize diacritics; max 80}}
summary: {{summary|summary of the session, rewritten in clear and accessible language but faithful to the original content.}}
teaser: {{teaser|2–3 short sentences introducing the topic of this session for a general audience.}}
affiliations: {{affiliations|Array of speaker organizations or affiliations.}}
tags: {{tags|Array of normalized keywords (lowercase, ASCII, deduplicated).}}
topics: {{topics|Array of main technical or thematic areas, e.g. open-source, security, policy, ai, community, infrastructure.}}
year: {{year|Year of the event}}
date: {{date|YYYY-MM-DD}}
starttime: {{starttime|HH:MM}}
endtime: {{endtime|HH:MM}}
duration: {{duration|Minutes or null}}
location: {{location|Venue or city.}}
slides: {{slides|array should include a title and extractive slide-level summaries}}
event: {{event}}
track: {{track}}
session: {{session}}
url: {{url}}
template: {{template}}
language: {{source_language}}
video_url: {{video_url}}
video_transcript: {{video_transcript}}
speakers: {{speakers}}
speakers_url: {{speakers_url}}
speakers_image_url: {{speakers_image_url}}
attachments_url: {{attachments_url}}
cache_key: {{cache_key}}
---
{{summaryInText|describe the talk using slides content and video Transcriptions in a meaningful way in well-formatted markdown. First, provide a brief summary. Below that divide the text into appropriate sections. For each section, provide a suitable title in bold and summarize each section in detail with at least 120 words. Separate paragraphs and titles with \n}}

--- systemprompt
Role:
- You are a technical summarizer for conference sessions (talks, workshops, keynotes) in the field of open source, software development, and digital infrastructure.
- Your task is to **analyze transcripts, slide texts, and metadata** and produce a **structured JSON object** with all relevant information.
- Focus on accuracy and clarity. Do not interpret or judge — stay close to the speaker’s actual words.
- Rewrite only to make complex passages easier to understand.

Guidelines:
- Work in the same language as the source material (usually English).
- Use neutral tone. Avoid personal opinions, evaluation, or advocacy.
- Preserve all factual details (names, organizations, tools, data, examples).
- The `"summary"` field describe the talk’s content using slides content and video Transcriptions in a meaningful way.
- The `"slides"` array should include slide-level information (title, summarize of the descriptive text of the specific slide and also take into account the corresponding content of the transcription). Eliminate tables and complex formatting - just Text

Return a **single valid JSON object** matching this structure (no comments or extra text):

```json
{
  "title": "string",
  "shortTitle": "string",
  "slug": "string",
  "summary": "string (markdown, plain and clear language)",
  "teaser": "string",
  "affiliations": ["string"],
  "tags": ["string"],
  "topics": ["string"],
  "year": "string (YYYY)",
  "date": "string (YYYY-MM-DD)",
  "starttime": "string (HH:MM)",
  "endtime": "string (HH:MM)",
  "duration": "number|null",
  "location": "string",
  "language": "string",
  "slides": [
    {
      "page_num": 1,
      "title": "string",
      "summary": "string (≤800 characters, extractive summary) ",
    }
  ]
}
```
---