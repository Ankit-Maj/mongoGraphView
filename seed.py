"""
seed.py — Concept Constellation seed script
Run once (or repeatedly) to populate the database without creating duplicates.
Uses insert_many() for batch inserts and update_one(upsert=True) for idempotency.
"""

import os, sys
# Ensure UTF-8 output on Windows terminals that default to cp1252
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pymongo import MongoClient, ASCENDING
from pymongo.errors import BulkWriteError, OperationFailure
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "concept_constellation")

CONCEPTS = [
    # ── DSA ──────────────────────────────────────────────────────────────────
    {"name": "Array", "domain": "DSA", "definition": "Contiguous block of memory storing elements of the same type.", "prerequisites": [], "related": ["Linked List", "Dynamic Programming"]},
    {"name": "Linked List", "domain": "DSA", "definition": "Linear data structure where elements point to the next.", "prerequisites": ["Array"], "related": ["Array", "Stack", "Queue"]},
    {"name": "Stack", "domain": "DSA", "definition": "LIFO data structure supporting push and pop operations.", "prerequisites": ["Linked List"], "related": ["Queue", "Recursion"]},
    {"name": "Queue", "domain": "DSA", "definition": "FIFO data structure supporting enqueue and dequeue.", "prerequisites": ["Linked List"], "related": ["Stack", "Graph Traversal"]},
    {"name": "Binary Tree", "domain": "DSA", "definition": "Hierarchical structure where each node has at most two children.", "prerequisites": ["Array", "Linked List"], "related": ["Binary Search Tree", "Heap"]},
    {"name": "Binary Search Tree", "domain": "DSA", "definition": "Binary tree with ordered left/right subtree property.", "prerequisites": ["Binary Tree"], "related": ["Binary Tree", "Balanced BST"]},
    {"name": "Balanced BST", "domain": "DSA", "definition": "Self-balancing BST (AVL, Red-Black) guaranteeing O(log n) ops.", "prerequisites": ["Binary Search Tree"], "related": ["Binary Search Tree", "Heap"]},
    {"name": "Heap", "domain": "DSA", "definition": "Complete binary tree satisfying heap property; used in priority queues.", "prerequisites": ["Binary Tree"], "related": ["Binary Tree", "Graph Traversal"]},
    {"name": "Graph Traversal", "domain": "DSA", "definition": "BFS and DFS algorithms for visiting graph nodes.", "prerequisites": ["Queue", "Stack"], "related": ["Shortest Path", "Dynamic Programming"]},
    {"name": "Shortest Path", "domain": "DSA", "definition": "Dijkstra and Bellman-Ford algorithms for minimum-cost paths.", "prerequisites": ["Graph Traversal", "Heap"], "related": ["Graph Traversal", "Dynamic Programming"]},
    {"name": "Dynamic Programming", "domain": "DSA", "definition": "Optimization technique breaking problems into overlapping subproblems.", "prerequisites": ["Recursion"], "related": ["Graph Traversal", "Shortest Path"]},
    {"name": "Recursion", "domain": "DSA", "definition": "Function calling itself with a base case to avoid infinite loops.", "prerequisites": [], "related": ["Stack", "Dynamic Programming"]},

    # ── Databases ─────────────────────────────────────────────────────────────
    {"name": "Relational Model", "domain": "Databases", "definition": "Data organized in tables with rows and columns governed by SQL.", "prerequisites": [], "related": ["SQL", "Normalization", "NoSQL"]},
    {"name": "SQL", "domain": "Databases", "definition": "Structured Query Language for managing relational databases.", "prerequisites": ["Relational Model"], "related": ["Relational Model", "Indexes"]},
    {"name": "Normalization", "domain": "Databases", "definition": "Process of organizing data to reduce redundancy via normal forms.", "prerequisites": ["Relational Model"], "related": ["Relational Model", "SQL"]},
    {"name": "Indexes", "domain": "Databases", "definition": "Data structures that speed up query execution at the cost of write overhead.", "prerequisites": ["SQL"], "related": ["SQL", "Query Optimization", "MongoDB Aggregation"]},
    {"name": "NoSQL", "domain": "Databases", "definition": "Non-relational databases offering flexible schemas and horizontal scalability.", "prerequisites": ["Relational Model"], "related": ["Relational Model", "Document Model", "CAP Theorem"]},
    {"name": "Document Model", "domain": "Databases", "definition": "Stores data as JSON-like documents, enabling nested and array fields.", "prerequisites": ["NoSQL"], "related": ["NoSQL", "MongoDB Aggregation", "Schema Design"]},
    {"name": "Schema Design", "domain": "Databases", "definition": "Planning document structure, embedding vs referencing, and validation rules.", "prerequisites": ["Document Model"], "related": ["Document Model", "Normalization"]},
    {"name": "MongoDB Aggregation", "domain": "Databases", "definition": "Pipeline-based framework for transforming and analyzing documents.", "prerequisites": ["Document Model", "Indexes"], "related": ["Document Model", "Query Optimization"]},
    {"name": "Query Optimization", "domain": "Databases", "definition": "Techniques to reduce query execution time through indexes and plans.", "prerequisites": ["Indexes"], "related": ["Indexes", "MongoDB Aggregation"]},
    {"name": "CAP Theorem", "domain": "Databases", "definition": "Distributed systems can guarantee at most two of: Consistency, Availability, Partition tolerance.", "prerequisites": ["NoSQL"], "related": ["NoSQL", "Distributed Systems"]},

    # ── Networking ────────────────────────────────────────────────────────────
    {"name": "OSI Model", "domain": "Networking", "definition": "Seven-layer conceptual framework for network protocol design.", "prerequisites": [], "related": ["TCP/IP", "HTTP"]},
    {"name": "TCP/IP", "domain": "Networking", "definition": "Core internet protocol suite for reliable data transmission.", "prerequisites": ["OSI Model"], "related": ["OSI Model", "HTTP", "DNS"]},
    {"name": "HTTP", "domain": "Networking", "definition": "Application-layer protocol for hypermedia document transfer.", "prerequisites": ["TCP/IP"], "related": ["TCP/IP", "REST API", "DNS"]},
    {"name": "DNS", "domain": "Networking", "definition": "Distributed naming system translating domain names to IP addresses.", "prerequisites": ["TCP/IP"], "related": ["TCP/IP", "HTTP"]},
    {"name": "REST API", "domain": "Networking", "definition": "Architectural style for distributed systems using HTTP verbs.", "prerequisites": ["HTTP"], "related": ["HTTP", "Document Model"]},
    {"name": "Distributed Systems", "domain": "Networking", "definition": "Systems where components on networked computers communicate and coordinate.", "prerequisites": ["TCP/IP", "CAP Theorem"], "related": ["CAP Theorem", "NoSQL"]},

    # ── Machine Learning ──────────────────────────────────────────────────────
    {"name": "Linear Regression", "domain": "Machine Learning", "definition": "Supervised model predicting continuous output as a linear function of inputs.", "prerequisites": [], "related": ["Gradient Descent", "Overfitting"]},
    {"name": "Gradient Descent", "domain": "Machine Learning", "definition": "Iterative optimization algorithm minimizing a loss function.", "prerequisites": ["Linear Regression"], "related": ["Linear Regression", "Neural Networks"]},
    {"name": "Overfitting", "domain": "Machine Learning", "definition": "Model captures training noise, failing to generalize to new data.", "prerequisites": ["Linear Regression"], "related": ["Linear Regression", "Cross Validation"]},
    {"name": "Cross Validation", "domain": "Machine Learning", "definition": "Technique splitting data into folds to estimate model generalization.", "prerequisites": ["Overfitting"], "related": ["Overfitting", "Decision Trees"]},
    {"name": "Decision Trees", "domain": "Machine Learning", "definition": "Tree-based model splitting data on feature thresholds.", "prerequisites": ["Cross Validation"], "related": ["Cross Validation", "Dynamic Programming"]},
    {"name": "Neural Networks", "domain": "Machine Learning", "definition": "Layered computational graphs inspired by biological neurons.", "prerequisites": ["Gradient Descent"], "related": ["Gradient Descent", "Graph Traversal"]},
]

