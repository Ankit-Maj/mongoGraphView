# Concept Constellation — Viva Presentation Outline

**Course:** Intelligent NoSQL Databases  
**Duration:** ~10 minutes + Q&A  

---

## Slide 1 — Introduction (1 min)

- **Project name:** Concept Constellation
- **One-liner:** A lightweight knowledge graph explorer for technical concepts, built with MongoDB, PyMongo, and Streamlit.
- **Core claim:** MongoDB's document model is a natural fit for graph-adjacent, schema-flexible data like a concept dependency map.

---

## Slide 2 — Problem & Motivation (1 min)

- Technical knowledge is graph-structured (prerequisites, cross-domain links).
- Relational tables require multiple joins; graph DBs add infrastructure overhead.
- MongoDB embedded arrays give fast reads with manageable write-time checks.

---

## Slide 3 — Data Model (2 min)

Show both document structures:

```
concepts            { name, domain, definition, prerequisites[], related[] }
learning_resources  { title, url, concepts[], resource_type }
```

- **Why embedded arrays?** Single-document reads, no join overhead for common queries.
- **Trade-off:** Application-level referential integrity instead of DB-enforced foreign keys.

---

## Slide 4 — Schema Validation & Indexing (1 min)

- `$jsonSchema` validator: required fields, BSON types, URL regex, `resource_type` enum.
- Unique index on `concepts.name`.
- **Live demo:** Attempt to insert a document missing required fields → `OperationFailure`.

---

## Slide 5 — CRUD Operations (2 min)

Walk through the Streamlit CRUD tab:

1. **Create** a new concept (show `insert_one`, prerequisite validation, cycle check).
2. **Read** it in the Explore tab (show `find_one`, resource lookup via `find`).
3. **Update** a field (show `update_one` with `$set`).
4. **Delete** it (show `delete_one` + cascade `update_many` with `$pull`).

Mention `insert_many` used in seed script via upsert pattern.

---

## Slide 6 — Aggregation Pipelines (2 min)

Show the Analytics tab with five pipelines:

| # | Question | Key stages |
|---|---|---|
| 1 | Concepts per domain | `$group`, `$sort`, `$project` |
| 2 | Most-connected concepts | `$project` + `$size`, `$sort`, `$limit` |
| 3 | Domains ranked | same as #1 |
| 4 | Resources by type | `$group`, `$sort` |
| 5 | Concepts with most resources | `$unwind`, `$group`, `$lookup`, `$project` |

Emphasize Pipeline 5 — cross-collection join using `$lookup`.

---

## Slide 7 — Relationship Graph (1 min)

- Graphviz Digraph: prerequisite edges (solid), related edges (dashed, bidirectional).
- Domain-colored nodes.
- Filter by domain.
- Fallback text list if Graphviz binary is unavailable.

---

## Slide 8 — Application Integrity Checks (30 sec)

- Self-reference prevention.
- Unknown reference detection.
- BFS cycle detection for prerequisites.
- Cascading delete cleanup.
- Confirmation checkbox before destructive operations.

---

## Slide 9 — Limitations & Future Work (30 sec)

- No DB-level referential integrity (MongoDB design trade-off).
- No authentication / multi-user support.
- Graphviz binary required for graph view.
- Future: change streams for live updates, Atlas Search for concept search.

---

## Slide 10 — Summary (30 sec)

- MongoDB document model → flexible, fast knowledge graph storage.
- PyMongo → direct, readable database operations.
- Aggregation pipelines → powerful analytics without loading data into Python.
- Streamlit → rapid functional UI with minimal boilerplate.
- ~500 lines of application code, 6 project files.

---

## Anticipated Q&A

**Q: Why not use a graph database like Neo4j?**  
A: For this scale, MongoDB's embedded arrays are sufficient and avoid infrastructure overhead. Neo4j excels at multi-hop traversals across millions of nodes.

**Q: Why not normalize concepts into a separate edges collection?**  
A: The access pattern is "get a concept and all its neighbors in one read." Embedding optimizes for this at the cost of referential integrity, which the app layer handles.

**Q: How does the cycle detection work?**  
A: BFS from the proposed prerequisites, checking if we can reach the concept being edited. If yes, a cycle exists and the update is rejected.

**Q: What happens if you insert directly via mongosh bypassing the app?**  
A: The `$jsonSchema` validator still enforces required fields and types. The unique index still prevents duplicates. Application-level checks (cycles, unknown refs) would be bypassed.

**Q: How would you scale this to 10,000 concepts?**  
A: Add compound indexes on `domain` and `prerequisites`, use Atlas Search for full-text lookup, paginate `find()` results, and consider partial graph loading in the visualization.
