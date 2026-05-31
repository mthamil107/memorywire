"""Hand-authored corpus for the memwire recall microbenchmark.

This dataset is the source-of-truth corpus for ``scripts/run_microbench.py``
and ``tests/benchmarks/test_recall_benchmark.py``. It is deliberately small,
deliberately human-written, and deliberately *not* drawn from any upstream
benchmark â€” the goal is one honest blog-post number for v0, not a claim to
LongMemEval / LoCoMo / BEAM parity. Those land in v0.2.

Shape
-----
* :data:`FACTS` â€” 100 entries. Each is a ``dict`` with ``id`` (stable
  string id used as gold-label), ``user_id`` (~10 distinct users so we
  exercise the per-user recall scope), ``type`` (mix of all four
  :class:`memwire.MemoryType` values), and ``content`` (the natural-language
  text the embedder sees).
* :data:`QUERIES` â€” 50 entries. Each is a ``dict`` with ``query`` (the
  natural-language search string), ``gold_ids`` (the set of fact ids that
  a correct system should return; may be empty for no-match probes; may
  have multiple ids for multi-hit queries), and ``user_id`` (the scope
  the recall is issued under).

Query taxonomy
--------------
* **Exact match** â€” query repeats a salient phrase from one fact.
* **Paraphrase** â€” query rewords a fact ("foods to avoid" â†’ peanuts).
* **Multi-hit** â€” query maps to 2-3 facts (e.g. "what languages does X speak").
* **No-match** â€” query has no expected fact (gold_ids=[]); used to
  measure how often the system surfaces a confident wrong answer.

Maintenance
-----------
If you add facts or queries, keep gold_ids in sync. The pytest harness
asserts mean recall@5 >= 0.6, so a regression would catch a typo'd id.
"""

from __future__ import annotations

from typing import TypedDict


class Fact(TypedDict):
    """One memory the benchmark will ingest."""

    id: str
    user_id: str
    type: str
    content: str


class Query(TypedDict):
    """One query + its gold answer set."""

    query: str
    gold_ids: list[str]
    user_id: str


# ---------------------------------------------------------------------------
# Facts â€” 100 entries across ~10 users, mixed memory types
# ---------------------------------------------------------------------------

