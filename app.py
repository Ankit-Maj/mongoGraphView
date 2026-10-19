"""
app.py  --  Concept Constellation
Knowledge graph explorer backed by MongoDB/PyMongo.

Sections:
  1. DB helpers  (connection, collection init, validation)
  2. Integrity helpers (reference checks, cycle detection)
  3. CRUD helpers -- Concepts
  4. CRUD helpers -- Resources
  5. Aggregation pipelines
  6. Graph helpers  (PyVis interactive + Graphviz static fallback)
  7. Streamlit page config + CSS
  8. Session state init
  9. DB connection
  10. Sidebar
  11. Inspector helper
  12. Section: Graph workspace
  13. Section: Explore
  14. Section: Resources
  15. Section: Analytics
  16. Section: Manage (CRUD)
"""

import os, re, sys, json, tempfile, pathlib
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import streamlit as st
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError, OperationFailure
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# 1. DB helpers
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DB_NAME     = os.getenv("DB_NAME", "concept_constellation")

DOMAINS        = ["DSA", "Databases", "Networking", "Machine Learning"]
RESOURCE_TYPES = ["Tutorial", "Documentation", "Paper"]

DOMAIN_COLORS = {
    "DSA":              "#B27A42",   # ochre
    "Databases":        "#8C3428",   # burgundy
    "Networking":       "#49624A",   # forest green
    "Machine Learning": "#77758E",   # dusty violet
}
DOMAIN_FALLBACK = "#567A78"           # muted teal

RESOURCE_TYPE_COLORS = {
    "Tutorial":      "#8C3428",
    "Documentation": "#49624A",
    "Paper":         "#77758E",
}


@st.cache_resource(show_spinner=False)
def get_db():
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[DB_NAME]
    _ensure_collections(db)
    return db


def _ensure_collections(db):
    existing = db.list_collection_names()
    concepts_validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["name", "domain", "definition", "prerequisites", "related"],
            "properties": {
                "name":          {"bsonType": "string", "minLength": 1},
                "domain":        {"bsonType": "string", "minLength": 1},
                "definition":    {"bsonType": "string", "minLength": 1},
                "prerequisites": {"bsonType": "array", "items": {"bsonType": "string"}},
                "related":       {"bsonType": "array", "items": {"bsonType": "string"}},
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
                "resource_type": {"bsonType": "string", "enum": RESOURCE_TYPES},
            },
        }
    }
    for cname, validator in [("concepts", concepts_validator),
                               ("learning_resources", resources_validator)]:
        if cname not in existing:
            db.create_collection(cname, validator=validator)
        else:
            try:
                db.command("collMod", cname, validator=validator)
            except OperationFailure:
                pass
    db.concepts.create_index([("name", ASCENDING)], unique=True)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Integrity helpers
# ─────────────────────────────────────────────────────────────────────────────

def all_concept_names(db) -> list[str]:
    return [c["name"] for c in db.concepts.find({}, {"name": 1, "_id": 0}).sort("name")]


def _validate_refs(db, name: str, prerequisites: list, related: list) -> list[str]:
    errors = []
    known = set(all_concept_names(db))
    if name in prerequisites:
        errors.append("A concept cannot list itself as a prerequisite.")
    if name in related:
        errors.append("A concept cannot list itself as related.")
    missing_pre = [p for p in prerequisites if p not in known and p != name]
    missing_rel = [r for r in related if r not in known and r != name]
    if missing_pre:
        errors.append(f"Unknown prerequisites: {', '.join(missing_pre)}")
    if missing_rel:
        errors.append(f"Unknown related concepts: {', '.join(missing_rel)}")
    return errors


def _has_cycle(db, start: str, prereqs: list[str]) -> bool:
    adj: dict[str, list] = {}
    for c in db.concepts.find({}, {"name": 1, "prerequisites": 1, "_id": 0}):
        adj[c["name"]] = c.get("prerequisites", [])
    adj[start] = prereqs
    visited, queue = set(), list(prereqs)
    while queue:
        node = queue.pop()
        if node == start:
            return True
        if node in visited:
            continue
        visited.add(node)
        queue.extend(adj.get(node, []))
    return False


def _validate_resource_refs(db, concepts: list[str]) -> list[str]:
    known = set(all_concept_names(db))
    missing = [c for c in concepts if c not in known]
    if missing:
        return [f"Unknown concepts in resource: {', '.join(missing)}"]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 3. CRUD helpers -- Concepts
# ─────────────────────────────────────────────────────────────────────────────

def create_concept(db, name, domain, definition, prerequisites, related):
    errors = _validate_refs(db, name, prerequisites, related)
    if errors:
        return False, "; ".join(errors)
    if _has_cycle(db, name, prerequisites):
        return False, "Adding these prerequisites would create a cycle."
    doc = {"name": name, "domain": domain, "definition": definition,
           "prerequisites": prerequisites, "related": related}
    try:
        db.concepts.insert_one(doc)
        return True, f"Concept '{name}' created."
    except DuplicateKeyError:
        return False, f"Concept '{name}' already exists."
    except OperationFailure as e:
        return False, str(e)


def read_concept(db, name):
    return db.concepts.find_one({"name": name}, {"_id": 0})


def update_concept(db, name, domain, definition, prerequisites, related):
    errors = _validate_refs(db, name, prerequisites, related)
    if errors:
        return False, "; ".join(errors)
    if _has_cycle(db, name, prerequisites):
        return False, "These prerequisites would create a cycle."
    try:
        result = db.concepts.update_one(
            {"name": name},
            {"$set": {"domain": domain, "definition": definition,
                      "prerequisites": prerequisites, "related": related}},
        )
        if result.matched_count == 0:
            return False, f"Concept '{name}' not found."
        return True, f"Concept '{name}' updated."
    except OperationFailure as e:
        return False, str(e)


def delete_concept(db, name):
    result = db.concepts.delete_one({"name": name})
    if result.deleted_count == 0:
        return False, f"Concept '{name}' not found."
    db.concepts.update_many({"prerequisites": name}, {"$pull": {"prerequisites": name}})
    db.concepts.update_many({"related": name}, {"$pull": {"related": name}})
    db.learning_resources.update_many({"concepts": name}, {"$pull": {"concepts": name}})
    return True, f"Concept '{name}' deleted and references cleaned up."


# ─────────────────────────────────────────────────────────────────────────────
# 4. CRUD helpers -- Resources
# ─────────────────────────────────────────────────────────────────────────────

