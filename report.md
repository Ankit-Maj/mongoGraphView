# Concept Constellation — Academic Report

**Course:** Intelligent NoSQL Databases  
**Project:** Concept Constellation — Knowledge Graph Explorer  
**Technology Stack:** Python 3.11+, MongoDB 7.x, PyMongo 4.6, Streamlit 1.32

---

## 1. Problem Statement

Technical knowledge is inherently graph-structured: concepts have prerequisites, belong to domains, and are interrelated. Traditional flat documents or relational tables struggle to represent these relationships readably. This project builds **Concept Constellation**, a minimal knowledge-graph explorer that stores, queries, and visualizes these relationships using MongoDB's document model.

---

## 2. Objectives

1. Demonstrate MongoDB schema design using embedded arrays for graph edges.
2. Implement full CRUD operations via PyMongo with schema validation.
3. Derive meaningful analytics through MongoDB aggregation pipelines.
4. Build a usable Streamlit interface with application-level integrity checks.
5. Show that NoSQL document databases are well-suited for flexible, graph-adjacent data.

---

## 3. Document Structure

### 3.1 `concepts` Collection

Each concept is a self-contained document. Graph edges (prerequisites, related) are stored as embedded string arrays of concept names.

```json
{
  "_id": ObjectId("..."),
  "name": "Binary Search Tree",
  "domain": "DSA",
  "definition": "Binary tree with ordered left/right subtree property.",
  "prerequisites": ["Binary Tree"],
  "related": ["Binary Tree", "Balanced BST"]
}
```

**Rationale for embedding:** A graph traversal starting from a concept needs its immediate neighbours. By embedding these as name arrays, a single `find_one()` returns all necessary data without additional round-trips. The trade-off is that referential integrity must be enforced in the application layer.

### 3.2 `learning_resources` Collection

Resources are also self-contained documents. The `concepts` array links resources to concepts by name, enabling the `$lookup`-based aggregation.

```json
{
  "_id": ObjectId("..."),
  "title": "Introduction to Algorithms (CLRS)",
  "url": "https://mitpress.mit.edu/...",
  "concepts": ["Dynamic Programming", "Graph Traversal", "Shortest Path", "Heap"],
  "resource_type": "Documentation"
}
```

---

## 4. Schema Validation

MongoDB `$jsonSchema` validators are set at collection creation and updated via `collMod`. Key rules:

| Field | Rule |
|---|---|
| `concepts.name` | `bsonType: string`, `minLength: 1` |
| `concepts.domain` | `bsonType: string`, `minLength: 1` |
| `concepts.prerequisites` | `bsonType: array`, items are strings |
| `learning_resources.url` | `pattern: "^https?://"` |
| `learning_resources.resource_type` | `enum: ["Tutorial","Documentation","Paper"]` |

A unique index on `concepts.name` prevents duplicate concept creation at the storage level.

**Validation test (from `seed.py`):** Inserting a document with only `name` set raises `OperationFailure` with message `Document failed validation`, confirming the validator is active.

---

## 5. CRUD Operations

All database operations are implemented directly in `app.py` using PyMongo — no ORM, no abstraction layer beyond simple helper functions.

### 5.1 Create

```python
# Concept creation — insert_one()
db.concepts.insert_one({
    "name": name, "domain": domain, "definition": definition,
    "prerequisites": prerequisites, "related": related
})

# Seed — upsert pattern (insert_many semantics via repeated update_one with $setOnInsert)
db.concepts.update_one({"name": c["name"]}, {"$setOnInsert": c}, upsert=True)
```

### 5.2 Read

```python
db.concepts.find_one({"name": name}, {"_id": 0})           # single concept
db.concepts.find({}, {"name": 1, "_id": 0}).sort("name")   # all names
db.learning_resources.find({"concepts": concept_name})      # resources for a concept
```

### 5.3 Update

```python
db.concepts.update_one(
    {"name": name},
    {"$set": {"domain": domain, "definition": definition,
              "prerequisites": prerequisites, "related": related}}
)
```

### 5.4 Delete