FACTS: list[Fact] = [
    # ---- Alice (10 facts, mostly semantic + a couple episodic) -----------
    {
        "id": "f001",
        "user_id": "alice",
        "type": "semantic",
        "content": "Alice is allergic to peanuts and tree nuts.",
    },
    {
        "id": "f002",
        "user_id": "alice",
        "type": "semantic",
        "content": "Alice's favourite colour is teal.",
    },
    {
        "id": "f003",
        "user_id": "alice",
        "type": "semantic",
        "content": "Alice lives in Brooklyn, New York.",
    },
    {
        "id": "f004",
        "user_id": "alice",
        "type": "semantic",
        "content": "Alice prefers Linux over macOS.",
    },
    {
        "id": "f005",
        "user_id": "alice",
        "type": "semantic",
        "content": "Alice plays piano on Sunday afternoons.",
    },
    {
        "id": "f006",
        "user_id": "alice",
        "type": "episodic",
        "content": "On 2026-01-15 Alice climbed Mount Rainier with three friends.",
    },
    {
        "id": "f007",
        "user_id": "alice",
        "type": "semantic",
        "content": "Alice reads mostly science-fiction novels.",
    },
    {
        "id": "f008",
        "user_id": "alice",
        "type": "semantic",
        "content": "Alice runs five kilometres every morning before work.",
    },
    {
        "id": "f009",
        "user_id": "alice",
        "type": "semantic",
        "content": "Alice tutors high-school maths students remotely.",
    },
    {
        "id": "f010",
        "user_id": "alice",
        "type": "emotional",
        "content": "Alice feels anxious when she has to give live presentations.",
    },
    # ---- Bob (10 facts) --------------------------------------------------
    {"id": "f011", "user_id": "bob", "type": "semantic", "content": "Bob is an avid sea kayaker."},
    {
        "id": "f012",
        "user_id": "bob",
        "type": "semantic",
        "content": "Bob lives in Seattle near Lake Union.",
    },
    {
        "id": "f013",
        "user_id": "bob",
        "type": "semantic",
        "content": "Bob prefers black tea over coffee.",
    },
    {
        "id": "f014",
        "user_id": "bob",
        "type": "semantic",
        "content": "Bob speaks French and Portuguese fluently.",
    },
    {
        "id": "f015",
        "user_id": "bob",
        "type": "semantic",
        "content": "Bob collects vintage typewriters from the 1950s.",
    },
    {
        "id": "f016",
        "user_id": "bob",
        "type": "episodic",
        "content": "On 2026-03-10 Bob asked for a refund on order #7821.",
    },
    {
        "id": "f017",
        "user_id": "bob",
        "type": "semantic",
        "content": "Bob recently adopted a tabby cat named Pixel.",
    },
    {
        "id": "f018",
        "user_id": "bob",
        "type": "semantic",
        "content": "Bob commutes by bicycle year-round, even in winter.",
    },
    {
        "id": "f019",
        "user_id": "bob",
        "type": "semantic",
        "content": "Bob volunteers at the local food bank on Wednesdays.",
    },
    {
        "id": "f020",
        "user_id": "bob",
        "type": "episodic",
        "content": "On 2026-04-02 Bob filed a complaint about a delayed shipment.",
    },
    # ---- Carla (10 facts, includes procedural) ---------------------------
    {
        "id": "f021",
        "user_id": "carla",
        "type": "semantic",
        "content": "Carla studies microbiology at Cambridge University.",
    },
    {
        "id": "f022",
        "user_id": "carla",
        "type": "semantic",
        "content": "Carla is fluent in Italian and Spanish.",
    },
    {
        "id": "f023",
        "user_id": "carla",
        "type": "semantic",
        "content": "Carla's PhD research focuses on gut microbiomes.",
    },
    {
        "id": "f024",
        "user_id": "carla",
        "type": "semantic",
        "content": "Carla enjoys long-distance cycling tours through Tuscany.",
    },
    {
        "id": "f025",
        "user_id": "carla",
        "type": "semantic",
        "content": "Carla bakes sourdough bread every Saturday morning.",
    },
    {
        "id": "f026",
        "user_id": "carla",
        "type": "semantic",
        "content": "Carla shares a flat with two roommates in Cambridge.",
    },
    {
        "id": "f027",
        "user_id": "carla",
        "type": "semantic",
        "content": "Carla plays the cello in a chamber music group.",
    },
    {
        "id": "f028",
        "user_id": "carla",
        "type": "procedural",
        "content": '{"name":"bake_sourdough","states":["mix","autolyse","fold","proof","bake"],"current":"mix"}',
    },
    {
        "id": "f029",
        "user_id": "carla",
        "type": "emotional",
        "content": "Carla feels deeply calm when she is gardening.",
    },
    {
        "id": "f030",
        "user_id": "carla",
        "type": "episodic",
        "content": "On 2026-02-20 Carla presented her research at the EMBO meeting.",
    },
    # ---- Daniel (10 facts) ----------------------------------------------
    {
        "id": "f031",
        "user_id": "daniel",
        "type": "semantic",
        "content": "Daniel follows a vegetarian diet.",
    },
    {
        "id": "f032",
        "user_id": "daniel",
        "type": "semantic",
        "content": "Daniel uses a mechanical keyboard with linear MX-Red switches.",
    },
    {
        "id": "f033",
        "user_id": "daniel",
        "type": "episodic",
        "content": "On 2026-01-30 Daniel's side-project reached the Hacker News front page.",
    },
    {
        "id": "f034",
        "user_id": "daniel",
        "type": "semantic",
        "content": "Daniel meditates for ten minutes every morning.",
    },
    {
        "id": "f035",
        "user_id": "daniel",
        "type": "semantic",
        "content": "Daniel's favourite ice cream flavour is pistachio.",
    },
    {
        "id": "f036",
        "user_id": "daniel",
        "type": "semantic",
        "content": "Daniel keeps a hand-written morning journal.",
    },
    {
        "id": "f037",
        "user_id": "daniel",
        "type": "semantic",
        "content": "Daniel works remotely from a co-working space in Berlin.",
    },
    {
        "id": "f038",
        "user_id": "daniel",
        "type": "episodic",
        "content": "On 2026-05-12 Daniel attended a Rust language meetup.",
    },
    {
        "id": "f039",
        "user_id": "daniel",
        "type": "semantic",
        "content": "Daniel is learning to play the harmonica.",
    },
    {
        "id": "f040",
        "user_id": "daniel",
        "type": "semantic",
        "content": "Daniel's favourite hike is the Lost Coast Trail in California.",
    },
    # ---- Elena (10 facts) -----------------------------------------------
    {
        "id": "f041",
        "user_id": "elena",
        "type": "semantic",
        "content": "Elena is a paediatric nurse at a children's hospital.",
    },
    {
        "id": "f042",
        "user_id": "elena",
        "type": "semantic",
        "content": "Elena grew up in Madrid and moved to Toronto at twenty-three.",
    },
    {
        "id": "f043",
        "user_id": "elena",
        "type": "semantic",
        "content": "Elena's twin daughters are six years old.",
    },
    {
        "id": "f044",
        "user_id": "elena",
        "type": "semantic",
        "content": "Elena drives a hybrid Toyota Prius.",
    },
    {
        "id": "f045",
        "user_id": "elena",
        "type": "semantic",
        "content": "Elena's favourite book is One Hundred Years of Solitude.",
    },
    {
        "id": "f046",
        "user_id": "elena",
        "type": "semantic",
        "content": "Elena is lactose intolerant and avoids dairy.",
    },
    {
        "id": "f047",
        "user_id": "elena",
        "type": "episodic",
        "content": "On 2025-12-20 Elena ran her first half-marathon.",
    },
    {
        "id": "f048",
        "user_id": "elena",
        "type": "semantic",
        "content": "Elena plays tennis every Thursday evening with colleagues.",
    },
    {
        "id": "f049",
        "user_id": "elena",
        "type": "emotional",
        "content": "Elena feels exhilarated when she finishes a long run.",
    },
    {
        "id": "f050",
        "user_id": "elena",
        "type": "semantic",
        "content": "Elena's grandmother taught her to cook traditional paella.",
    },
    # ---- Felix (10 facts) -----------------------------------------------
    {
        "id": "f051",
        "user_id": "felix",
        "type": "semantic",
        "content": "Felix is a senior tax lawyer in Munich.",
    },
    {
        "id": "f052",
        "user_id": "felix",
        "type": "semantic",
        "content": "Felix collects rare jazz vinyl from the 1960s.",
    },
    {
        "id": "f053",
        "user_id": "felix",
        "type": "semantic",
        "content": "Felix speaks German, English, and conversational Japanese.",
    },
    {
        "id": "f054",
        "user_id": "felix",
        "type": "semantic",
        "content": "Felix is married to a software architect named Maren.",
    },
    {
        "id": "f055",
        "user_id": "felix",
        "type": "semantic",
        "content": "Felix supports Bayern Munich football club.",
    },
    {
        "id": "f056",
        "user_id": "felix",
        "type": "episodic",
        "content": "On 2026-04-18 Felix flew to Tokyo for a client engagement.",
    },
    {
        "id": "f057",
        "user_id": "felix",
        "type": "semantic",
        "content": "Felix takes his coffee black with one sugar.",
    },
    {
        "id": "f058",
        "user_id": "felix",
        "type": "semantic",
        "content": "Felix prefers fountain pens to ballpoints.",
    },
    {
        "id": "f059",
        "user_id": "felix",
        "type": "semantic",
        "content": "Felix has an irrational fear of small dogs.",
    },
    {
        "id": "f060",
        "user_id": "felix",
        "type": "emotional",
        "content": "Felix feels nostalgic whenever he hears Miles Davis records.",
    },
    # ---- Grace (10 facts) -----------------------------------------------
    {
        "id": "f061",
        "user_id": "grace",
        "type": "semantic",
        "content": "Grace is a marine biologist working on coral reef restoration.",
    },
    {
        "id": "f062",
        "user_id": "grace",
        "type": "semantic",
        "content": "Grace is based in Townsville on the Great Barrier Reef.",
    },
    {
        "id": "f063",
        "user_id": "grace",
        "type": "semantic",
        "content": "Grace holds a PADI divemaster certification.",
    },
    {
        "id": "f064",
        "user_id": "grace",
        "type": "semantic",
        "content": "Grace's PhD was on symbiotic algae in stony corals.",
    },
    {
        "id": "f065",
        "user_id": "grace",
        "type": "semantic",
        "content": "Grace teaches an open-water diving course on weekends.",
    },
    {
        "id": "f066",
        "user_id": "grace",
        "type": "episodic",
        "content": "On 2026-03-22 Grace published a Nature paper on coral bleaching.",
    },
    {
        "id": "f067",
        "user_id": "grace",
        "type": "semantic",
        "content": "Grace's favourite dive site is the SS Yongala wreck.",
    },
    {
        "id": "f068",
        "user_id": "grace",
        "type": "semantic",
        "content": "Grace adopted a rescue greyhound named Echo last year.",
    },
    {
        "id": "f069",
        "user_id": "grace",
        "type": "emotional",
        "content": "Grace feels heartbroken every time she sees bleached reefs.",
    },
    {
        "id": "f070",
        "user_id": "grace",
        "type": "semantic",
        "content": "Grace doesn't drink alcohol for medical reasons.",
    },
    # ---- Hari (10 facts) ------------------------------------------------
    {
        "id": "f071",
        "user_id": "hari",
        "type": "semantic",
        "content": "Hari is a backend engineer specialising in distributed systems.",
    },
    {
        "id": "f072",
        "user_id": "hari",
        "type": "semantic",
        "content": "Hari works at a fintech start-up in Bangalore.",
    },
    {
        "id": "f073",
        "user_id": "hari",
        "type": "semantic",
        "content": "Hari completed a marathon in three hours and forty-two minutes.",
    },
    {
        "id": "f074",
        "user_id": "hari",
        "type": "semantic",
        "content": "Hari plays competitive chess and is rated around 1900 Elo.",
    },
    {"id": "f075", "user_id": "hari", "type": "semantic", "content": "Hari is a strict vegan."},
    {
        "id": "f076",
        "user_id": "hari",
        "type": "semantic",
        "content": "Hari's open-source project on Raft consensus has 8k stars.",
    },
    {
        "id": "f077",
        "user_id": "hari",
        "type": "semantic",
        "content": "Hari studied at IIT Madras for his bachelor's degree.",
    },
    {
        "id": "f078",
        "user_id": "hari",
        "type": "episodic",
        "content": "On 2026-02-14 Hari proposed to his partner at the Taj Mahal.",
    },
    {
        "id": "f079",
        "user_id": "hari",
        "type": "procedural",
        "content": '{"name":"deploy_pipeline","states":["build","test","stage","canary","prod"],"current":"build"}',
    },
    {
        "id": "f080",
        "user_id": "hari",
        "type": "semantic",
        "content": "Hari's favourite cuisine is Kerala-style fish curry.",
    },
    # ---- Ines (10 facts) ------------------------------------------------
    {
        "id": "f081",
        "user_id": "ines",
        "type": "semantic",
        "content": "Ines is a freelance illustrator based in Lisbon.",
    },
    {
        "id": "f082",
        "user_id": "ines",
        "type": "semantic",
        "content": "Ines specialises in watercolour botanical illustrations.",
    },
    {
        "id": "f083",
        "user_id": "ines",
        "type": "semantic",
        "content": "Ines runs a small Etsy shop selling original prints.",
    },
    {
        "id": "f084",
        "user_id": "ines",
        "type": "semantic",
        "content": "Ines's studio is in the Alfama district.",
    },
    {
        "id": "f085",
        "user_id": "ines",
        "type": "semantic",
        "content": "Ines drinks green tea, never coffee.",
    },
    {
        "id": "f086",
        "user_id": "ines",
        "type": "semantic",
        "content": "Ines has two cats named Pancho and Frida.",
    },
    {
        "id": "f087",
        "user_id": "ines",
        "type": "episodic",
        "content": "On 2026-01-08 Ines's work was featured in The Guardian.",
    },
    {
        "id": "f088",
        "user_id": "ines",
        "type": "semantic",
        "content": "Ines is allergic to bee stings.",
    },
    {
        "id": "f089",
        "user_id": "ines",
        "type": "semantic",
        "content": "Ines volunteers teaching art to refugee children on Saturdays.",
    },
    {
        "id": "f090",
        "user_id": "ines",
        "type": "emotional",
        "content": "Ines feels most creative early in the morning before sunrise.",
    },
    # ---- Jonas (10 facts) -----------------------------------------------
    {
        "id": "f091",
        "user_id": "jonas",
        "type": "semantic",
        "content": "Jonas is a high-school physics teacher in Oslo.",
    },
    {
        "id": "f092",
        "user_id": "jonas",
        "type": "semantic",
        "content": "Jonas plays bass guitar in a local indie-rock band.",
    },
    {
        "id": "f093",
        "user_id": "jonas",
        "type": "semantic",
        "content": "Jonas is married with one teenage son named Erik.",
    },
    {
        "id": "f094",
        "user_id": "jonas",
        "type": "semantic",
        "content": "Jonas cross-country skis throughout the winter.",
    },
    {
        "id": "f095",
        "user_id": "jonas",
        "type": "semantic",
        "content": "Jonas drives an electric Volkswagen ID.4.",
    },
    {
        "id": "f096",
        "user_id": "jonas",
        "type": "semantic",
        "content": "Jonas brews his own dark Norwegian-style ale at home.",
    },
    {
        "id": "f097",
        "user_id": "jonas",
        "type": "episodic",
        "content": "On 2026-04-30 Jonas's band played at the Oslo Jazz Festival.",
    },
    {
        "id": "f098",
        "user_id": "jonas",
        "type": "semantic",
        "content": "Jonas reads physics popularisations by Carlo Rovelli.",
    },
    {
        "id": "f099",
        "user_id": "jonas",
        "type": "semantic",
        "content": "Jonas's grandfather was a fisherman from Bergen.",
    },
    {
        "id": "f100",
        "user_id": "jonas",
        "type": "emotional",
        "content": "Jonas feels most alive when he's skiing on a clear winter morning.",
    },
]