def create_resource(db, title, url, concepts, resource_type):
    errors = _validate_resource_refs(db, concepts)
    if errors:
        return False, "; ".join(errors)
    if not re.match(r"^https?://", url):
        return False, "URL must start with http:// or https://"
    doc = {"title": title, "url": url, "concepts": concepts, "resource_type": resource_type}
    try:
        db.learning_resources.insert_one(doc)
        return True, f"Resource '{title}' created."
    except OperationFailure as e:
        return False, str(e)


def update_resource(db, resource_id, title, url, concepts, resource_type):
    from bson import ObjectId
    errors = _validate_resource_refs(db, concepts)
    if errors:
        return False, "; ".join(errors)
    try:
        result = db.learning_resources.update_one(
            {"_id": ObjectId(resource_id)},
            {"$set": {"title": title, "url": url,
                      "concepts": concepts, "resource_type": resource_type}},
        )
        if result.matched_count == 0:
            return False, "Resource not found."
        return True, "Resource updated."
    except OperationFailure as e:
        return False, str(e)


def delete_resource(db, resource_id):
    from bson import ObjectId
    result = db.learning_resources.delete_one({"_id": ObjectId(resource_id)})
    if result.deleted_count == 0:
        return False, "Resource not found."
    return True, "Resource deleted."


# ─────────────────────────────────────────────────────────────────────────────
# 5. Aggregation pipelines
# ─────────────────────────────────────────────────────────────────────────────

def agg_concepts_per_domain(db):
    return list(db.concepts.aggregate([
        {"$group":   {"_id": "$domain", "count": {"$sum": 1}}},
        {"$sort":    {"count": -1}},
        {"$project": {"domain": "$_id", "count": 1, "_id": 0}},
    ]))


def agg_most_connected(db):
    return list(db.concepts.aggregate([
        {"$project": {
            "name": 1,
            "degree": {"$add": [{"$size": "$prerequisites"}, {"$size": "$related"}]},
            "_id": 0,
        }},
        {"$sort":  {"degree": -1}},
        {"$limit": 10},
    ]))


def agg_domains_ranked(db):
    return list(db.concepts.aggregate([
        {"$group":   {"_id": "$domain", "concept_count": {"$sum": 1}}},
        {"$sort":    {"concept_count": -1}},
        {"$project": {"domain": "$_id", "concept_count": 1, "_id": 0}},
    ]))


def agg_resource_type_counts(db):
    return list(db.learning_resources.aggregate([
        {"$group":   {"_id": "$resource_type", "count": {"$sum": 1}}},
        {"$sort":    {"count": -1}},
        {"$project": {"resource_type": "$_id", "count": 1, "_id": 0}},
    ]))


def agg_concepts_with_most_resources(db):
    return list(db.learning_resources.aggregate([
        {"$unwind": "$concepts"},
        {"$group":  {"_id": "$concepts", "resource_count": {"$sum": 1}}},
        {"$sort":   {"resource_count": -1}},
        {"$limit":  10},
        {"$lookup": {
            "from":         "concepts",
            "localField":   "_id",
            "foreignField": "name",
            "as":           "concept_doc",
        }},
        {"$project": {
            "concept":        "$_id",
            "resource_count": 1,
            "domain": {"$arrayElemAt": ["$concept_doc.domain", 0]},
            "_id": 0,
        }},
    ]))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Graph helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_graph_data(db, filter_domains=None, show_prereq=True, show_related=True,
                    focus_concept=None):
    query = {"domain": {"$in": filter_domains}} if filter_domains else {}
    concepts = list(db.concepts.find(query, {"_id": 0}))
    concept_set = {c["name"] for c in concepts}

    if focus_concept:
        focus_doc = db.concepts.find_one({"name": focus_concept}, {"_id": 0})
        if focus_doc:
            if focus_concept not in concept_set:
                concepts.append(focus_doc)
                concept_set.add(focus_concept)
            neighbors = set(focus_doc.get("prerequisites", []) +
                            focus_doc.get("related", []))
            extra = [c for c in db.concepts.find(
                {"name": {"$in": list(neighbors)}}, {"_id": 0}
            ) if c["name"] not in concept_set]
            concepts += extra
            concept_set = {c["name"] for c in concepts}

    nodes = []
    for c in concepts:
        color = DOMAIN_COLORS.get(c["domain"], DOMAIN_FALLBACK)
        size  = 14 + min(len(c.get("prerequisites", [])) + len(c.get("related", [])), 6) * 2
        is_focus = (c["name"] == focus_concept)
        nodes.append({
            "id":     c["name"],
            "label":  c["name"],
            "color":  "#ffffff" if is_focus else color,
            "size":   22 if is_focus else size,
            "domain": c["domain"],
            "border": "#ffffff" if is_focus else color,
        })

    prereq_edges, related_edges = [], []
    seen_related = set()

    if show_prereq:
        for c in concepts:
            for pre in c.get("prerequisites", []):
                if pre in concept_set and pre != c["name"]:
                    prereq_edges.append({"from": pre, "to": c["name"]})

    if show_related:
        for c in concepts:
            for rel in c.get("related", []):
                pair = tuple(sorted([c["name"], rel]))
                if rel in concept_set and rel != c["name"] and pair not in seen_related:
                    seen_related.add(pair)
                    related_edges.append({"from": c["name"], "to": rel})

    return nodes, prereq_edges, related_edges, concept_set


