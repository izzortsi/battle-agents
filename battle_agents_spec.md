# Battle-Agents: Complete Implementation Specification

**Ontology-Driven Generative Combat Agents — From-Scratch Reimplementation**

This document is a self-contained specification for building the system. It merges the architectural plan with all resolved design decisions. A coding agent should be able to implement the full system from this document alone.

---

## 1. Overview

### 1.1 What This Is

An LLM-driven multi-agent combat simulation where agents perceive, remember, reflect, plan, communicate, and fight on a 2D tile grid. The system fuses two approaches:

- **Park et al. (Generative Agents, UIST '23)**: the cognitive architecture — Memory Stream → Retrieval (scored by recency + importance + relevance) → Reflection → Planning → Action.
- **A formal ontological backbone**: domain D, relation families R, agent knowledge as subsets of P(R), and a transition function f: S × M × P → S' × M' × A realized via LLM prompts.

### 1.2 Scope

Combat-focused, but agents have personalities, dispositions, social memory, and the capacity for emergent cooperation, betrayal, alliance, and dialogue. A pre-battle social phase provides open-world flavor. Two modes: single battle ("run once") and multi-battle ("campaign") with persistent memory.

### 1.3 Tech Stack

- **Language**: Python 3.11+
- **LLM backends**: Anthropic API (Claude), ollama, vLLM — via adapter pattern
- **Embeddings**: `nomic-embed-text` bundled via ollama (default); Voyage/OpenAI as alternatives
- **Frontend**: Phaser.js (2D tile rendering) + Django/Flask (HTTP server)
- **Target agent count**: 4–6 (designed for 10+ scalability)

### 1.4 Design Priorities (ranked)

1. Clean ontological formalization (the formal layer is a real data structure, not documentation)
2. Faithful generative agents architecture (Park et al.'s memory/retrieval/reflection loop)
3. Interesting emergent agent behaviors (alliances, betrayal, information diffusion)
4. Production-quality code and modularity

---

## 2. Formal Ontology Layer

### 2.1 Domain and Relations

The ontological foundation:

- Domain: D = {Agent, Location, Object, Event, Action}
- Relations: R = {R_i}_{i≥1}, where R_i is the set of relations of arity i over elements of D

**World State**: the current ground instantiation of R — all relation tuples currently holding.

**Agent Knowledge**: for agent a, K_a ⊆ P(R) — a partial, possibly incorrect view of which facts hold. Agents never read the world state directly; they receive perceptions filtered through the perception engine, which constructs their K_a. This asymmetry between ground truth and agent belief is the mechanism for emergent drama (misinformation, outdated beliefs, surprises).

### 2.2 Concrete Relation Schemas

| Relation | Arity | Example |
|----------|-------|---------|
| `occupies(agent, location)` | 2 | `occupies(Kael, tile_3_5)` |
| `contains(location, object)` | 2 | `contains(arena, health_potion)` |
| `has_disposition(agent, agent, disposition)` | 3 | `has_disposition(Kael, Lyra, hostile)` |
| `allied_with(agent, agent)` | 2 | `allied_with(Kael, Vorn)` |
| `has_status(agent, status_effect)` | 2 | `has_status(Kael, poisoned)` |
| `holds(agent, object)` | 2 | `holds(Lyra, fire_staff)` |
| `occurred(event, turn)` | 2 | `occurred(kael_attacks_lyra, 7)` |

### 2.3 Modules

```
ontology/
├── domain.py          # Entity base classes: Agent, Location, Object, Event, Action
├── relations.py       # Relation registry, ground instantiation, queries
├── world_state.py     # WorldState: the full ground instantiation of R (single source of truth)
├── knowledge.py       # AgentKnowledge: partial view K_a ⊆ P(R)
└── schemas.py         # Concrete relation schemas for combat game
```

---

## 3. World Structure

### 3.1 World Graph

Hierarchical tree of locations:

```
World
├── Staging Area (pre-battle social zone)
│   ├── Tavern
│   │   ├── Tables (interaction points)
│   │   └── Bar (NPC vendor)
│   └── Training Ground
│       └── Practice Dummies
└── Battle Arena
    ├── Grid (N×M tile grid)
    ├── Terrain Features (walls, cover, elevation)
    └── Interactable Objects (health shrines, traps)
```

### 3.2 Environment Controller

External to agents. Manages:

- Global world state R (the ontology's ground instantiation)
- Turn/tick ordering (initiative system)
- Action resolution and conflict arbitration
- Perception broadcasting
- Victory/defeat conditions
- Alliance inference from social models

### 3.3 Battle Grid

N×M tile grid supporting:

- Collision detection (walls, occupied tiles)
- Pathfinding (for move validation)
- Terrain types (cover, elevation — future)
- Distance calculation (Manhattan or Chebyshev)

### 3.4 Modules

```
world/
├── world_graph.py         # Hierarchical location tree
├── environment.py         # EnvironmentController: manages R, resolves actions
├── battle_grid.py         # N×M tile grid with terrain, collision, pathfinding
├── turn_manager.py        # Initiative rolling, turn ordering, round tracking
├── perception_engine.py   # Filters world state into per-agent perceptions
└── alliance_resolver.py   # Infers alliance status from social models
```

---

## 4. Agent Architecture

### 4.1 Agent Data Model (layered)

```
┌─────────────────────────────────────────┐
│              IDENTITY                    │
│  name, backstory, personality traits     │
├─────────────────────────────────────────┤
│           ATTRIBUTES (hidden)            │
│  HP, mana, attack, defense, speed        │
│  combat_class, abilities, equipment      │
├─────────────────────────────────────────┤
│         KNOWLEDGE  K_a ⊆ P(R)           │
│  what the agent believes about the world │
├─────────────────────────────────────────┤
│            WORLDVIEW                     │
│  higher-level interpretation of K_a      │
│  (built from knowledge + assessment)     │
├─────────────────────────────────────────┤
│          MEMORY STREAM                   │
│  list of MemoryNodes (obs/refl/plan)     │
├─────────────────────────────────────────┤
│         GOALS & PLANS                    │
│  current objectives + strategies         │
├─────────────────────────────────────────┤
│          SOCIAL MODEL                    │
│  disposition toward each known agent     │
│  trust, hostility, alliance status       │
└─────────────────────────────────────────┘
```

### 4.2 Social Model

Each agent maintains relationships with all known agents:

```python
@dataclass
class Relationship:
    agent_name: str
    disposition: float              # -1.0 (hostile) to +1.0 (allied)
    trust: float                    # 0.0 to 1.0
    interaction_count: int
    last_interaction_turn: int
    alliance_declared: bool         # explicit verbal alliance proposed/accepted?
    alliance_turn: Optional[int]    # when alliance was verbally established
    betrayal_count: int             # times this agent has betrayed us
    notes: List[str]                # NL memory snippets about relationship

class SocialModel:
    relationships: Dict[str, Relationship]

    def get_disposition(self, other: str) -> float: ...
    def update_disposition(self, other: str, delta: float, reason: str): ...
    def get_allies(self, threshold: float = 0.5) -> List[str]: ...
    def get_enemies(self, threshold: float = -0.3) -> List[str]: ...
```

Disposition updates through multiple channels:

| Event | Delta | Channel |
|-------|-------|---------|
| Agent b attacks a | -0.3 to -0.5 | Heuristic (immediate) |
| Agent b heals/buffs a | +0.2 to +0.4 | Heuristic (immediate) |
| Agent b kills a's ally | -0.2 | Heuristic (immediate) |
| Agent b kills a's enemy | +0.15 | Heuristic (immediate) |
| Positive dialogue outcome | +0.05 to +0.2 | Dialogue self-report |
| Threatening dialogue | -0.1 to -0.2 | Dialogue self-report |
| Reflection reappraisal | Variable | LLM-driven (during reflection) |

### 4.3 Modules

```
agent/
├── agent.py              # Agent class: ties together all components
├── identity.py           # Name, backstory, personality, combat class
├── attributes.py         # Stats, abilities, equipment, status effects
├── knowledge.py          # AgentKnowledge: the agent's partial world view
├── social_model.py       # Relationships, dispositions, trust
├── goals.py              # Goal representation and priority system
└── plans.py              # Plan representation (hierarchical)
```

---

## 5. Cognitive Loop (Generative Agent Core)

### 5.1 Transition Function

Per turn, each agent executes:

    f: (S × M × P) → (S' × M' × A)

where S = agent state, M = memory stream, P = current perception, A = chosen action. Each call to f is realized by a sequence of LLM prompts that produce structured JSON data.

### 5.2 Cognitive Steps (per turn)

```
PERCEIVE  →  Environment provides filtered observations for this agent
    ↓
REMEMBER  →  Store new observations as MemoryNodes
    ↓
RETRIEVE  →  Score all memories by recency + importance + relevance; return top-K
    ↓
REFLECT   →  IF importance_accumulator ≥ threshold:
                generate higher-level insights, store as reflection nodes (depth > 0)
    ↓
PLAN      →  Given retrieved memories + current state:
                generate/update high-level plan, decompose into immediate action
    ↓
ACT       →  Select and emit a CombatAction (move/attack/defend/ability/chat/wait)
```

### 5.3 Memory Stream

```python
class MemoryType(str, Enum):
    OBSERVATION = "observation"
    REFLECTION = "reflection"
    PLAN = "plan"

@dataclass
class MemoryNode:
    node_id: int
    turn_created: int
    last_accessed: int
    memory_type: MemoryType
    description: str              # natural language
    poignancy: int                # 1-10 importance score
    depth: int                    # 0 for observations, ≥1 for reflections
    embedding: Optional[List[float]]  # for relevance scoring (computed once at creation)
    subject: str                  # SPO triple for structured retrieval
    predicate: str
    object: str
    evidence_ids: List[int]       # provenance: which memories were synthesized (for reflections)
```

### 5.4 Retrieval Function

Scoring formula (from Park et al.):

    score = α_rec · recency + α_imp · importance + α_rel · relevance

where:

- recency = γ^(Δt), γ ∈ (0,1) decay factor, Δt = turns since creation. Default γ = 0.85.
- importance = poignancy / 10
- relevance = cosine_sim(embed(memory.description), embed(query)). Falls back to keyword overlap if no embedding model available.

All three are min-max normalized to [0, 1] before combining. Default: α_rec = α_imp = α_rel = 1. Return top-K (default K=7).

### 5.5 Reflection

Triggered when importance_accumulator ≥ threshold (default 50; Park et al. used 150 for daily timescale, we use 50 for combat's faster pace — reflects every ~5-8 turns).

Process:
1. Gather the 100 most recent memories (or all, if fewer).
2. LLM prompt: "Given these statements, what are 3 high-level questions we can answer?"
3. For each question, retrieve relevant memories via the retrieval function.
4. LLM prompt: "What insights can you infer? (cite evidence by statement number)"
5. Parse and store as MemoryNode(depth=1, type=REFLECTION).
6. Reset importance_accumulator.

Reflections participate in future retrievals — creating recursive reflection trees where higher-level abstractions build on lower-level ones.

### 5.6 Planning

Hierarchical, compressed for combat timescale:

- **High-level plan**: generated at battle start or after major events (ally dies, HP drops below threshold, new enemy appears). Example: "Focus fire on the mage first, then clean up melee fighters."
- **Immediate plan**: decomposed from high-level plan each turn. Example: "Move toward Lyra, then use Fireball next turn."
- Plans stored as MemoryNode(type=PLAN) and participate in retrieval.

### 5.7 Action Space

| Action | Description | Requirements |
|--------|-------------|--------------|
| `MOVE(tile)` | Move to adjacent tile | tile passable, within move_range |
| `ATTACK(target)` | Basic attack | target in attack_range, target alive |
| `DEFEND` | Raise defense | diminishing returns on consecutive use |
| `ABILITY(name, target/tile)` | Use a named ability | mana cost, cooldown, range |
| `CHAT(target, message)` | Initiate synchronous dialogue | target alive, costs initiator's action |
| `WAIT` | Do nothing | always available |

### 5.8 Modules

```
cognition/
├── cognitive_loop.py     # Orchestrates the full perceive→act cycle
├── perceiver.py          # Converts environment observations into MemoryNodes
├── memory_stream.py      # MemoryNode storage, indexing, serialization
├── retrieval.py          # Three-factor scoring: recency + importance + relevance
├── reflection.py         # Importance-triggered higher-level synthesis
├── planner.py            # Hierarchical plan generation and decomposition
├── decision.py           # Final action selection from plan + context
├── dialogue.py           # Synchronous dialogue sessions (see §6)
└── embeddings.py         # Embedding cache and providers (see §8)
```

---

## 6. Synchronous Dialogue Protocol

### 6.1 Mechanism

When agent a emits CHAT(target=b, message=m1), a **DialogueSession** opens. The exchange is bounded at L_max rounds (default: 2 in combat, 4 in pre-battle).

```
Agent a decides CHAT(target=b, message=m₁)
  │
  ▼
DialogueSession opens between a and b
  │
  ├── Round 1:  a says m₁
  │             b receives m₁, LLM generates response m₂ (+ continue/end flag)
  │
  ├── Round 2:  a receives m₂, LLM generates m₃ (+ continue/end flag)
  │             b receives m₃, LLM generates m₄ (+ continue/end flag)
  │
  └── Session closes (max rounds reached or either party signals end)
```

Each LLM response includes: `{"message": "...", "continue": true/false, "disposition_shift": float}`. The disposition_shift is the speaker's self-reported internal reaction, feeding into the social model.

### 6.2 Cost Asymmetry

During combat, the **initiator sacrifices their action** to start a dialogue, but the **responder answers for free** (interrupt). This creates genuine strategic tension: you burn a combat action to attempt negotiation.

During pre-battle, chat is a free action (no turn cost).

### 6.3 Memory Emission

After a session closes:

1. The full exchange is summarized into **one MemoryNode per participant**, from each agent's own perspective. Example:
   - For a: "Kael proposed an alliance with Lyra against Vorn. Lyra was cautious but agreed to a temporary truce."
   - For b: "Kael approached Lyra proposing a joint attack on Vorn. Lyra agreed to a truce but remains wary."

2. Nearby agents (within perception radius, not participants) receive an **overheard observation**: "Kael and Lyra were seen talking intensely near the east wall." — they get the fact of the conversation but not its content.

### 6.4 Data Model

```python
@dataclass
class DialogueSession:
    initiator: str
    responder: str
    turn_started: int
    max_rounds: int
    exchanges: List[DialogueExchange]
    status: Literal["active", "ended_by_initiator", "ended_by_responder", "max_rounds"]

@dataclass
class DialogueExchange:
    speaker: str
    message: str
    disposition_shift: float
    round_number: int
```

---

## 7. Dynamic Alliance System

### 7.1 Core Principle

Alliances are **not a game mechanic** — they are an **emergent property** of the social model. There is no "form alliance" button. Alliances emerge from conversations, consistent non-hostile behavior, and shared enemies. The environment controller *infers* alliance status from dispositions.

### 7.2 Alliance Inference

The environment controller maps dispositions to alliance status:

    alliance_status(a, b) =
        ALLIED   if d_a(b) > τ+ AND d_b(a) > τ+
        HOSTILE  if d_a(b) < τ- OR d_b(a) < τ-
        NEUTRAL  otherwise

where d_a(b) is agent a's disposition toward b, τ+ = 0.5, τ- = -0.3.

**Key asymmetry**: ALLIED requires mutual high disposition. HOSTILE requires only one party to be hostile. If a hates b but b likes a, status is HOSTILE — a will attack and b will be surprised.

### 7.3 Friendly Fire

Agents can always attack anyone — the system never hard-blocks. But attacking an ally causes a massive disposition collapse (effectively a betrayal). The LLM-driven cognition will naturally avoid this unless the agent has a deliberate reason.

| Alliance status | Attack allowed? | Consequence |
|-----------------|----------------|-------------|
| ALLIED | Yes, but penalized | Massive disposition drop, alliance breaks |
| NEUTRAL | Yes | Normal disposition shift |
| HOSTILE | Yes | No additional penalty |

### 7.4 Victory Conditions

- **Free-for-all (default)**: last individual standing. Alliances are tactical but temporary.
- **Team mode**: at battle start, a "team check" freezes current alliances into teams. Teams win together. Betrayal can break the team.
- **Last-faction-standing**: if all survivors are mutually ALLIED, they win collectively.

---

## 8. Embedding System

### 8.1 Bundled Default

Bundle `nomic-embed-text` (768-dim, ~275M params) via ollama. Runs on CPU.

### 8.2 Architecture

```
llm/
└── embeddings.py
    ├── EmbeddingProvider (ABC)
    ├── OllamaEmbeddings       # ollama pull nomic-embed-text
    ├── AnthropicEmbeddings    # via voyage-3-lite
    ├── OpenAIEmbeddings       # text-embedding-3-small
    └── EmbeddingCache         # LRU cache mapping text → vector
```

### 8.3 Usage

Memories are embedded once at creation time and cached. The query embedding is computed per retrieval call. The retrieval function's relevance component:

    relevance(m, q) = cosine_sim(embed(m.description), embed(q))

### 8.4 Fallback

If no embedding model is available, fall back to keyword overlap on SPO triples:

```python
def compute_relevance(memory, query, embedder):
    if embedder is not None:
        return cosine_sim(embedder.embed(memory.description), embedder.embed(query))
    else:
        return keyword_overlap(memory.keywords, extract_keywords(query))
```

### 8.5 Cache

```python
class EmbeddingCache:
    def __init__(self, provider: EmbeddingProvider, max_size: int = 2048):
        self._provider = provider
        self._cache: OrderedDict[str, List[float]] = OrderedDict()
        self._max_size = max_size

    def embed(self, text: str) -> List[float]:
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]
        vec = self._provider.embed([text])[0]
        self._cache[text] = vec
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return vec
```

---

## 9. LLM Adapter Layer

### 9.1 Interface

```python
from abc import ABC, abstractmethod
from typing import List, Optional

class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 512,
                 temperature: float = 0.7, response_format: Optional[str] = None) -> str: ...

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]: ...

    @property
    @abstractmethod
    def supports_embeddings(self) -> bool: ...

    @property
    @abstractmethod
    def name(self) -> str: ...
```

### 9.2 Adapters

- `anthropic_adapter.py` — Claude via anthropic SDK
- `ollama_adapter.py` — Local models via ollama REST API
- `vllm_adapter.py` — Local models via vLLM OpenAI-compatible API

### 9.3 Model Router

Maps (cognitive_step, agent_config) → adapter_instance. Different steps have different quality/cost needs:

| Cognitive Step | Quality Need | Suggested Model |
|----------------|-------------|-----------------|
| Action decision | HIGH | Claude Sonnet / GPT-4o / large local |
| Reflection | MEDIUM | Claude Haiku / small local |
| Importance rating | LOW | Heuristic table (no LLM call) |
| Dialogue response | HIGH | Strong model |
| Commentary | MEDIUM | Mid-tier |
| Embedding | N/A | nomic-embed-text / voyage-3-lite |

### 9.4 Modules

```
llm/
├── adapter.py               # ABC definition
├── anthropic_adapter.py
├── ollama_adapter.py
├── vllm_adapter.py
├── router.py                # Maps (step_type, agent) → adapter
└── prompts/
    ├── decision.py          # Action selection prompts
    ├── reflection.py        # Reflection generation prompts
    ├── planning.py          # Plan generation prompts
    ├── perception.py        # Observation summarization prompts
    ├── social.py            # Disposition assessment prompts
    ├── dialogue.py          # Dialogue exchange prompts
    └── commentary.py        # Narrator commentary prompts
```

---

## 10. Perception & Interaction

### 10.1 Perception Engine

Each turn, the environment controller generates perceptions for each agent:

1. **Spatial filter**: entities within the agent's perception radius on the grid.
2. **Knowledge update**: perceived facts are added to K_a; unperceived facts may decay.
3. **Observation generation**: each perceived entity/event becomes a MemoryNode(type=OBSERVATION).

Agents perceive *descriptions* of other agents' actions, not internal states. An agent sees "Kael moved toward Lyra" but not "Kael is planning to betray the alliance."

### 10.2 Interaction

Not hardcoded. The LLM-driven cognition decides how to respond to perceived entities based on personality, memories, plan, and social model. Possible interactions:

| Perceived Situation | Possible Agent Responses |
|---------------------|-------------------------|
| Hostile agent in range | Attack, Ability, Chat (threaten/parley) |
| Friendly/neutral agent | Chat (converse, propose alliance) |
| Common enemy / shared threat | Collaborate (emergent) |
| Object (potion, shrine) | Use item, move toward |

---

## 11. Game Flow

### 11.1 Phases

```
PHASE 1: SETUP
  Load/generate characters, place on grid, initialize memory streams

PHASE 2: PRE-BATTLE (6 ticks, configurable [4-8])
  Agents in staging area: converse, form relationships, gather info
  Simultaneous ticks (all agents act in parallel)
  Chat is free (no action cost), L_max = 4
  Larger perception radius (12 vs combat's default)
  Memories carry into combat

PHASE 3: COMBAT
  Turn-based on the battle grid (initiative order)
  Each turn: perceive → remember → retrieve → (reflect) → (plan) → act
  Chat costs initiator's action, L_max = 2
  Continue until victory condition met

PHASE 4: RESOLUTION
  Generate battle conclusion narrative
  Serialize final state for replay/analysis
  If campaign mode: compress memories, persist state
```

### 11.2 Pre-Battle Duration: 6 Ticks

Rationale: at 6 ticks each agent averages ~3 conversations, enough for:
- Two-hop information diffusion (A tells B, B tells C)
- At least one reflection trigger
- Alliance/enmity formation beyond initial backstory seeds

LLM budget: ~90 calls over 6 ticks (5 agents) ≈ $0.18 with Haiku-class models.

### 11.3 Victory Conditions

- **Last standing**: last alive agent/team wins (default)
- **Team mode**: alliance-frozen teams, win together
- **Last-faction-standing**: all survivors mutually ALLIED win collectively
- **Objective-based**: capture a point, hold for N turns (future)
- **Timed**: most HP remaining after T rounds (future)

---

## 12. Combat Mechanics

### 12.1 Action Resolution

The environment controller resolves actions against the world state:

- **MOVE**: validate tile passability and move_range, update position in grid and world state.
- **ATTACK**: validate range, compute damage = max(0, attacker.attack - target.defense) × uniform(0.8, 1.2), apply.
- **DEFEND**: add defend status effect (duration 1, magnitude 0.5). Diminishing returns: magnitude halves for each consecutive defend.
- **ABILITY**: validate mana, cooldown, range. Apply damage/effects. Supports AOE patterns.
- **CHAT**: trigger synchronous DialogueSession (see §6).
- **WAIT**: no-op.

### 12.2 Status Effects

```python
# Each status effect: {type, duration, magnitude, source}
# Examples: defend, poison, stun, buff_attack, debuff_defense
```

### 12.3 Modules

```
combat/
├── actions.py            # ActionType enum, CombatAction dataclass
├── action_resolver.py    # Resolves actions against world state
└── status_effects.py     # Buff/debuff system
```

---

## 13. Campaign Mode

### 13.1 Two Modes

```yaml
mode: "run_once"    # or "campaign"

campaign:
  battle_count: 5
  memory_carry: true
  memory_compression: true
  xp_progression: true
  roster_persistent: true
```

### 13.2 Run-Once Mode

Load characters → run pre-battle + combat → serialize final state → done. Memory exists only within the single battle.

### 13.3 Campaign Mode

After each battle:

1. **Memory Compression**: keep all reflections + top-K observations (by poignancy) + LLM-summarized "campaign memories" (depth=2 meta-reflections). Discard raw observations and stale plans.

```python
def compress_memories(memory: MemoryStream, keep_top_k: int = 20) -> MemoryStream:
    reflections = memory.get_by_type(REFLECTION)       # keep all
    observations = memory.get_by_type(OBSERVATION)
    observations.sort(key=lambda m: m.poignancy, reverse=True)
    top_observations = observations[:keep_top_k]

    remaining = observations[keep_top_k:]
    if remaining:
        summaries = llm_summarize_memories(remaining, max_summaries=3)
        campaign_nodes = [
            MemoryNode(type=REFLECTION, depth=2, description=s, poignancy=7)
            for s in summaries
        ]
    else:
        campaign_nodes = []

    compressed = MemoryStream()
    for node in reflections + top_observations + campaign_nodes:
        compressed.add(node)
    return compressed
```

2. **Social Model Persistence**: dispositions, trust, betrayal counts carry over.

3. **XP/Stat Progression** (optional): winners gain small stat boosts. Losers can return with a "grudge" backstory addition.

4. **Roster Management**: agents persist across battles. New agents can join; eliminated agents can be resurrected or retired.

### 13.4 State Serialization

```python
@dataclass
class CampaignState:
    campaign_id: str
    battle_number: int
    roster: List[AgentSnapshot]
    compressed_memories: Dict[str, List[MemoryNode]]
    battle_history: List[BattleResult]
    def save(self, path: str): ...
    @classmethod
    def load(cls, path: str) -> "CampaignState": ...

@dataclass
class BattleResult:
    battle_number: int
    winner: Optional[str]
    survivors: List[str]
    eliminated: List[str]
    turn_count: int
    summary: str     # LLM-generated narrative summary
```

### 13.5 Modules

```
campaign/
├── campaign_state.py       # CampaignState serialization
├── memory_compression.py   # Between-battle memory compression
└── progression.py          # XP, stat growth, roster management
```

---

## 14. Scalability

### 14.1 Current Target: 4–6 Agents

Per combat turn: ~11 LLM calls, ~2-4 seconds with parallel API calls. Sequential processing is fine.

### 14.2 Design-for-Scale Patterns (implement now)

**Agent-level parallelism**: each agent's cognitive loop is independent. Wrap in asyncio tasks:

```python
async def run_all_agents(agents, env):
    tasks = {a.name: asyncio.create_task(run_single_agent(a, env))
             for a in agents if a.is_alive()}
    results = await asyncio.gather(*tasks.values())
    return dict(zip(tasks.keys(), results))
```

**Model routing by agent importance**: agents in critical situations (low HP, high social activity) get the strong model; background agents get a cheaper one.

**Perception culling**: only include agents within perception radius + 2 tiles in the battlefield description.

**Batched embedding**: embed all new memories across all agents in a single batch call.

---

## 15. Frontend

### 15.1 Architecture

```
frontend/
├── server/
│   ├── app.py                # Flask/Django (serves pages + API)
│   ├── api/
│   │   ├── movement.py       # GET /movement/<step> — movement JSON
│   │   ├── state.py          # GET /state — current world state
│   │   └── control.py        # POST /advance, /start, /pause
│   └── templates/
│       └── arena.html        # Main page: Phaser canvas + UI panels
├── static/
│   ├── js/
│   │   ├── game.js           # Phaser scene: grid, sprites, animations
│   │   ├── ui.js             # Sidebar: persona cards, kill feed, chat
│   │   └── api.js            # Fetch wrappers
│   ├── assets/               # tiles/, sprites/, ui/
│   └── css/
│       └── arena.css
```

### 15.2 UI Panels

- **Grid view** (Phaser canvas): top-down tile grid, animated sprites, HP/mana bars, terrain.
- **Persona cards** (sidebar): name, class, HP/mana, current action, reasoning, personality.
- **Battle chat** (overlay): real-time agent-to-agent dialogue.
- **Kill feed** (sidebar): chronological combat event log.
- **Commentary** (banner): LLM-generated narrator commentary per round.
- **Memory inspector** (modal, debug): click agent to see memory stream, reflections, plan.

---

## 16. Full Project Structure

```
battle-agents/
├── ontology/                    # Layer 0: Formal ontology
│   ├── domain.py
│   ├── relations.py
│   ├── world_state.py
│   ├── knowledge.py
│   └── schemas.py
│
├── world/                       # Layer 1: Environment
│   ├── world_graph.py
│   ├── environment.py
│   ├── battle_grid.py
│   ├── turn_manager.py
│   ├── perception_engine.py
│   └── alliance_resolver.py
│
├── agent/                       # Layer 2: Agent data model
│   ├── agent.py
│   ├── identity.py
│   ├── attributes.py
│   ├── knowledge.py
│   ├── social_model.py
│   ├── goals.py
│   └── plans.py
│
├── cognition/                   # Layer 3: Cognitive loop
│   ├── cognitive_loop.py
│   ├── perceiver.py
│   ├── memory_stream.py
│   ├── retrieval.py
│   ├── reflection.py
│   ├── planner.py
│   ├── decision.py
│   ├── dialogue.py
│   └── embeddings.py
│
├── combat/                      # Combat mechanics
│   ├── actions.py
│   ├── action_resolver.py
│   └── status_effects.py
│
├── llm/                         # Layer 4: LLM adapters
│   ├── adapter.py
│   ├── anthropic_adapter.py
│   ├── ollama_adapter.py
│   ├── vllm_adapter.py
│   ├── router.py
│   └── prompts/
│       ├── decision.py
│       ├── reflection.py
│       ├── planning.py
│       ├── perception.py
│       ├── social.py
│       ├── dialogue.py
│       └── commentary.py
│
├── campaign/                    # Campaign mode
│   ├── campaign_state.py
│   ├── memory_compression.py
│   └── progression.py
│
├── frontend/                    # Layer 5: Visualization
│   ├── server/
│   └── static/
│
├── config/
│   ├── characters/              # Character preset YAMLs
│   ├── game_config.yaml
│   └── llm_config.yaml
│
├── runner.py                    # Main entry point
├── tests/
└── README.md
```

---

## 17. Implementation Roadmap

### Phase 1: Ontology + World + Agent Shell *(no LLM)*

Build the data backbone. End state: agents placed on a grid, environment ticks forward with random/scripted actions, world state and agent knowledge are inspectable.

**Modules**: `ontology/`, `world/`, `agent/`, `combat/actions.py`, `combat/action_resolver.py`

### Phase 2: Memory + Retrieval + Embeddings + Basic Decision

Wire up the cognitive core. End state: agents make LLM-driven combat decisions informed by their memory stream.

**Modules**: `llm/adapter.py` + adapters, `cognition/memory_stream.py`, `cognition/retrieval.py`, `cognition/embeddings.py`, `cognition/decision.py`, `cognition/cognitive_loop.py`

### Phase 3: Dialogue + Social Model + Reflection + Planning

Emergence starts. End state: agents talk, form alliances, reflect on experience, plan ahead.

**Modules**: `cognition/dialogue.py`, `cognition/reflection.py`, `cognition/planner.py`, `agent/social_model.py`, `world/alliance_resolver.py`

### Phase 4: Pre-Battle Phase + Game Flow

Full two-phase simulation: social → combat. End state: end-to-end playable.

**Modules**: `world/turn_manager.py` (pre-battle mode), game flow orchestration in `runner.py`

### Phase 5: Campaign Mode

Persistence across battles. End state: multi-battle campaigns with compressed memory carryover.

**Modules**: `campaign/`

### Phase 6: Frontend + Polish

Visual interface. End state: watchable, interactive simulation in the browser.

**Modules**: `frontend/`

---

## 18. Key Architectural Invariants

These are non-negotiable design constraints:

1. **WorldState is the single source of truth.** Agents never read it directly. All information flows through the perception engine.

2. **Agent knowledge can diverge from ground truth.** K_a ⊆ P(R) is a subjective, possibly wrong view. This is the mechanism for surprise, misinformation, and dramatic irony.

3. **Every cognitive step produces structured JSON.** The prompt layer bridges symbolic ontology and neural generation. All LLM outputs are parsed into typed data structures.

4. **Chat is a first-class combat action.** Initiating dialogue costs the agent's action during combat. The responder answers for free. This creates genuine strategic tension between fighting and diplomacy.

5. **Alliances are emergent, not mechanical.** No "form alliance" button. The environment controller infers alliance status from disposition thresholds. ALLIED requires mutual consent; HOSTILE is unilateral.

6. **Reflections form recursive trees.** Reflections can be built on other reflections (increasing depth). Campaign mode extends this across battles with depth=2 meta-reflections.

7. **The adapter pattern isolates all LLM calls.** Switching between Claude, ollama, and vLLM should require only changing configuration, not code.

---

## 19. Configuration Reference

### game_config.yaml

```yaml
mode: "run_once"              # "run_once" or "campaign"

grid:
  width: 20
  height: 15

pre_battle:
  enabled: true
  duration_ticks: 6
  tick_mode: simultaneous
  chat_max_rounds: 4
  perception_radius: 12

combat:
  chat_max_rounds: 2
  perception_radius: 8
  reflection_threshold: 50
  retrieval_top_k: 7
  retrieval_decay: 0.85

alliance:
  allied_threshold: 0.5
  hostile_threshold: -0.3

victory:
  mode: "last_standing"       # "last_standing", "team", "last_faction"

campaign:
  battle_count: 5
  memory_carry: true
  memory_compression: true
  compression_keep_top_k: 20
  xp_progression: true
  roster_persistent: true
```

### llm_config.yaml

```yaml
default_adapter: "ollama"

adapters:
  anthropic:
    api_key_env: "ANTHROPIC_API_KEY"
    strong_model: "claude-sonnet-4-20250514"
    cheap_model: "claude-haiku-4-5-20251001"
  ollama:
    base_url: "http://localhost:11434"
    strong_model: "llama3.1:70b"
    cheap_model: "llama3.1:8b"
  vllm:
    base_url: "http://localhost:8000"
    model: "meta-llama/Llama-3.1-8B-Instruct"

embedding:
  provider: "ollama"
  model: "nomic-embed-text"
  cache_size: 2048

routing:
  action_decision: "strong"
  reflection: "cheap"
  dialogue: "strong"
  planning: "strong"
  commentary: "cheap"
  importance_rating: "heuristic"  # use POIGNANCY_TABLE, no LLM call
```