# ---------------------------------------------------------------------------
# Queries â€” 50 entries, mix of paraphrase / exact-match / multi-hit / no-match
# ---------------------------------------------------------------------------

QUERIES: list[Query] = [
    # ---- Paraphrase recall (24 queries) ---------------------------------
    {"query": "what foods should I avoid serving Alice?", "gold_ids": ["f001"], "user_id": "alice"},
    {"query": "which colour does Alice prefer?", "gold_ids": ["f002"], "user_id": "alice"},
    {"query": "where does Alice live?", "gold_ids": ["f003"], "user_id": "alice"},
    {"query": "which operating system does Alice use?", "gold_ids": ["f004"], "user_id": "alice"},
    {"query": "any refund requests from Bob?", "gold_ids": ["f016"], "user_id": "bob"},
    {"query": "what hot drinks does Bob like?", "gold_ids": ["f013"], "user_id": "bob"},
    {"query": "did Bob get a new pet recently?", "gold_ids": ["f017"], "user_id": "bob"},
    {"query": "what is Carla researching?", "gold_ids": ["f023"], "user_id": "carla"},
    {"query": "what does Carla bake on weekends?", "gold_ids": ["f025"], "user_id": "carla"},
    {"query": "what musical instrument does Carla play?", "gold_ids": ["f027"], "user_id": "carla"},
    {
        "query": "what kind of keyboard does Daniel type on?",
        "gold_ids": ["f032"],
        "user_id": "daniel",
    },
    {"query": "what is Daniel's preferred ice cream?", "gold_ids": ["f035"], "user_id": "daniel"},
    {
        "query": "what hiking trail does Daniel love most?",
        "gold_ids": ["f040"],
        "user_id": "daniel",
    },
    {"query": "what job does Elena do?", "gold_ids": ["f041"], "user_id": "elena"},
    {"query": "does Elena have children?", "gold_ids": ["f043"], "user_id": "elena"},
    {
        "query": "what dietary restrictions does Elena have?",
        "gold_ids": ["f046"],
        "user_id": "elena",
    },
    {"query": "what music does Felix collect?", "gold_ids": ["f052"], "user_id": "felix"},
    {"query": "what football team does Felix follow?", "gold_ids": ["f055"], "user_id": "felix"},
    {"query": "what does Grace do for a living?", "gold_ids": ["f061"], "user_id": "grace"},
    {"query": "what's Grace's favourite place to dive?", "gold_ids": ["f067"], "user_id": "grace"},
    {"query": "what game does Hari play competitively?", "gold_ids": ["f074"], "user_id": "hari"},
    {"query": "what art form does Ines specialise in?", "gold_ids": ["f082"], "user_id": "ines"},
    {"query": "what does Ines drink in the morning?", "gold_ids": ["f085"], "user_id": "ines"},
    {"query": "what sport does Jonas do in winter?", "gold_ids": ["f094"], "user_id": "jonas"},
    # ---- Exact / near-exact match (10 queries) --------------------------
    {"query": "Alice plays piano on Sunday afternoons", "gold_ids": ["f005"], "user_id": "alice"},
    {"query": "Alice tutors high-school maths students", "gold_ids": ["f009"], "user_id": "alice"},
    {"query": "Bob is an avid sea kayaker", "gold_ids": ["f011"], "user_id": "bob"},
    {"query": "Bob commutes by bicycle year-round", "gold_ids": ["f018"], "user_id": "bob"},
    {"query": "Carla studies microbiology at Cambridge", "gold_ids": ["f021"], "user_id": "carla"},
    {
        "query": "Daniel keeps a hand-written morning journal",
        "gold_ids": ["f036"],
        "user_id": "daniel",
    },
    {"query": "Elena drives a hybrid Toyota Prius", "gold_ids": ["f044"], "user_id": "elena"},
    {
        "query": "Felix prefers fountain pens to ballpoints",
        "gold_ids": ["f058"],
        "user_id": "felix",
    },
    {"query": "Hari studied at IIT Madras", "gold_ids": ["f077"], "user_id": "hari"},
    {
        "query": "Jonas plays bass guitar in an indie-rock band",
        "gold_ids": ["f092"],
        "user_id": "jonas",
    },
    # ---- Multi-hit (8 queries, 2-3 gold ids each) -----------------------
    {"query": "what languages does Bob speak?", "gold_ids": ["f014"], "user_id": "bob"},
    {"query": "what languages does Felix speak?", "gold_ids": ["f053"], "user_id": "felix"},
    {"query": "what languages does Carla speak?", "gold_ids": ["f022"], "user_id": "carla"},
    {
        "query": "tell me about Alice's outdoor activities",
        "gold_ids": ["f006", "f008"],
        "user_id": "alice",
    },
    {
        "query": "what do we know about Bob's complaints or refunds?",
        "gold_ids": ["f016", "f020"],
        "user_id": "bob",
    },
    {"query": "what physical exercise does Hari do?", "gold_ids": ["f073"], "user_id": "hari"},
    {
        "query": "tell me about Grace's diving credentials and teaching",
        "gold_ids": ["f063", "f065"],
        "user_id": "grace",
    },
    {
        "query": "what allergies or intolerances does Elena have?",
        "gold_ids": ["f046"],
        "user_id": "elena",
    },
    # ---- No-match (8 queries, gold_ids=[]) ------------------------------
    {"query": "what is Alice's social-security number?", "gold_ids": [], "user_id": "alice"},
    {"query": "does Bob own a private jet?", "gold_ids": [], "user_id": "bob"},
    {"query": "has Carla ever lived in Antarctica?", "gold_ids": [], "user_id": "carla"},
    {"query": "did Daniel win an Olympic medal?", "gold_ids": [], "user_id": "daniel"},
    {"query": "is Elena a professional skydiver?", "gold_ids": [], "user_id": "elena"},
    {"query": "what dragon breed does Felix own?", "gold_ids": [], "user_id": "felix"},
    {"query": "has Grace climbed Mount Everest?", "gold_ids": [], "user_id": "grace"},
    {"query": "does Jonas race Formula One cars?", "gold_ids": [], "user_id": "jonas"},
]


__all__ = ["FACTS", "QUERIES", "Fact", "Query"]
