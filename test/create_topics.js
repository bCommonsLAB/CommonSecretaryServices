// MongoDB-Script zum Erstellen von Topics basierend auf Session-Cache
// Dieses Script verwendet die bestehende Datenbank
// Ausführung mit: mongosh --file test/create_topics.js

// Verbindung zur Datenbank wird automatisch hergestellt
print("Starte Topic-Erstellung aus Session-Cache in der bestehenden Datenbank...");

// Ecosocial Themen als Referenzdaten
const ecosocialTopics = {
  "Energie": {
    "display_name": { "de": "Energie: Beschleunigung des Übergangs durch Open Source", "en": "Energy: Accelerating Transition Through Open Source" },
    "description": { 
      "de": "Diskussionen über den Einsatz von Open-Source-Technologien zur Förderung erneuerbarer Energien und zur Unterstützung der Energiewende.",
      "en": "Discussions about using open source technologies to promote renewable energy and support the energy transition."
    },
    "keywords": ["Energie", "Erneuerbare", "Open Source", "Nachhaltigkeit", "Transition"]
  },
  "Regierungskollaboration": {
    "display_name": { "de": "Regierungskollaboration durch Open Source", "en": "Government Collaboration Through Open Source" },
    "description": { 
      "de": "Erörterung der Zusammenarbeit zwischen Regierungen und Open-Source-Communities zur Förderung transparenter und partizipativer Regierungsführung.",
      "en": "Discussion of collaboration between governments and open source communities to promote transparent and participatory governance."
    },
    "keywords": ["Regierung", "Kollaboration", "Transparenz", "Partizipation", "Open Source"]
  },
  "Inklusives Web": {
    "display_name": { "de": "Inklusives Web für alle", "en": "Inclusive Web for Everyone" },
    "description": { 
      "de": "Fokus auf die Entwicklung von Web-Technologien, die für alle zugänglich sind, einschließlich Menschen mit Behinderungen, um digitale Inklusion zu fördern.",
      "en": "Focus on developing web technologies accessible to everyone, including people with disabilities, to promote digital inclusion."
    },
    "keywords": ["Inklusion", "Barrierefreiheit", "Web", "Accessibility", "Digitale Teilhabe"]
  },
  "Open-Source-Design": {
    "display_name": { "de": "Open-Source-Design für nachhaltige Lösungen", "en": "Open Source Design for Sustainable Solutions" },
    "description": { 
      "de": "Förderung von Designpraktiken, die auf offenen Prinzipien basieren, um benutzerzentrierte und nachhaltige Lösungen zu entwickeln.",
      "en": "Promotion of design practices based on open principles to develop user-centered and sustainable solutions."
    },
    "keywords": ["Design", "Open Source", "Nachhaltigkeit", "UX", "Benutzerzentriert"]
  },
  "offenes Design": {
    "display_name": { "de": "Offenes Design für nachhaltige Lösungen", "en": "Open Design for Sustainable Solutions" },
    "description": { 
      "de": "Förderung von Designpraktiken, die auf offenen Prinzipien basieren, um benutzerzentrierte und nachhaltige Lösungen zu entwickeln.",
      "en": "Promotion of design practices based on open principles to develop user-centered and sustainable solutions."
    },
    "keywords": ["Design", "Open Source", "Nachhaltigkeit", "UX", "Benutzerzentriert"]
  },
  "Open-Source-Hardware": {
    "display_name": { "de": "Open-Source-Hardware und nachhaltige Produktion", "en": "Open Source Hardware and Sustainable Production" },
    "description": { 
      "de": "Diskussionen über die Entwicklung und Verbreitung von Open-Source-Hardwarelösungen, die nachhaltige Produktion und Reparatur fördern.",
      "en": "Discussions about the development and dissemination of open source hardware solutions that promote sustainable production and repair."
    },
    "keywords": ["Hardware", "Open Source", "Nachhaltigkeit", "Produktion", "Reparierbarkeit"]
  }
};

// Details aus dem Beispiel-Cache-Eintrag
const exampleCacheId = "67d4de1a4b21761a934fae47";
print(`Suche nach Cache-Eintrag mit _id: ${exampleCacheId}`);

// BSON-ObjectId erstellen
let objectId;
try {
  objectId = new ObjectId(exampleCacheId);
  print("ObjectId erfolgreich erstellt.");
} catch (e) {
  print(`Fehler beim Erstellen der ObjectId: ${e.message}`);
  objectId = null;
}

let exampleEntry = null;
if (objectId) {
  exampleEntry = db.session_cache.findOne({ _id: objectId });
}

if (!exampleEntry) {
  print("Beispiel-Eintrag nicht gefunden, suche nach Einträgen mit 'offenes Design'...");
  exampleEntry = db.session_cache.findOne({ "result.topic": "offenes Design" });
}