```python
db.concepts.delete_one({"name": name})
# Cascade cleanup using update_many + $pull
db.concepts.update_many({"prerequisites": name}, {"$pull": {"prerequisites": name}})
db.concepts.update_many({"related": name}, {"$pull": {"related": name}})
db.learning_resources.update_many({"concepts": name}, {"$pull": {"concepts": name}})
```

---

## 6. Aggregation Pipelines

All five analytics queries use MongoDB's aggregation framework. No collection data is loaded into Python for computation.

### Pipeline 1 — Concepts per Domain
Stages: `$group` (count by domain) → `$sort` (descending) → `$project` (rename fields).

### Pipeline 2 — Most-Connected Concepts
Stages: `$project` (compute degree as `$add` of two `$size` values) → `$sort` → `$limit`.  
*Demonstrates computed fields in `$project` and `$size` array operator.*

### Pipeline 3 — Domains Ranked
Same as Pipeline 1; separated for clarity in the report. Demonstrates reuse of the `$group/$sort` pattern.

### Pipeline 4 — Resource Counts by Type
Stages: `$group` (count by `resource_type`) → `$sort` → `$project`.

### Pipeline 5 — Concepts with Most Resources (`$lookup`)
Stages: `$unwind` (explode concepts array) → `$group` (count per concept) → `$sort` → `$limit` → `$lookup` (join concept document for domain) → `$project`.  
*Demonstrates cross-collection join, `$unwind`, and `$lookup`.*

### Sample Output (seed data, 35 concepts, 15 resources)

| Pipeline | Sample result |
|---|---|
| 1 | DSA: 12, Databases: 10, Networking: 6, Machine Learning: 6... (approx.) |
| 2 | Graph Traversal degree 4, Dynamic Programming degree 4 |
| 4 | Tutorial: 7, Documentation: 5, Paper: 3 |
| 5 | MongoDB Aggregation appears in 3 resources |

> **Note:** Exact numbers depend on seed data. Run `seed.py` and visit the Analytics tab for live results.

---

## 7. PyMongo Integration

PyMongo is the sole database driver. Key integration patterns:

- **`MongoClient` caching** via `@st.cache_resource` ensures a single connection across Streamlit re-renders.
- **Collection validators** applied via `create_collection()` and `db.command("collMod", ...)`.
- **Unique index** created with `create_index([("name", ASCENDING)], unique=True)`.
- **`DuplicateKeyError`** and `OperationFailure` are caught and surfaced as user-friendly Streamlit messages.
- **`ObjectId`** used as resource primary key; converted from string for edit/delete operations.

---

## 8. Application-Level Integrity

Since MongoDB does not enforce foreign-key constraints:

| Check | Implementation |
|---|---|
| Self-reference | `if name in prerequisites` |
| Unknown references | Compare against `all_concept_names(db)` |
| Prerequisite cycles | BFS from new prerequisites, checking if `start` is reachable |
| Cascade delete | `update_many` with `$pull` after `delete_one` |
| Confirmation for destructive ops | Streamlit `st.checkbox` gate before delete buttons |

---

## 9. Limitations

1. **No foreign key enforcement at DB level** — MongoDB does not prevent dangling references; application checks are run only on write through the UI. Direct driver manipulation bypasses them.
2. **Cycle detection is local** — The BFS cycle check works for simple chains but may produce false negatives in very complex multi-hop cycles if the graph is large and the adjacency is partially stale during a batch insert.
3. **No authentication** — The app assumes a trusted local or Atlas connection; user auth is outside scope.
4. **Graphviz binary dependency** — The relationship graph requires the Graphviz system package. If absent, the app falls back to a text list.
5. **Single-process Streamlit** — Concurrent edits from multiple browser tabs may cause race conditions on aggregations; acceptable for a demo.

---

## 10. Conclusion

Concept Constellation demonstrates that MongoDB's document model is a natural fit for flexible, schema-evolving graph-adjacent data. Embedded arrays deliver fast single-document reads; `$jsonSchema` validators enforce structural correctness; aggregation pipelines provide rich analytics without loading data into Python; and PyMongo's straightforward API keeps the codebase compact and readable. The project fulfills all course objectives within approximately 500 lines of application code.