LEARNING_RESOURCES = [
    {"title": "Introduction to Algorithms (CLRS)", "url": "https://mitpress.mit.edu/9780262046305/introduction-to-algorithms/", "concepts": ["Dynamic Programming", "Graph Traversal", "Shortest Path", "Heap"], "resource_type": "Documentation"},
    {"title": "MongoDB Official Documentation", "url": "https://www.mongodb.com/docs/", "concepts": ["Document Model", "MongoDB Aggregation", "Schema Design", "Indexes"], "resource_type": "Documentation"},
    {"title": "Visualgo — Data Structure Visualizations", "url": "https://visualgo.net/", "concepts": ["Array", "Linked List", "Binary Search Tree", "Heap", "Graph Traversal"], "resource_type": "Tutorial"},
    {"title": "PyMongo Tutorial", "url": "https://pymongo.readthedocs.io/en/stable/tutorial.html", "concepts": ["MongoDB Aggregation", "Document Model"], "resource_type": "Tutorial"},
    {"title": "The Little MongoDB Book", "url": "https://github.com/karlseguin/the-little-mongodb-book", "concepts": ["Document Model", "Schema Design", "NoSQL"], "resource_type": "Documentation"},
    {"title": "Designing Data-Intensive Applications (Kleppmann)", "url": "https://dataintensive.net/", "concepts": ["CAP Theorem", "Distributed Systems", "Indexes", "Normalization"], "resource_type": "Paper"},
    {"title": "CS50 Introduction to Computer Science", "url": "https://cs50.harvard.edu/", "concepts": ["Array", "Recursion", "Stack", "Queue", "SQL"], "resource_type": "Tutorial"},
    {"title": "Stanford ML Course (Andrew Ng)", "url": "https://www.coursera.org/specializations/machine-learning-introduction", "concepts": ["Linear Regression", "Gradient Descent", "Overfitting", "Neural Networks"], "resource_type": "Tutorial"},
    {"title": "Database System Concepts (Silberschatz)", "url": "https://www.db-book.com/", "concepts": ["Relational Model", "SQL", "Normalization", "Query Optimization"], "resource_type": "Documentation"},
    {"title": "Computer Networking: A Top-Down Approach", "url": "https://gaia.cs.umass.edu/kurose_ross/", "concepts": ["OSI Model", "TCP/IP", "HTTP", "DNS"], "resource_type": "Documentation"},
    {"title": "MongoDB Aggregation Pipeline (Tutorial)", "url": "https://www.mongodb.com/docs/manual/aggregation/", "concepts": ["MongoDB Aggregation", "Indexes", "Query Optimization"], "resource_type": "Tutorial"},
    {"title": "Deep Learning (Goodfellow et al.)", "url": "https://www.deeplearningbook.org/", "concepts": ["Neural Networks", "Gradient Descent", "Overfitting"], "resource_type": "Paper"},
    {"title": "RESTful Web APIs (Richardson)", "url": "https://www.oreilly.com/library/view/restful-web-apis/9781449359713/", "concepts": ["REST API", "HTTP"], "resource_type": "Documentation"},
    {"title": "NoSQL Distilled (Fowler)", "url": "https://martinfowler.com/books/nosql.html", "concepts": ["NoSQL", "Document Model", "CAP Theorem"], "resource_type": "Paper"},
    {"title": "Programiz DSA Tutorials", "url": "https://www.programiz.com/dsa", "concepts": ["Stack", "Queue", "Binary Tree", "Binary Search Tree", "Balanced BST"], "resource_type": "Tutorial"},
]