def build_pyvis_graph(nodes, prereq_edges, related_edges, height="580px"):
    from pyvis.network import Network
    # Warm parchment canvas, ink-colored labels
    net = Network(height=height, width="100%", bgcolor="#F4EFE5",
                  font_color="#292820", directed=True)
    net.set_options(json.dumps({
        "nodes": {
            "font": {"size": 12, "face": "'Source Sans 3', 'Lato', sans-serif",
                     "color": "#292820"},
            "borderWidth": 2,
            "borderWidthSelected": 3,
            "shadow": {"enabled": True, "size": 5,
                       "color": "rgba(120,100,80,0.18)"},
        },
        "edges": {
            "smooth": {"type": "dynamic"},
            "shadow": False,
        },
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -35,
                "centralGravity": 0.005,
                "springLength": 120,
                "springConstant": 0.08,
                "damping": 0.4,
            },
            "solver": "forceAtlas2Based",
            "stabilization": {"iterations": 150},
        },
        "interaction": {
            "hover": True,
            "tooltipDelay": 150,
            "navigationButtons": False,
            "keyboard": {"enabled": True},
        },
        "layout": {"improvedLayout": True},
    }))
    for n in nodes:
        is_focus = n.get("border") != n["color"]  # focus nodes have different border
        base_color = n["color"]
        border_color = "#8C3428" if is_focus else base_color  # burgundy halo for focus
        # Lighten node fill slightly for legibility on parchment
        net.add_node(
            n["id"],
            label=n["label"],
            color={"background": base_color,
                   "border": border_color,
                   "highlight": {"background": "#8C3428", "border": "#8C3428"},
                   "hover":     {"background": base_color, "border": "#8C3428"}},
            size=n["size"],
            font={"color": "#FBF8F1", "size": 12,
                  "face": "'Source Sans 3', 'Lato', sans-serif"},
            title=f"{n['id']}  |  {n['domain']}",
        )
    # Prerequisite edges: warm brown, solid, directed
    for e in prereq_edges:
        net.add_edge(e["from"], e["to"],
                     color={"color": "rgba(140,100,60,0.50)",
                            "highlight": "rgba(140,52,40,0.85)"},
                     width=1.4, arrows="to", title="prerequisite", dashes=False)
    # Related edges: light gray-brown, dashed, undirected
    for e in related_edges:
        net.add_edge(e["from"], e["to"],
                     color={"color": "rgba(160,145,120,0.30)",
                            "highlight": "rgba(140,52,40,0.60)"},
                     width=1, arrows="", title="related", dashes=[5, 5])
    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
    tmp.close()
    net.save_graph(tmp.name)
    html = pathlib.Path(tmp.name).read_text(encoding="utf-8")
    pathlib.Path(tmp.name).unlink(missing_ok=True)
    return html


def build_graphviz_fallback(db, filter_domains=None, show_prereq=True, show_related=True):
    try:
        import graphviz
    except ImportError:
        return None
    query = {"domain": {"$in": filter_domains}} if filter_domains else {}
    concepts = list(db.concepts.find(query, {"_id": 0}))
    concept_set = {c["name"] for c in concepts}
    g = graphviz.Digraph(
        graph_attr={"bgcolor": "#F4EFE5", "rankdir": "LR",
                    "fontname": "Helvetica", "splines": "curved"},
        node_attr={"shape": "box", "style": "filled,rounded",
                   "fontname": "Helvetica", "fontsize": "10", "margin": "0.15,0.08"},
        edge_attr={"fontname": "Helvetica", "fontsize": "8"},
    )
    for c in concepts:
        color = DOMAIN_COLORS.get(c["domain"], DOMAIN_FALLBACK)
        g.node(c["name"], fillcolor=color, fontcolor="white", color=color + "aa")
    seen_related = set()
    for c in concepts:
        if show_prereq:
            for pre in c.get("prerequisites", []):
                if pre in concept_set and pre != c["name"]:
                    g.edge(pre, c["name"], color="rgba(180,190,210,0.6)")
        if show_related:
            for rel in c.get("related", []):
                pair = tuple(sorted([c["name"], rel]))
                if rel in concept_set and rel != c["name"] and pair not in seen_related:
                    seen_related.add(pair)
                    g.edge(c["name"], rel, color="rgba(140,155,180,0.35)",
                           style="dashed", dir="none")
    return g


# ─────────────────────────────────────────────────────────────────────────────
# 7. Streamlit page config + CSS
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Concept Constellation",
    page_icon="*",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=Source+Sans+3:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'Source Sans 3', 'Lato', Georgia, serif;
    font-size: 14px;
    color: #292820;
}
.stApp { background-color: #F4EFE5; color: #292820; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1rem; padding-bottom: 1rem; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background-color: #FBF8F1;
    border-right: 1px solid #D8D0C2;
    min-width: 220px !important;
    max-width: 240px !important;
}
section[data-testid="stSidebar"] > div { padding: 0; }

/* ── Masthead ── */
.nav-logo {
    padding: 20px 16px 14px;
    border-bottom: 2px solid #292820;
    margin-bottom: 8px;
}
.nav-logo-text {
    font-family: 'Playfair Display', 'Georgia', serif;
    font-size: 15px; font-weight: 700;
    color: #292820; letter-spacing: -0.01em;
    line-height: 1.2;
}
.nav-logo-sub {
    font-family: 'IBM Plex Mono', 'Courier New', monospace;
    font-size: 9px; color: #777064;
    letter-spacing: 0.12em; margin-top: 3px;
    text-transform: uppercase;
}

/* ── Nav items ── */
.nav-section { padding: 0 8px; margin-bottom: 2px; }
.nav-section-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px; font-weight: 500; color: #B0A898;
    letter-spacing: 0.1em; text-transform: uppercase;
    padding: 10px 8px 4px; display: block;
}