if (exampleEntry) {
  print("Cache-Eintrag gefunden:");
  printjson({
    _id: exampleEntry._id,
    cache_key: exampleEntry.cache_key,
    created_at: exampleEntry.created_at,
    "result.topic": exampleEntry.result?.topic,
    "result.event": exampleEntry.result?.event
  });
} else {
  print("Kein passender Cache-Eintrag gefunden. Suche nach allen Einträgen mit Topics...");
}

// Session-Cache auslesen
const sessionCacheEntries = db.session_cache.find({
  "result.topic": { $exists: true, $ne: null }
}).toArray();

print(`${sessionCacheEntries.length} Session-Cache-Einträge mit Topics gefunden.`);

// Einzigartige Topics extrahieren
const uniqueTopics = [];
const topicMapping = {};

sessionCacheEntries.forEach(entry => {
  const topicName = entry.result.topic;
  if (topicName && !topicMapping[topicName]) {
    uniqueTopics.push(topicName);
    topicMapping[topicName] = true;
  }
});

print(`${uniqueTopics.length} einzigartige Topics extrahiert: ${uniqueTopics.join(", ")}`);

// Topics in der Collection erstellen
let createdCount = 0;
uniqueTopics.forEach(topicName => {
  // Prüfen, ob Topic bereits existiert
  const existingTopic = db.topics.findOne({ "topic_id": topicName });
  if (existingTopic) {
    print(`Topic "${topicName}" existiert bereits.`);
    return;
  }
  
  // Topic-Daten erstellen
  const topicData = ecosocialTopics[topicName] || {
    "display_name": { "de": topicName, "en": topicName },
    "description": { 
      "de": `Ein Thema über ${topicName} im Kontext von Open Source und Nachhaltigkeit.`,
      "en": `A topic about ${topicName} in the context of open source and sustainability.`
    },
    "keywords": [topicName, "Open Source", "Nachhaltigkeit"]
  };
  
  // Event aus der Session extrahieren
  let event = "FOSDEM 2025"; // Standard-Event
  const sessionWithTopic = sessionCacheEntries.find(s => s.result.topic === topicName);
  if (sessionWithTopic && sessionWithTopic.result.event) {
    event = sessionWithTopic.result.event;
  }
  
  // Topic-Dokument erstellen
  const topicDocument = {
    "topic_id": topicName,
    "event": event,
    "display_name": topicData.display_name,
    "description": topicData.description,
    "keywords": topicData.keywords,
    "primary_target_group": "technical",
    "relevance_threshold": 0.6,
    "status": "active",
    "template": "ecosocial",
    "created_at": new Date(),
    "updated_at": new Date()
  };
  
  // In die Datenbank einfügen
  db.topics.insertOne(topicDocument);
  createdCount++;
  print(`Topic "${topicName}" erfolgreich erstellt.`);
});

print(`${createdCount} neue Topics erstellt.`);

// Test: Topic abfragen
const testTopic = "offenes Design";
const topic = db.topics.findOne({ "topic_id": testTopic });

if (topic) {
  print(`\nTest erfolgreich: Topic "${testTopic}" gefunden:`);
  printjson(topic);
} else {
  print(`\nTest fehlgeschlagen: Topic "${testTopic}" nicht gefunden.`);
}

// Zielgruppen erstellen, falls nicht vorhanden
const targetGroups = [
  {
    "target_id": "technical",
    "display_name": {
      "de": "Technische Zielgruppe",
      "en": "Technical Audience"
    },
    "description": {
      "de": "Entwickler, Technikexperten und technisch versierte Personen",
      "en": "Developers, technical experts, and technically skilled individuals"
    },
    "status": "active"
  },
  {
    "target_id": "non_technical",
    "display_name": {
      "de": "Nicht-technische Zielgruppe",
      "en": "Non-Technical Audience"
    },
    "description": {
      "de": "Entscheidungsträger, Manager und nicht-technische Stakeholder",
      "en": "Decision makers, managers, and non-technical stakeholders"
    },
    "status": "active"
  }
];

let targetGroupsCreated = 0;
targetGroups.forEach(tg => {
  const existingTargetGroup = db.target_groups.findOne({ "target_id": tg.target_id });
  if (!existingTargetGroup) {
    tg.created_at = new Date();
    tg.updated_at = new Date();
    db.target_groups.insertOne(tg);
    targetGroupsCreated++;
    print(`Zielgruppe "${tg.target_id}" erstellt.`);
  } else {
    print(`Zielgruppe "${tg.target_id}" existiert bereits.`);
  }
});
print(`${targetGroupsCreated} neue Zielgruppen erstellt.`);

print("\nTopic- und Zielgruppen-Erstellung abgeschlossen."); 