def get_db():
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client[DB_NAME]


def setup_collections(db):
    """Create collections with $jsonSchema validators and unique index."""
    existing = db.list_collection_names()

    concepts_validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["name", "domain", "definition", "prerequisites", "related"],
            "properties": {
                "name":         {"bsonType": "string", "minLength": 1},
                "domain":       {"bsonType": "string", "minLength": 1},
                "definition":   {"bsonType": "string", "minLength": 1},
                "prerequisites":{"bsonType": "array", "items": {"bsonType": "string"}},
                "related":      {"bsonType": "array", "items": {"bsonType": "string"}},
            },
        }
    }

    resources_validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["title", "url", "concepts", "resource_type"],
            "properties": {
                "title":         {"bsonType": "string", "minLength": 1},
                "url":           {"bsonType": "string", "pattern": "^https?://"},
                "concepts":      {"bsonType": "array", "items": {"bsonType": "string"}},
                "resource_type": {"bsonType": "string", "enum": ["Tutorial", "Documentation", "Paper"]},
            },
        }
    }

    if "concepts" not in existing:
        db.create_collection("concepts", validator=concepts_validator)
        print("  Created 'concepts' collection with validator.")
    else:
        # Update validator in case it changed
        try:
            db.command("collMod", "concepts", validator=concepts_validator)
            print("  Updated 'concepts' validator.")
        except OperationFailure as e:
            print(f"  Warning: could not update concepts validator: {e}")

    if "learning_resources" not in existing:
        db.create_collection("learning_resources", validator=resources_validator)
        print("  Created 'learning_resources' collection with validator.")
    else:
        try:
            db.command("collMod", "learning_resources", validator=resources_validator)
            print("  Updated 'learning_resources' validator.")
        except OperationFailure as e:
            print(f"  Warning: could not update resources validator: {e}")

    # Unique index on concepts.name
    db.concepts.create_index([("name", ASCENDING)], unique=True)
    print("  Ensured unique index on concepts.name.")