.stButton > button {
    width: 100%; text-align: left; justify-content: flex-start;
    background: transparent; color: #777064;
    border: none; border-radius: 3px;
    padding: 6px 10px; font-size: 13px; font-weight: 400;
    font-family: 'Source Sans 3', 'Lato', sans-serif;
    transition: background 0.12s, color 0.12s;
    cursor: pointer;
}
.stButton > button:hover { background: #EDE8DC; color: #292820; border: none; }
.nav-active .stButton > button {
    background: #F4EFE5 !important;
    color: #8C3428 !important;
    font-weight: 600 !important;
    border-left: 2px solid #8C3428 !important;
}

/* ── Sidebar filters ── */
.sidebar-divider { border: none; border-top: 1px solid #D8D0C2; margin: 8px 0; }
.filter-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px; font-weight: 500; color: #B0A898;
    letter-spacing: 0.1em; text-transform: uppercase;
    padding: 8px 16px 4px; display: block;
}

[data-testid="stCheckbox"] label {
    font-size: 12.5px; color: #777064;
    font-family: 'Source Sans 3', 'Lato', sans-serif;
    gap: 6px;
}
[data-testid="stCheckbox"] label:hover { color: #292820; }

/* ── Main content ── */
.stApp { background-color: #F4EFE5; color: #292820; }

/* ── Section headings ── */
.section-heading {
    font-family: 'Playfair Display', 'Georgia', serif;
    font-size: 18px; font-weight: 700; color: #292820;
    letter-spacing: -0.01em;
    margin-bottom: 14px; padding-bottom: 8px;
    border-bottom: 1px solid #D8D0C2;
}

/* ── Inspector panel ── */
.inspector-empty {
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    height: 400px; text-align: center; color: #B0A898;
}
.inspector-empty-icon { font-size: 28px; margin-bottom: 12px; opacity: 0.5; }
.inspector-empty-text {
    font-size: 13px; line-height: 1.7;
    font-family: 'Source Sans 3', 'Lato', sans-serif;
    color: #B0A898;
}

.inspector-name {
    font-family: 'Playfair Display', 'Georgia', serif;
    font-size: 20px; font-weight: 700; color: #292820;
    margin: 0 0 6px; line-height: 1.25;
}
.inspector-domain-badge {
    display: inline-block;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px; font-weight: 500; letter-spacing: 0.1em;
    text-transform: uppercase; padding: 2px 8px; border-radius: 2px;
    margin-bottom: 10px;
}
.inspector-definition {
    font-family: 'Source Sans 3', 'Lato', sans-serif;
    font-size: 14px; line-height: 1.7; color: #555048;
    margin-bottom: 12px; padding-bottom: 12px;
    border-bottom: 1px solid #D8D0C2;
}
.inspector-section-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px; font-weight: 500; color: #B0A898;
    letter-spacing: 0.1em; text-transform: uppercase;
    margin: 12px 0 6px;
    padding-bottom: 3px;
    border-bottom: 1px solid #EDE8DC;
}

/* ── Concept chips ── */
.concept-chip {
    display: inline-flex; align-items: center;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px; padding: 2px 8px; border-radius: 2px;
    border: 1px solid #D8D0C2; color: #555048;
    background: #FBF8F1; margin: 2px;
}
.concept-chip-pre {
    color: #49624A; border-color: #C5D1C6; background: #F2F5F2;
}
.concept-chip-rel {
    color: #8C3428; border-color: #DFC9C5; background: #FAF3F2;
}

/* ── Resource items ── */
.resource-item {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 8px 12px;
    background: #FBF8F1; border: 1px solid #D8D0C2;
    border-left: 3px solid #B0A898;
    margin-bottom: 5px;
}
.resource-type-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; margin-top: 6px; }
.resource-link {
    font-family: 'Source Sans 3', 'Lato', sans-serif;
    font-size: 13px; color: #8C3428; text-decoration: none; line-height: 1.5;
}
.resource-link:hover { color: #6B2620; text-decoration: underline; }
.resource-type-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px; color: #B0A898; display: block; margin-top: 1px;
    text-transform: uppercase; letter-spacing: 0.06em;
}

/* ── Graph toolbar ── */
.graph-toolbar {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 12px;
    background: #FBF8F1; border-bottom: 1px solid #D8D0C2;
}
.graph-toolbar-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; font-weight: 500; color: #B0A898;
    text-transform: uppercase; letter-spacing: 0.1em;
}
.graph-stat {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; color: #B0A898; margin-left: auto;
}

.edge-legend { display: flex; align-items: center; gap: 16px; }
.edge-legend-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #B0A898; }
.edge-line { width: 20px; height: 1px; }

/* ── Explore concept list ── */
.concept-list-item {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px;
    background: #FBF8F1; border: 1px solid #D8D0C2;
    margin-bottom: 3px;
}
.concept-list-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.concept-list-name {
    font-family: 'Source Sans 3', 'Lato', sans-serif;
    font-size: 13px; color: #292820; font-weight: 500;
}
.concept-list-domain {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; color: #B0A898; margin-left: auto;
    text-transform: uppercase; letter-spacing: 0.05em;
}

/* ── Analytics stats ── */
.stat-row { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.stat-card {
    flex: 1; min-width: 100px;
    background: #FBF8F1; border: 1px solid #D8D0C2;
    border-top: 2px solid #8C3428;
    padding: 12px 16px;
}
.stat-card-value {
    font-family: 'Playfair Display', 'Georgia', serif;
    font-size: 26px; font-weight: 700; color: #292820;
    display: block; margin-bottom: 2px;
}
.stat-card-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px; color: #B0A898;
    text-transform: uppercase; letter-spacing: 0.1em; font-weight: 500;
}
.pipeline-badge {
    display: inline-block;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; color: #777064;
    background: #FBF8F1; border: 1px solid #D8D0C2;
    padding: 2px 8px; margin-bottom: 8px;
}

/* ── Form controls ── */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] select {
    background: #FBF8F1 !important; border: 1px solid #D8D0C2 !important;
    color: #292820 !important; border-radius: 3px !important; font-size: 13px !important;
    font-family: 'Source Sans 3', 'Lato', sans-serif !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: #8C3428 !important;
    box-shadow: 0 0 0 2px rgba(140,52,40,0.15) !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"] {
    background: #EDE8DC; border-color: #D8D0C2; color: #292820;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: #FBF8F1; padding: 3px; gap: 2px;
    border-bottom: 1px solid #D8D0C2;
    border-radius: 0;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 0; color: #777064;
    font-family: 'Source Sans 3', 'Lato', sans-serif;
    font-size: 13px; font-weight: 400; padding: 6px 16px;
    border-bottom: 2px solid transparent;
}
.stTabs [aria-selected="true"] {
    background: transparent !important;
    color: #8C3428 !important;
    border-bottom: 2px solid #8C3428 !important;
    font-weight: 600 !important;
}

/* ── Buttons ── */
.stButton > button[kind="primary"],
button[kind="primary"] {
    background: #8C3428 !important; color: #FBF8F1 !important;
    border: none !important; border-radius: 3px !important;
}
.stButton > button[kind="primary"]:hover {
    background: #6B2620 !important;
}

