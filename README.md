# Concept Constellation

A lightweight knowledge graph explorer for technical concepts, built with **Python · MongoDB · PyMongo · Streamlit**.

---

## Quick Start

```bash
# 1. Clone / navigate to project directory
# 2. Install dependencies
pip install -r requirements.txt   # includes pyvis for the interactive graph

# 3. Configure your MongoDB URI
copy .env.example .env            # Windows
# cp .env.example .env            # macOS/Linux
# Edit .env and set MONGODB_URI

# 4. Seed the database (idempotent — safe to rerun)
python seed.py

# 5. Launch the app
python -m streamlit run app.py
# → Opens at http://localhost:8501
```

---

## Schema Design

### Collection: `concepts`

```json
{
  "name":         "Binary Search Tree",   // unique string
  "domain":       "DSA",                  // domain string
  "definition":   "...",
  "prerequisites": ["Binary Tree"],        // array of concept names
  "related":      ["Balanced BST", "Heap"]
}
```

### Collection: `learning_resources`

```json
{
  "title":         "PyMongo Tutorial",
  "url":           "https://pymongo.readthedocs.io/...",
  "concepts":      ["Document Model", "MongoDB Aggregation"],
  "resource_type": "Tutorial"             // enum: Tutorial | Documentation | Paper
}
```

### Design Decision: Embedded Arrays vs. Edge Collection

Relationships (`prerequisites`, `related`, `concepts`) are stored as **embedded string arrays** rather than in a separate edge collection because:

1. **Read performance** — Concept details including all relationships are retrieved in a single `find_one()` call with no joins.
2. **Simplicity** — Avoids a third collection and join overhead for a dataset of this size.
3. **MongoDB philosophy** — Documents that are queried together should be stored together.
4. **Aggregation support** — MongoDB's `$unwind` and `$lookup` make cross-collection analytics easy despite embedding.

Trade-off: referential integrity is not enforced by the database engine, so the application layer validates all references on write.

---

## Collection Validation

Both collections use MongoDB `$jsonSchema` validators (applied at `create_collection` time and refreshed via `collMod`):

| Collection          | Rule                                                      |
|---------------------|-----------------------------------------------------------|
| `concepts`          | All five fields required; arrays of strings               |
| `concepts`          | `name`, `domain`, `definition` must be non-empty strings  |
| `learning_resources`| All four fields required                                  |
| `learning_resources`| `url` must match `^https?://`                             |
| `learning_resources`| `resource_type` restricted to `["Tutorial","Documentation","Paper"]` |

A **unique index** on `concepts.name` prevents duplicate concept names at the database level.

**Application-level checks** (in `app.py`):
- Self-reference prevention (concept cannot list itself)
- Unknown reference detection for prerequisites, related, and resource concept lists
- Prerequisite cycle detection via BFS

---

## CRUD Operations

| Operation          | PyMongo call                        | Where used                            |
|--------------------|-------------------------------------|---------------------------------------|
| `insert_one()`     | Create concept / resource           | Manage → Add, `seed.py` (upsert)      |
| `insert_many()`    | Batch insert (seed script pattern)  | Demonstrated in seed pipeline         |
| `find()`           | List all concepts, resources linked | Explore, Resources, Graph             |
| `find_one()`       | Load single concept                 | Inspector panel, Edit resource        |
| `update_one()`     | Edit concept / resource             | Manage → Edit forms                   |
| `update_many()`    | Cascade-clean after delete          | `delete_concept()` cleanup            |
| `delete_one()`     | Delete concept / resource           | Manage → Delete action               |
| `delete_many()`    | Bulk cleanup (possible future use)  | Available via `delete_many()` calls   |

---

## Aggregation Pipelines

### 1. Concepts per Domain
```python
db.concepts.aggregate([
    {"$group":   {"_id": "$domain", "count": {"$sum": 1}}},
    {"$sort":    {"count": -1}},
    {"$project": {"domain": "$_id", "count": 1, "_id": 0}},
])
```

### 2. Most-Connected Concepts (degree = prereqs + related)
```python
db.concepts.aggregate([
    {"$project": {"name": 1, "degree": {"$add": [
        {"$size": "$prerequisites"}, {"$size": "$related"}]}}},
    {"$sort": {"degree": -1}},
    {"$limit": 10},
])
```

### 3. Domains Ranked by Concept Count
Uses the same `$group` → `$sort` pattern as Pipeline 1.

### 4. Resource Counts by Type
```python
db.learning_resources.aggregate([
    {"$group":   {"_id": "$resource_type", "count": {"$sum": 1}}},
    {"$sort":    {"count": -1}},
    {"$project": {"resource_type": "$_id", "count": 1, "_id": 0}},
])
```

### 5. Concepts with Most Resources (`$lookup`)
```python
db.learning_resources.aggregate([
    {"$unwind": "$concepts"},
    {"$group":  {"_id": "$concepts", "resource_count": {"$sum": 1}}},
    {"$sort":   {"resource_count": -1}},
    {"$limit":  10},
    {"$lookup": {"from": "concepts", "localField": "_id",
                 "foreignField": "name", "as": "concept_doc"}},
    {"$project": {"concept": "$_id", "resource_count": 1,
                  "domain": {"$arrayElemAt": ["$concept_doc.domain", 0]}, "_id": 0}},
])
```

---

## Error Handling

| Error scenario                  | Handling                                         |
|---------------------------------|--------------------------------------------------|
| MongoDB unreachable             | `st.stop()` with friendly error message          |
| Duplicate concept name          | `DuplicateKeyError` caught, user-facing message  |
| Schema validation failure       | `OperationFailure` caught, user-facing message   |
| Missing referenced concept      | Pre-write Python check returns error list        |
| Self-referencing concept        | Caught in `_validate_refs()`                     |
| Prerequisite cycles             | BFS check in `_has_cycle()`                      |
| Invalid URL format              | Regex check before insert                        |
| Empty collections               | Graceful "no data" messages in every section     |

---

## Project Structure

```
mongoproj/
├── app.py              # Streamlit app + all DB operations
├── seed.py             # Idempotent seed script
├── requirements.txt    # Python dependencies (includes pyvis)
├── .env.example        # Environment variable template
├── README.md           # This file
├── report.md           # Academic report
└── presentation.md     # Viva outline
```

## Application Sections

| Section | Description |
|---|---|
| **Graph** | Force-directed interactive knowledge graph (PyVis + NetworkX). Sidebar domain filters and edge-type toggles update the graph in real time. Select a concept from the dropdown to focus it and expand its neighborhood. |
| **Explore** | Searchable, filterable list of all concepts with a detailed inspector panel showing definition, prerequisites, related concepts, and linked resources. |
| **Resources** | Searchable learning resources with type filter, linked concept chips, and working URLs. |
| **Analytics** | Five MongoDB aggregation pipelines rendered as bar charts and tables: concepts per domain, most-connected concepts, domain ranking, resources by type, concepts with most resources ($lookup). |
| **Manage** | Full CRUD for concepts and resources. Cascade-deletion warnings show which documents will be affected before confirmation. |

---

## Environment Variables

| Variable      | Default                          | Description              |
|---------------|----------------------------------|--------------------------|
| `MONGODB_URI` | `mongodb://localhost:27017/`     | MongoDB connection string |
| `DB_NAME`     | `concept_constellation`          | Target database name      |

Copy `.env.example` to `.env` and fill in your values. Never commit `.env` with real credentials.