def seed_concepts(db):
    """Upsert concepts by name (idempotent)."""
    upserted = skipped = 0
    for c in CONCEPTS:
        result = db.concepts.update_one(
            {"name": c["name"]},
            {"$setOnInsert": c},
            upsert=True,
        )
        if result.upserted_id:
            upserted += 1
        else:
            skipped += 1
    print(f"  Concepts: {upserted} inserted, {skipped} already existed.")


def seed_resources(db):
    """Upsert resources by title (idempotent)."""
    upserted = skipped = 0
    for r in LEARNING_RESOURCES:
        result = db.learning_resources.update_one(
            {"title": r["title"]},
            {"$setOnInsert": r},
            upsert=True,
        )
        if result.upserted_id:
            upserted += 1
        else:
            skipped += 1
    print(f"  Resources: {upserted} inserted, {skipped} already existed.")


def demo_validation(db):
    """
    Demonstrate MongoDB schema validation by attempting an invalid insert.
    This is intentionally expected to fail.
    """
    print("\n  [Validation Demo] Attempting invalid insert (missing required fields)…")
    try:
        db.concepts.insert_one({"name": "Bad Doc"})  # missing domain, definition, etc.
        print("  ERROR: Invalid document was accepted — validator may not be active.")
    except OperationFailure as e:
        print(f"  ✓ Validation correctly rejected invalid document: {e.details.get('errmsg', str(e))}")

    print("  [Validation Demo] Attempting invalid resource_type enum value…")
    try:
        db.learning_resources.insert_one({
            "title": "Bad Resource",
            "url": "https://example.com",
            "concepts": [],
            "resource_type": "Video",   # not in enum
        })
        print("  ERROR: Invalid resource_type was accepted.")
    except OperationFailure as e:
        print(f"  ✓ Validation correctly rejected invalid resource_type: {e.details.get('errmsg', str(e))}")


if __name__ == "__main__":
    print("Concept Constellation — Seed Script")
    print("=" * 40)
    try:
        db = get_db()
        print("✓ Connected to MongoDB.")
    except Exception as e:
        print(f"✗ Could not connect to MongoDB: {e}")
        print("  Make sure MongoDB is running and MONGODB_URI is set in your .env file.")
        raise SystemExit(1)

    print("\nSetting up collections and indexes…")
    setup_collections(db)

    print("\nSeeding data…")
    seed_concepts(db)
    seed_resources(db)

    demo_validation(db)

    print("\n✓ Seed complete.")
    total_concepts = db.concepts.count_documents({})
    total_resources = db.learning_resources.count_documents({})
    print(f"  Total concepts   : {total_concepts}")
    print(f"  Total resources  : {total_resources}")