/* ── Rules & scrollbars ── */
hr { border: none; border-top: 1px solid #D8D0C2; margin: 12px 0; }

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #F4EFE5; }
::-webkit-scrollbar-thumb { background: #D8D0C2; border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: #B0A898; }

[data-testid="stDataFrame"] { border: 1px solid #D8D0C2 !important; border-radius: 3px !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Session state
# ─────────────────────────────────────────────────────────────────────────────

SECTIONS = ["Graph", "Explore", "Resources", "Analytics", "Manage"]

def _ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default

_ss("section",          "Graph")
_ss("selected_concept", None)
_ss("graph_search",     "")
_ss("filter_domains",   list(DOMAIN_COLORS.keys()))
_ss("show_prereq",      True)
_ss("show_related",     True)


# ─────────────────────────────────────────────────────────────────────────────
# 9. DB connection
# ─────────────────────────────────────────────────────────────────────────────

try:
    db = get_db()
except Exception as e:
    st.error(f"**Cannot connect to MongoDB.**\n\nCheck your `.env` and ensure MongoDB is running.\n\n`{e}`")
    st.stop()

n_concepts  = db.concepts.count_documents({})
n_resources = db.learning_resources.count_documents({})


# ─────────────────────────────────────────────────────────────────────────────
# 10. Sidebar
# ─────────────────────────────────────────────────────────────────────────────

SECTION_ICONS = {
    "Graph":     "[ ] Graph",
    "Explore":   "( ) Explore",
    "Resources": "[=] Resources",
    "Analytics": "~~~ Analytics",
    "Manage":    "[+] Manage",
}

with st.sidebar:
    st.markdown("""
    <div class="nav-logo">
      <div class="nav-logo-text">Concept Constellation</div>
      <div class="nav-logo-sub">Knowledge Graph Explorer</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<span class="nav-section-label">Navigation</span>', unsafe_allow_html=True)

    for sec in SECTIONS:
        is_active = st.session_state.section == sec
        css_class = "nav-active" if is_active else ""
        st.markdown(f'<div class="nav-section {css_class}">', unsafe_allow_html=True)
        if st.button(SECTION_ICONS[sec], key=f"nav_{sec}"):
            st.session_state.section = sec
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<span class="filter-label">Graph Filters</span>', unsafe_allow_html=True)

    search_val = st.text_input(
        "Search concept", value=st.session_state.graph_search,
        placeholder="Search concept...", key="graph_search_input",
        label_visibility="collapsed",
    )
    if search_val != st.session_state.graph_search:
        st.session_state.graph_search = search_val
        if search_val and read_concept(db, search_val):
            st.session_state.selected_concept = search_val
        st.rerun()

    st.markdown('<span class="filter-label" style="margin-top:8px;">Domains</span>',
                unsafe_allow_html=True)

    db_domains = (sorted({c["domain"] for c in db.concepts.find({}, {"domain": 1, "_id": 0})})
                  if n_concepts > 0 else DOMAINS)

    for dom in db_domains:
        color   = DOMAIN_COLORS.get(dom, DOMAIN_FALLBACK)
        checked = dom in st.session_state.filter_domains
        new_val = st.checkbox(f" {dom}", value=checked, key=f"dom_{dom}")
        if new_val != checked:
            if new_val:
                st.session_state.filter_domains.append(dom)
            else:
                st.session_state.filter_domains = [d for d in st.session_state.filter_domains if d != dom]
            st.rerun()

    st.markdown('<span class="filter-label" style="margin-top:6px;">Edge Types</span>',
                unsafe_allow_html=True)
    new_pre = st.checkbox("Prerequisites ->", value=st.session_state.show_prereq, key="cb_prereq")
    new_rel = st.checkbox("Related  --",      value=st.session_state.show_related, key="cb_related")
    if new_pre != st.session_state.show_prereq or new_rel != st.session_state.show_related:
        st.session_state.show_prereq  = new_pre
        st.session_state.show_related = new_rel
        st.rerun()

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<span class="filter-label">Domain Legend</span>', unsafe_allow_html=True)
    for dom in db_domains:
        color = DOMAIN_COLORS.get(dom, DOMAIN_FALLBACK)
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:6px;padding:2px 16px;">'
            f'<div style="width:8px;height:8px;border-radius:50%;background:{color};flex-shrink:0;"></div>'
            f'<span style="font-size:11.5px;color:#777064;font-family:Source Sans 3,Lato,sans-serif;">{dom}</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    n_pre     = sum(len(c.get("prerequisites", [])) for c in db.concepts.find({}, {"prerequisites": 1, "_id": 0}))
    n_rel_raw = sum(len(c.get("related", []))        for c in db.concepts.find({}, {"related": 1,        "_id": 0}))
    st.markdown(
        f'<div style="padding:0 16px;">'
        f'<div style="font-size:10px;color:#B0A898;font-family:IBM Plex Mono,monospace;letter-spacing:0.04em;">'
        f'{n_concepts} concepts &middot; {n_resources} resources</div>'
        f'<div style="font-size:10px;color:#B0A898;font-family:IBM Plex Mono,monospace;letter-spacing:0.04em;">'
        f'{n_pre} prereq edges &middot; {n_rel_raw // 2} related pairs</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown(
        '<div style="padding:0 16px;font-size:10.5px;color:#49624A;">'
        '&#9679; MongoDB connected</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 11. Inspector helper
# ─────────────────────────────────────────────────────────────────────────────

def render_inspector(concept_name, db, show_navigate=True):
    if not concept_name:
        st.markdown("""
        <div class="inspector-empty">
          <div class="inspector-empty-icon">( )</div>
          <div class="inspector-empty-text">
            Select a concept in the graph<br/>or use the search to focus a node.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    concept = read_concept(db, concept_name)
    if not concept:
        st.caption(f"Concept '{concept_name}' not found.")
        return

    dom_color = DOMAIN_COLORS.get(concept["domain"], DOMAIN_FALLBACK)
    st.markdown(
        f'<div class="inspector-name">{concept["name"]}</div>'
        f'<span class="inspector-domain-badge" '
        f'style="background:{dom_color}22;color:{dom_color};border:1px solid {dom_color}44;">'
        f'{concept["domain"]}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="inspector-definition">{concept["definition"]}</div>',
                unsafe_allow_html=True)

    prereqs = concept.get("prerequisites", [])
    st.markdown('<div class="inspector-section-title">Prerequisites</div>', unsafe_allow_html=True)
    if prereqs:
        chips = "".join(f'<span class="concept-chip concept-chip-pre">{p}</span>' for p in prereqs)
        st.markdown(f'<div style="margin-bottom:8px;">{chips}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:12px;color:#4b5563;margin-bottom:8px;">None</div>',
                    unsafe_allow_html=True)

    related = concept.get("related", [])
    st.markdown('<div class="inspector-section-title">Related Concepts</div>', unsafe_allow_html=True)
    if related:
        chips = "".join(f'<span class="concept-chip concept-chip-rel">{r}</span>' for r in related)
        st.markdown(f'<div style="margin-bottom:8px;">{chips}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:12px;color:#4b5563;margin-bottom:8px;">None</div>',
                    unsafe_allow_html=True)

    resources = list(db.learning_resources.find(
        {"concepts": concept_name},
        {"_id": 0, "title": 1, "url": 1, "resource_type": 1}
    ))
    st.markdown('<div class="inspector-section-title">Learning Resources</div>', unsafe_allow_html=True)
    if resources:
        for res in resources:
            dot_color = RESOURCE_TYPE_COLORS.get(res["resource_type"], "#555")
            st.markdown(
                f'<div class="resource-item">'
                f'<div class="resource-type-dot" style="background:{dot_color};"></div>'
                f'<div>'
                f'<a class="resource-link" href="{res["url"]}" target="_blank">{res["title"]}</a>'
                f'<span class="resource-type-label">{res["resource_type"]}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown('<div style="font-size:12px;color:#B0A898;">No resources linked.</div>',
                    unsafe_allow_html=True)

    if show_navigate and (prereqs or related):
        st.markdown('<hr style="border-color:#D8D0C2;margin:12px 0;"/>', unsafe_allow_html=True)
        st.markdown('<div class="inspector-section-title">Navigate to</div>', unsafe_allow_html=True)
        neighbors = list(dict.fromkeys(prereqs + related))
        sel = st.selectbox(
            "Navigate to neighbor", ["--"] + neighbors,
            key=f"nav_neighbor_{concept_name}", label_visibility="collapsed",
        )
        if sel and sel != "--":
            if st.button("Go", key=f"go_{concept_name}_{sel}"):
                st.session_state.selected_concept = sel
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 12. Section: Graph workspace
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.section == "Graph":
    if n_concepts == 0:
        st.info("No concepts in database. Run `python seed.py` to populate.")
    else:
        col_graph, col_inspector = st.columns([3, 1], gap="small")

        with col_graph:
            filter_doms = st.session_state.filter_domains or None
            focus       = st.session_state.selected_concept

            nodes, pre_edges, rel_edges, cset = _get_graph_data(
                db,
                filter_domains=filter_doms,
                show_prereq=st.session_state.show_prereq,
                show_related=st.session_state.show_related,
                focus_concept=focus,
            )
            n_nodes = len(nodes)
            n_edges = len(pre_edges) + len(rel_edges)

            st.markdown(
                f'<div class="graph-toolbar">'
                f'<span class="graph-toolbar-title">Knowledge Graph</span>'
                f'<div class="edge-legend">'
                f'<div class="edge-legend-item">'
                f'<div class="edge-line" style="background:rgba(140,100,60,0.50);"></div>'
                f'<span>Prerequisite</span></div>'
                f'<div class="edge-legend-item">'
                f'<div class="edge-line" style="background:rgba(160,145,120,0.35);'
                f'border-top:1px dashed rgba(160,145,120,0.5);height:0;"></div>'
                f'<span>Related</span></div></div>'
                f'<span class="graph-stat">{n_nodes} nodes &middot; {n_edges} edges</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            all_names_graph = sorted(cset)
            focus_options   = ["-- none --"] + all_names_graph
            cur_idx         = focus_options.index(focus) if focus in focus_options else 0

            focus_sel = st.selectbox(
                "Focus concept", focus_options, index=cur_idx,
                key="graph_focus_sel", label_visibility="collapsed",
            )
            if focus_sel != focus_options[cur_idx]:
                st.session_state.selected_concept = None if focus_sel == "-- none --" else focus_sel
                st.rerun()

            try:
                graph_html = build_pyvis_graph(nodes, pre_edges, rel_edges, height="560px")
                st.components.v1.html(graph_html, height=560)
            except ImportError:
                st.caption("PyVis unavailable -- showing static graph")
                g = build_graphviz_fallback(
                    db,
                    filter_domains=filter_doms,
                    show_prereq=st.session_state.show_prereq,
                    show_related=st.session_state.show_related,
                )
                if g:
                    st.graphviz_chart(g.source)
            except Exception as ex:
                st.error(f"Graph render error: {ex}")

        with col_inspector:
            st.markdown('<div class="section-heading" style="margin-bottom:10px;">Inspector</div>',
                        unsafe_allow_html=True)
            render_inspector(st.session_state.selected_concept, db)


# ─────────────────────────────────────────────────────────────────────────────
# 13. Section: Explore
# ─────────────────────────────────────────────────────────────────────────────

elif st.session_state.section == "Explore":
    col_list, col_detail = st.columns([1, 2], gap="small")

    with col_list:
        st.markdown('<div class="section-heading">Concepts</div>', unsafe_allow_html=True)
        search_q   = st.text_input("Filter concepts",  placeholder="Filter concepts...",
                                   key="explore_search", label_visibility="collapsed")
        dom_filter = st.selectbox("Domain filter", ["All"] + DOMAINS,
                                  key="explore_dom_filter", label_visibility="collapsed")

        all_docs = list(db.concepts.find(
            {}, {"name": 1, "domain": 1, "_id": 0}
        ).sort("name"))
        filtered = [
            c for c in all_docs
            if (not search_q or search_q.lower() in c["name"].lower())
            and (dom_filter == "All" or c["domain"] == dom_filter)
        ]

        if not filtered:
            st.caption("No concepts found.")
        else:
            for c in filtered:
                color   = DOMAIN_COLORS.get(c["domain"], DOMAIN_FALLBACK)
                is_sel  = st.session_state.selected_concept == c["name"]
                bg      = "#FAF3F2" if is_sel else "#FBF8F1"
                border  = "#8C3428" if is_sel else "#D8D0C2"
                st.markdown(
                    f'<div class="concept-list-item" style="background:{bg};border-color:{border};">'
                    f'<div class="concept-list-dot" style="background:{color};"></div>'
                    f'<span class="concept-list-name">{c["name"]}</span>'
                    f'<span class="concept-list-domain">{c["domain"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button("Select", key=f"sel_{c['name']}", help=f"View {c['name']}",
                             use_container_width=True):
                    st.session_state.selected_concept = c["name"]
                    st.rerun()

    with col_detail:
        st.markdown('<div class="section-heading">Detail</div>', unsafe_allow_html=True)
        render_inspector(st.session_state.selected_concept, db)


# ─────────────────────────────────────────────────────────────────────────────
# 14. Section: Resources
# ─────────────────────────────────────────────────────────────────────────────

elif st.session_state.section == "Resources":
    st.markdown('<div class="section-heading">Learning Resources</div>', unsafe_allow_html=True)

    col_s, col_t = st.columns([3, 1])
    with col_s:
        res_search = st.text_input("Search resources", placeholder="Search resources...",
                                   key="res_search", label_visibility="collapsed")
    with col_t:
        res_type_f = st.selectbox("Resource type", ["All types"] + RESOURCE_TYPES,
                                  key="res_type_f", label_visibility="collapsed")

    all_resources = list(db.learning_resources.find(
        {}, {"title": 1, "url": 1, "resource_type": 1, "concepts": 1, "_id": 0}
    ).sort("title"))
    filtered_res = [
        r for r in all_resources
        if (not res_search or res_search.lower() in r["title"].lower())
        and (res_type_f == "All types" or r["resource_type"] == res_type_f)
    ]

    if not filtered_res:
        st.caption("No resources found.")
    else:
        for res in filtered_res:
            dot_color = RESOURCE_TYPE_COLORS.get(res["resource_type"], "#555")
            concept_chips = "".join(
                f'<span style="display:inline-block;font-size:11px;'
                f'font-family:IBM Plex Mono,monospace;'
                f'padding:1px 7px;border-radius:2px;'
                f'background:#FAF3F2;border:1px solid #DFC9C5;'
                f'color:#8C3428;margin:1px;">{cn}</span>'
                for cn in res.get("concepts", [])
            )
            st.markdown(
                f'<div style="background:#FBF8F1;border:1px solid #D8D0C2;'
                f'border-left:3px solid {dot_color};'
                f'padding:10px 14px;margin-bottom:6px;">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
                f'<div style="width:6px;height:6px;border-radius:50%;background:{dot_color};flex-shrink:0;"></div>'
                f'<a href="{res["url"]}" target="_blank" '
                f'style="font-family:Source Sans 3,Lato,sans-serif;font-size:13px;color:#8C3428;'
                f'text-decoration:none;font-weight:500;">'
                f'{res["title"]}</a>'
                f'<span style="font-size:9px;font-family:IBM Plex Mono,monospace;'
                f'color:#B0A898;margin-left:auto;text-transform:uppercase;letter-spacing:0.06em;">'
                f'{res["resource_type"]}</span>'
                f'</div>'
                f'<div style="padding-left:14px;">{concept_chips}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    st.markdown(
        f'<div style="font-size:10px;color:#B0A898;font-family:IBM Plex Mono,monospace;'
        f'letter-spacing:0.04em;margin-top:8px;">'
        f'{len(filtered_res)} of {len(all_resources)} resources</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 15. Section: Analytics
# ─────────────────────────────────────────────────────────────────────────────

elif st.session_state.section == "Analytics":
    import pandas as pd
    st.markdown('<div class="section-heading">Analytics</div>', unsafe_allow_html=True)

    if n_concepts == 0:
        st.caption("No data. Run seed.py first.")
    else:
        data1 = agg_concepts_per_domain(db)
        st.markdown('<div class="stat-row">', unsafe_allow_html=True)
        for row in data1:
            color = DOMAIN_COLORS.get(row["domain"], DOMAIN_FALLBACK)
            st.markdown(
                f'<div class="stat-card">'
                f'<span class="stat-card-value" style="color:{color};">{row["count"]}</span>'
                f'<span class="stat-card-label">{row["domain"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<div class="stat-card">'
            f'<span class="stat-card-value">{n_resources}</span>'
            f'<span class="stat-card-label">Resources</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

        tab_a, tab_b, tab_c, tab_d = st.tabs([
            "Most Connected", "Domains Ranked", "Resources by Type", "Resources per Concept"
        ])

        with tab_a:
            st.markdown('<span class="pipeline-badge">$project · $size · $sort · $limit</span>',
                        unsafe_allow_html=True)
            data2 = agg_most_connected(db)
            if data2:
                df2 = pd.DataFrame(data2)
                st.bar_chart(df2.set_index("name")["degree"], height=220, color="#5b8dd9")
                st.dataframe(df2.rename(columns={"name": "Concept", "degree": "Connections"}),
                             hide_index=True, height=200)

        with tab_b:
            st.markdown('<span class="pipeline-badge">$group · $sort · $project</span>',
                        unsafe_allow_html=True)
            data3 = agg_domains_ranked(db)
            if data3:
                df3 = pd.DataFrame(data3).rename(
                    columns={"domain": "Domain", "concept_count": "Concepts"})
                st.bar_chart(df3.set_index("Domain")["Concepts"], height=220, color="#57a87a")
                st.dataframe(df3, hide_index=True, height=160)

        with tab_c:
            st.markdown('<span class="pipeline-badge">$group · $sort · $project</span>',
                        unsafe_allow_html=True)
            data4 = agg_resource_type_counts(db)
            if data4:
                df4 = pd.DataFrame(data4).rename(
                    columns={"resource_type": "Type", "count": "Count"})
                st.bar_chart(df4.set_index("Type")["Count"], height=220, color="#d4845a")
                st.dataframe(df4, hide_index=True, height=140)

        with tab_d:
            st.markdown('<span class="pipeline-badge">$unwind · $group · $sort · $limit · $lookup · $project</span>',
                        unsafe_allow_html=True)
            data5 = agg_concepts_with_most_resources(db)
            if data5:
                df5 = pd.DataFrame(data5).rename(
                    columns={"concept": "Concept", "resource_count": "Resources", "domain": "Domain"})
                st.bar_chart(df5.set_index("Concept")["Resources"], height=220, color="#c0655e")
                st.dataframe(df5, hide_index=True, height=220)
            elif n_resources == 0:
                st.caption("No resources in database.")
            else:
                st.caption("No linked concepts found.")


# ─────────────────────────────────────────────────────────────────────────────
# 16. Section: Manage (CRUD)
# ─────────────────────────────────────────────────────────────────────────────

elif st.session_state.section == "Manage":
    st.markdown('<div class="section-heading">Manage</div>', unsafe_allow_html=True)

    tab_concepts, tab_resources = st.tabs(["Concepts", "Resources"])

    # --- Concepts CRUD ---
    with tab_concepts:
        all_names = all_concept_names(db)
        action = st.radio("Action", ["Add", "Edit", "Delete"], horizontal=True,
                          key="concept_action", label_visibility="collapsed")

        if action == "Add":
            st.markdown("<br/>", unsafe_allow_html=True)
            with st.form("add_concept_form", border=False):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    name = st.text_input("Concept name *")
                with col_b:
                    domain = st.selectbox("Domain *", DOMAINS)
                definition = st.text_area("Definition *", height=90)
                col_c, col_d = st.columns(2)
                with col_c:
                    prereqs = st.multiselect("Prerequisites", all_names)
                with col_d:
                    related = st.multiselect("Related Concepts", all_names)
                submitted = st.form_submit_button("Create Concept")
            if submitted:
                if not name.strip() or not definition.strip():
                    st.error("Name and definition are required.")
                else:
                    ok, msg = create_concept(db, name.strip(), domain,
                                             definition.strip(), prereqs, related)
                    (st.success if ok else st.error)(msg)

        elif action == "Edit":
            if not all_names:
                st.info("No concepts to edit.")
            else:
                target  = st.selectbox("Select concept", all_names, key="edit_concept_sel")
                concept = read_concept(db, target)
                if concept:
                    st.markdown("<br/>", unsafe_allow_html=True)
                    with st.form("edit_concept_form", border=False):
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            st.text_input("Name", value=target, disabled=True)
                        with col_b:
                            domain = st.selectbox(
                                "Domain", DOMAINS,
                                index=DOMAINS.index(concept["domain"])
                                      if concept["domain"] in DOMAINS else 0,
                            )
                        definition = st.text_area("Definition", concept["definition"], height=90)
                        other = [n for n in all_names if n != target]
                        col_c, col_d = st.columns(2)
                        with col_c:
                            prereqs = st.multiselect("Prerequisites", other,
                                                     default=concept.get("prerequisites", []))
                        with col_d:
                            related = st.multiselect("Related Concepts", other,
                                                     default=concept.get("related", []))
                        submitted = st.form_submit_button("Save Changes")
                    if submitted:
                        ok, msg = update_concept(db, target, domain,
                                                 definition.strip(), prereqs, related)
                        (st.success if ok else st.error)(msg)

        elif action == "Delete":
            if not all_names:
                st.info("No concepts to delete.")
            else:
                target  = st.selectbox("Select concept to delete", all_names, key="del_concept_sel")
                concept = read_concept(db, target)
                if concept:
                    refs_pre = list(db.concepts.find({"prerequisites": target}, {"name": 1, "_id": 0}))
                    refs_rel = list(db.concepts.find({"related": target},       {"name": 1, "_id": 0}))
                    refs_res = list(db.learning_resources.find({"concepts": target}, {"title": 1, "_id": 0}))
                    impact_lines = []
                    if refs_pre:
                        impact_lines.append(f"Prerequisite of: {', '.join(c['name'] for c in refs_pre)}")
                    if refs_rel:
                        impact_lines.append(f"Related to: {', '.join(c['name'] for c in refs_rel)}")
                    if refs_res:
                        impact_lines.append(f"In resources: {', '.join(r['title'] for r in refs_res)}")
                    if impact_lines:
                        st.warning("**Cascade effects on deletion:**\n\n" + "\n\n".join(impact_lines))
                    else:
                        st.info(f"**{target}** has no outgoing references. Safe to delete.")
                    confirm = st.checkbox(f"I understand -- delete '{target}' and clean up all references")
                    if st.button("Delete Concept", disabled=not confirm, type="primary"):
                        ok, msg = delete_concept(db, target)
                        if ok:
                            st.success(msg)
                            if st.session_state.selected_concept == target:
                                st.session_state.selected_concept = None
                            st.rerun()
                        else:
                            st.error(msg)

    # --- Resources CRUD ---
    with tab_resources:
        all_names   = all_concept_names(db)
        all_res_raw = list(db.learning_resources.find({}, {"title": 1}))
        action_r = st.radio("Action", ["Add", "Edit", "Delete"], horizontal=True,
                            key="resource_action", label_visibility="collapsed")

        if action_r == "Add":
            st.markdown("<br/>", unsafe_allow_html=True)
            with st.form("add_resource_form", border=False):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    title = st.text_input("Title *")
                with col_b:
                    res_type = st.selectbox("Type *", RESOURCE_TYPES)
                url          = st.text_input("URL * (https://...)")
                linked_concs = st.multiselect("Linked Concepts", all_names)
                submitted    = st.form_submit_button("Create Resource")
            if submitted:
                if not title.strip() or not url.strip():
                    st.error("Title and URL are required.")
                else:
                    ok, msg = create_resource(db, title.strip(), url.strip(),
                                              linked_concs, res_type)
                    (st.success if ok else st.error)(msg)

        elif action_r == "Edit":
            if not all_res_raw:
                st.info("No resources to edit.")
            else:
                options = {str(r["_id"]): r["title"] for r in all_res_raw}
                sel_id  = st.selectbox("Select resource", list(options.keys()),
                                       format_func=lambda x: options[x], key="edit_res_sel")
                from bson import ObjectId
                res = db.learning_resources.find_one({"_id": ObjectId(sel_id)})
                if res:
                    st.markdown("<br/>", unsafe_allow_html=True)
                    with st.form("edit_resource_form", border=False):
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            title = st.text_input("Title", res["title"])
                        with col_b:
                            res_type = st.selectbox(
                                "Type", RESOURCE_TYPES,
                                index=RESOURCE_TYPES.index(res["resource_type"])
                                      if res["resource_type"] in RESOURCE_TYPES else 0,
                            )
                        url          = st.text_input("URL", res["url"])
                        linked_concs = st.multiselect("Linked Concepts", all_names,
                                                      default=res.get("concepts", []))
                        submitted    = st.form_submit_button("Save Changes")
                    if submitted:
                        ok, msg = update_resource(db, sel_id, title.strip(), url.strip(),
                                                  linked_concs, res_type)
                        (st.success if ok else st.error)(msg)

        elif action_r == "Delete":
            if not all_res_raw:
                st.info("No resources to delete.")
            else:
                options = {str(r["_id"]): r["title"] for r in all_res_raw}
                sel_id  = st.selectbox("Select resource to delete", list(options.keys()),
                                       format_func=lambda x: options[x], key="del_res_sel")
                st.warning(f"Delete **{options[sel_id]}**? This cannot be undone.")
                confirm = st.checkbox("Confirm deletion")
                if st.button("Delete Resource", disabled=not confirm, type="primary"):
                    ok, msg = delete_resource(db, sel_id)
                    (st.success if ok else st.error)(msg)
                    st.rerun()
