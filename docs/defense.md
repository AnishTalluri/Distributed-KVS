# Distributed KVS — Design Defense Doc

**Project**: [Distributed-KVS](https://github.com/AnishTalluri/Distributed-KVS)
**Current tag**: `v0.1.1-part1-defended`
**Status**: Part 1 complete and defensible. Parts 2-4 in progress.

## Purpose

This doc is my interview prep artifact for the Distributed KVS project. Every major design decision in the codebase is captured here with: the choice, the alternatives considered, the rationale, tradeoffs accepted, and drill questions I should be able to answer cold. Before any interview where this project comes up, I re-read this and self-quiz using the questions in the appendix.

## Companion materials

- **Repo**: `~/Distributed-KVS` (WSL) / [github.com/AnishTalluri/Distributed-KVS](https://github.com/AnishTalluri/Distributed-KVS)
- **Notebook**: short-form paper notes for common terms, patterns, wrong-answers-I've-made
- **Kuper lectures**: CSE 138 Distributed Systems by Lindsey Kuper (YouTube). See lecture map below.

## How to use this doc

- **Before an interview**: read the pitch section out loud until it flows. Skim the TL;DR of each drill. Use the self-quiz appendix to test recall on any drill where the TL;DR feels uncertain.
- **Between coding sessions**: add new drills as we drill new design choices. Every choice gets its own entry.
- **When drilled in an interview**: don't recite the doc. Answer in your own words, using the doc's rationale as a mental scaffold.

## The 30-second pitch (memorize)

> This is a distributed key-value store I'm building in stages. Currently it's at the single-node stage: a Python service running in a Docker container, exposing four HTTP endpoints — GET all keys, GET one, PUT, DELETE — backed by an in-memory Python dictionary. The goal across the full project is to add replication so writes go to multiple nodes, then causal consistency so those nodes agree on the order of updates without a central coordinator, then sharding so the data is partitioned across the cluster instead of duplicated. Right now I've completed the single-node baseline. I'm working on the replication layer next.

**Common mistakes I've made and corrected**:
- Calling it "distributed" when it's currently single-node (wrong — it's *building toward* distributed)
- Saying "Byzantine" to mean fault tolerance (wrong — Byzantine = nodes that lie, not nodes that die)
- "Updates itself through HTTP methods" (wrong — the server responds to client requests; it doesn't self-update)

## Kuper lecture map

| Lecture | Topic | When needed |
|---|---|---|
| 1 | What is a distributed system, why it's hard, non-determinism | Foundational — done |
| 2 | Time, clocks, ordering, happens-before | Before Part 3 |
| 3 | Lamport clocks, logical time | Before Part 3 |
| 4 | Vector clocks, causal ordering | Before Part 3 |

Parts 1 and 2 don't require additional lectures beyond Lecture 1. Lectures 2-4 should be watched during Part 2 coding to be ready for Part 3.

## Table of contents

- [Part 1: Single-Node KVS](#part-1-single-node-kvs)
  - [Drill 1 — Project pitch and foundations](#drill-1--project-pitch-and-foundations)
  - [Drill 2 — Concurrent client handling](#drill-2--concurrent-client-handling)
  - [Drill 3 — Browser environment](#drill-3--browser-environment)
  - [Drill 4 — FastAPI over Flask](#drill-4--fastapi-over-flask)
  - [Drill 5 — HTTPException vs JSONResponse](#drill-5--httpexception-vs-jsonresponse)
  - [Drill 6 — Host binding 0.0.0.0](#drill-6--host-binding-0000)
  - [Drill 7 — Four status codes](#drill-7--four-status-codes)
  - [Drill 8 — Docker layer caching](#drill-8--docker-layer-caching)
  - [Drill 9 — Why containerize](#drill-9--why-containerize)
  - [Drill 10 — Module-scope store, Part 2 handoff](#drill-10--module-scope-store-part-2-handoff)
- [Self-quiz appendix](#self-quiz-appendix)

---

# Part 1: Single-Node KVS

## Drill 1 — Project pitch and foundations

**TL;DR**: Multi-stage distributed KVS. Part 1 is single-node, in-memory, in Docker. Focused on the API contract before adding replication (Part 2), causal consistency (Part 3), and sharding (Part 4).

### 1a. Distributed system defined at three levels

**Level 1 (what it is)**: A system made of multiple computers that coordinate over a network to solve a single problem or serve a single logical service to clients.

**Level 2 (why it matters here)**: We're building toward a distributed KVS across Parts 2-4. Part 1 is single-node — a baseline to lock down the API contract. Parts 2 onward add replication, causal consistency, and sharding across multiple nodes. We chose to build in stages so the API stays constant while the internals evolve.

**Level 3 (what breaks without it)**: Without distribution, we have a single point of failure (one node dies, service dies) and a fixed ceiling on throughput (one machine's CPU/RAM/network). Every problem the rest of the project solves — replication, consistency, sharding — only exists because we chose to distribute.

**Common misuse to avoid**: Fault tolerance is a *goal* of distributed systems, not a *definition*. Calling any single-node system with backups "distributed" is wrong.

### 1b. In-memory Python dict as Part 1 storage

**Choice**: Standard Python `dict` at module scope in `src/kvs/main.py`, no persistence.

**Alternatives considered**:
- SQLite (persistent, no extra deps, but SQL overhead unnecessary for KV)
- File I/O with JSON dump on every mutation (persistent, but slow and race-prone)
- Redis (fast + persistent, but external dependency defeats the "build a KVS" learning goal)
- LevelDB/RocksDB (production-grade, but overkill for Part 1)

**Rationale**: Simplest thing that meets Part 1's requirements. O(1) average-case operations. Zero external dependencies. Direct 1:1 match with the spec's logical key-value model. Lets us focus on API contract and HTTP correctness before worrying about storage semantics.

**Tradeoffs accepted**:
- No persistence — data lost on container restart. Acceptable because Part 1 spec doesn't require durability.
- Bounded by container RAM. Acceptable at test scale.
- State isolated to this process — becomes the central Part 2 problem (see Drill 10).
- Concurrency safety is accidental via CPython's GIL, not by design (see Drill 2).

### Drill questions

1. What is a distributed system, at three levels of depth?
2. What does "in-memory" mean, technically?
3. Why not use a database?
4. What happens if the container restarts?
5. What's the time complexity of your reads and writes, and why?
6. Two clients PUT the same key at the same instant. What happens? (Full answer in Drill 2.)
7. In Part 2, why can't Node A just read Node B's dict directly? (Full answer in Drill 10.)

**See also**: Drill 2 (concurrent handling on this dict), Drill 10 (module-scope store lifecycle).

---

## Drill 2 — Concurrent client handling

**TL;DR**: Two concurrent PUTs to the same key both succeed. Last-writer-wins. Safety comes from the fact that there's no `await` between the check and the set — the critical section is atomic *by code layout*, not by explicit lock. Fragile.

### Q1 — What makes concurrent request handling possible?

Two layers:
1. The OS kernel accepts both TCP connections at the socket layer.
2. uvicorn's asyncio event loop dispatches each connection as a coroutine on a single thread.

`await` is *not* the answer — it's what enables coroutine switching *after* dispatch.

### Q2 — Where does a task suspend?

`body = await request.json()`. Suspends because reading the body is network I/O (bytes arrive over TCP at unpredictable speed). Other lines are CPU-bound dict operations that complete instantly, so no await needed.

### Q3 — What makes check-and-set safe from interleaving?

The rule: event loop only switches tasks at `await` expressions. There is no await between `if key in store` and `store[key] = value`, so the critical section runs atomically within one task.

### Q4 — Timeline of two concurrent PUTs

- **T0**: Both connections accepted, both tasks queued.
- **T1**: Event loop runs Task A briefly, A suspends at await.
- **T2**: Event loop runs Task B briefly, B suspends at await.
- **T3**: B's body arrives first, B resumes, commits, returns 201.
- **T4**: A's body arrives, A resumes, sees key exists, commits, returns 200.

Final state: `store["foo"] = A's value`. Last-writer-wins.

### Q5 — Robust or fragile?

Fragile. No explicit locks. Safety is inherited from the coincidence that there's no await between the check and the set. Adding `await write_to_disk()` between them would silently introduce a race condition.

### GIL note

CPython's Global Interpreter Lock also ensures that `dict[key] = value` is a single atomic bytecode operation. This provides an additional safety layer we didn't design for — a language-specific accident. In Part 2, when nodes communicate across the network, the GIL no longer protects us because it only applies within a single Python process.

### Drill questions

1. Does `async` prevent or enable concurrency? Explain.
2. Point to the exact line where a coroutine suspends. Why does it suspend there?
3. Two tasks are in flight. Can the event loop switch from Task A to Task B mid-function? Under what condition?
4. If we added persistence with `await write_to_disk(...)` between the check and the set, what breaks?
5. Why does the GIL save us here, and why does it stop saving us in Part 2?
6. Is this design robust or fragile? Name one specific change to the code that would break the safety.

**See also**: Drill 4 (FastAPI's async model), Drill 10 (why process-local state means Part 2 = replication).

---

## Drill 3 — Browser environment

**TL;DR**: No, this KVS can't run in a browser. Browsers are sandboxed clients — they can't bind ports, don't run Python, and code lifecycle is tied to the tab. A browser can only *talk to* my KVS, not host it.

### Dependencies my KVS has that browsers don't provide

1. **CPython runtime** — browsers execute JS/WASM, not Python bytecode.
2. **Listening TCP socket on port 8081** — browsers cannot bind ports; the sandbox forbids it.
3. **Long-lived server process** — browser code lifecycle is tied to the tab; close tab, code stops.
4. **Multi-client access to shared state** — each browser is isolated; no cross-browser direct connection is possible.

### What a browser can be here

A client. It can send HTTP requests to my KVS (running on a server). It cannot host the KVS itself.

### Common mistake to avoid

`localhost` is a *network address*, not a *runtime environment*. Curl on localhost and a browser on localhost both mean "client on this same machine" — the server is still running as a native OS process.

### Drill questions

1. What runtime does a browser provide?
2. Why can't browsers bind to a port?
3. What's the difference between a client and a server?
4. If I wanted my KVS to be usable from a browser, what would the architecture look like? (Answer: browser stays as client, my KVS keeps running as a server on some machine, browser makes HTTP calls to it — which is already the case.)
5. What browser feature comes closest to a "long-lived server-like process"? (Answer: service workers. Still can't bind sockets.)

**See also**: Drill 6 (`--host 0.0.0.0` — also about network binding semantics).

---

## Drill 4 — Why FastAPI over Flask

**TL;DR**: FastAPI is async-first, Flask is sync-first. Part 2 replication requires fan-out to N peer nodes concurrently via `asyncio.gather`. In FastAPI that's one line; in Flask it would require the Quart extension or a redesign. Bonus: Pydantic body validation and auto-generated OpenAPI docs.

### Decision

FastAPI, built on Starlette/ASGI.

### Alternatives considered

- Flask (sync-first, would need Quart or async extensions for Part 2)
- Raw Starlette (too low-level; FastAPI adds validation, DI, docs on top)
- Node.js/Express (out of scope — project is Python-only)

### Rationale

The Part 2 replication protocol requires each node to fan out writes to N peer nodes over HTTP and wait for acknowledgments. In an async-first framework, those N peer calls run concurrently via `asyncio.gather()`, so total latency ≈ slowest single round-trip. In a sync framework, they'd run sequentially, so latency ≈ sum of all round-trips. FastAPI's async-native design makes concurrent fan-out the natural, idiomatic way to write the code.

### Secondary benefits (not the reason we picked it)

- Pydantic-based automatic request-body validation from type hints
- Auto-generated OpenAPI/Swagger docs at `/docs`

### Tradeoffs accepted

- Async code is harder to reason about than sync (race conditions from misplaced awaits are possible — see Drill 2)
- Newer framework, slightly smaller community than Flask (irrelevant for this project)

### Common bad answers to avoid

- "FastAPI is faster" — meaningless; both frameworks serve simple requests at wire speed
- "It has type hints" — Python has type hints; frameworks don't own that
- "It handles concurrency for me" — the event loop handles concurrency; FastAPI just exposes it

### Drill questions

1. What's ASGI vs WSGI?
2. Concretely, how does `asyncio.gather()` help Part 2 replication?
3. If I used Flask, what would I need to change to make Part 2 work?
4. Does FastAPI prevent race conditions? Why or why not?

**See also**: Drill 2 (async concurrency mechanics).

---

## Drill 5 — HTTPException vs JSONResponse

**TL;DR**: Exceptions for abnormal flow (errors, aborts), returns for normal flow (successful completion). General programming principle, not a FastAPI-specific rule.

### Decision

- `raise HTTPException` for error paths
- `return JSONResponse` (or bare `return`) for success paths

### Rationale

Reflects the general programming principle — exceptions are for abnormal flow (aborts, errors), returns are for normal flow (successful completion). FastAPI's exception handler catches `HTTPException`, formats it into a consistent JSON error response shape, and integrates with middleware/logging. Bare `return` gets the default status code (200); `JSONResponse` is used when the status code isn't the default (e.g., 201).

### Alternatives considered

- Use `raise HTTPException` for everything, including success: semantically wrong (success isn't an exception), confuses debuggers/readers.
- Use `return JSONResponse` for everything, including errors: loses FastAPI's consistent error formatting, harder to bubble errors up from helper functions, no middleware hook for exceptions.

### Three patterns actually in the code

- `GET /data` → `return {"keys": [...]}` — bare return, 200 by default
- `PUT` create → `return JSONResponse(status_code=201, ...)` — non-default success
- Any error → `raise HTTPException(status_code=..., detail=...)` — abort with error

### Drill questions

1. Why not use `HTTPException` for success codes?
2. Why not use `JSONResponse` for errors?
3. What's the default status code when you just `return` from a handler?
4. If a helper function three layers deep hits an error, how does the error get to the client?
5. What does FastAPI's built-in exception handler actually do with an `HTTPException`?

**See also**: Drill 7 (the specific status codes we return).

---

## Drill 6 — Host binding 0.0.0.0

**TL;DR**: `0.0.0.0` = wildcard bind meaning "listen on all interfaces." Required inside containers because the container has its own network namespace, and Docker's port forwarding routes traffic through the container's *external* interface. Binding only to `127.0.0.1` (loopback) means Docker's forwarded traffic finds nothing listening.

### Decision

uvicorn binds to `0.0.0.0` (all interfaces) rather than the default `127.0.0.1` (loopback).

### Rationale

A Docker container has its own network namespace with its own loopback and external interfaces, separate from the host's. Docker's port forwarding (`-p 8081:8081`) routes traffic into the container's external interface. If uvicorn binds only to `127.0.0.1`, it listens on the container's internal loopback only, and the forwarded traffic finds nothing listening on the external interface — connection refused. Binding to `0.0.0.0` tells uvicorn to listen on all interfaces, including the external one Docker uses.

### What would break without it

- Container starts fine
- `curl http://localhost:8081` from host returns connection refused
- All integration tests fail
- Silent failure mode — no error in container logs

### Security note

`0.0.0.0` = "accept from anywhere" is safe here *because the container is the trust boundary*. Docker controls what "anywhere" actually resolves to. In production on bare metal, `0.0.0.0` combined with public internet exposure would be a mistake without additional controls (firewall, reverse proxy, auth).

### Interview trap

`0.0.0.0` is valid as a *bind* address (server-side, means "all interfaces") but invalid as a *destination* address (client-side — you can't send a packet to "everywhere"). Same string, opposite meanings depending on context.

### Drill questions

1. What's the difference between `127.0.0.1` and `0.0.0.0`?
2. Why does `curl` from my host fail if I bind to `127.0.0.1` inside a container?
3. Is `0.0.0.0` a security risk here? Why or why not?
4. If I wanted to only allow connections from Docker's port forwarding (not other container-internal processes), could I? (Answer: not straightforwardly — bind-side control is by interface, not by source. That's a firewall's job.)

**See also**: Drill 3 (client vs server distinction), Drill 9 (why containerize in the first place).

---

## Drill 7 — Four status codes

**TL;DR**: 200 = success, 201 = created, 400 = malformed request, 404 = missing key. 4xx = client's fault (fix your request). 5xx = server's fault (retry might work). Interview trap: 404 leaks existence info in enumerable ID spaces.

### Codes used

- 200 OK — successful GET, successful PUT update, successful DELETE
- 201 Created — successful PUT that created a new key (didn't previously exist)
- 400 Bad Request — malformed body (missing JSON, missing "value" field)
- 404 Not Found — GET or DELETE on a key that doesn't exist

### Semantic classes

- 2xx = success
- 4xx = client error (fix your request, don't retry as-is)
- 5xx = server error (my problem, retry might work)

### 400 vs 404 distinction

- 400 = "your request is broken"
- 404 = "your request is fine, but the thing you asked about doesn't exist"

Both are the client's fault semantically (4xx), but distinguishing them tells the client whether to fix the request or accept that the resource is missing.

### When 404 is arguably the wrong choice

- **Enumeration risk**: if key existence is sensitive (e.g., `user:12345`), 404 leaks which IDs exist. Attacker probes keys, distinguishes 404 from 200 responses, enumerates valid IDs. Some APIs return 403 for both "missing" and "forbidden" to hide the distinction.
- **REST purism**: some argue the endpoint `/data/{key}` *is* a valid URL that the server understood, so a missing value should be 204 or 200-with-null, not 404. Taste question.

### Codes not used (yet), and why

- 204 No Content — could argue DELETE should return this. We use 200 with a message body for consistency.
- 409 Conflict — not applicable; we allow overwrite on PUT.
- 500 Internal Server Error — used implicitly by FastAPI when unhandled exceptions occur (e.g., the `body[key]` bug earlier).
- 503 Service Unavailable — will matter in Part 2 when a node can't reach enough peers to commit a write.

### Drill questions

1. What's the difference between 400 and 404?
2. What's the difference between 4xx and 5xx?
3. Why might you *not* use 404 for a missing key?
4. Which status code would you return in Part 2 if a write can't reach all peer nodes? (Answer: 503 or 500 depending on failure mode.)
5. Should DELETE return 200 or 204? Defend your choice.

**See also**: Drill 5 (mechanism for returning these codes).

---

## Drill 8 — Docker layer caching

**TL;DR**: Every Dockerfile line is a cached layer. Cache invalidation cascades forward. Put slow-changing inputs (dependencies) before fast-changing inputs (source code) so `pip install` stays cached across every code edit. Correct ordering ≈ 2s rebuilds; swapped ordering ≈ 30-60s rebuilds.

### Decision

Copy `requirements.txt` and run `pip install` before copying the application source code.

### Rationale

Docker builds images as a stack of cached layers. Each Dockerfile line produces one layer. Cache invalidation cascades forward — invalidating a layer invalidates everything after it. By placing slow-changing inputs (`requirements.txt`, ~30-60s pip install) *before* fast-changing inputs (source code, changes every edit), we keep the expensive install layer cached across all normal development builds. Only source-code copy and the trailing no-op layers re-run on a code edit.

### Impact

- Correct ordering: rebuild after code edit ≈ 2 seconds (source-copy layer + trailing no-ops)
- Swapped ordering: rebuild after code edit ≈ 30-60 seconds (source-copy invalidates pip install cache)

### Why it matters beyond speed

Fast rebuilds → rebuild often → test in the containerized environment on every change → catch container-specific bugs early. Slow rebuilds → skip rebuilds → develop outside the container → ship broken images.

### When cache does need to be busted

- `requirements.txt` changes (new dep, version bump) → pip install re-runs. Correct behavior.
- Base image bump (e.g., `python:3.12-slim` → `python:3.13-slim`) → everything re-runs. Rare.

### Drill questions

1. What is a Docker layer?
2. When does Docker invalidate a cached layer?
3. What does "cache invalidation cascades forward" mean?
4. If pip install were fast (say 2 seconds), would this ordering still matter? (Answer: less critical but still good practice — total build time savings still add up.)
5. What if you had two different files that change at different rates — how would you order them? (Answer: rarer-changing first.)

**See also**: Drill 9 (why we containerize at all).

---

## Drill 9 — Why containerize

**TL;DR**: Runtime isolation, reproducibility, deployable artifact, and multi-node simulation. Not "consistency across environments" alone — unpack it. Specifically for a distributed systems project, containers = the mechanism for running N isolated nodes on one laptop.

### Decision

Package the KVS as a Docker container image rather than shipping the Python source and requiring users to run `python main.py`.

### Rationale, in order of importance for this project

1. **Dependency and runtime isolation**: The image freezes the Python version (3.12-slim), OS libraries, and all pip packages. My laptop's system Python doesn't leak in; container packages don't leak out. `venv` handles pip package isolation but not Python version or system libraries.

2. **Runtime reproducibility**: The same image behaves identically on my machine, another dev's Mac, a CI runner, or a cloud VM. Code is easy to share (git); runtimes are not. Docker captures the whole runtime, not just the code.

3. **Standard deployable artifact**: Kubernetes, ECS, Cloud Run, Fargate, docker-compose all consume container images. Producing an image (rather than source + install docs) makes the project deployable in a way every modern platform understands.

4. **Network and process namespace for multi-node simulation**: A container is a self-contained "machine" with its own network stack and process tree. This is essential for Part 2, where I'll run 3 nodes as 3 containers on one laptop. Without containers, simulating an N-node cluster locally means juggling ports and processes manually.

### What Docker does NOT give you (common confusion)

- Fast rebuilds — that's a consequence of Dockerfile *design* (layer ordering, see Drill 8), not the choice to containerize.
- "Organization" — filesystems already organize code. Container = runtime isolation, not code organization.
- "One-command startup" — a bash script does that too. Docker gives you *reproducible* one-command startup.

### Alternatives considered

- Bare `python main.py` + README — no isolation, no runtime capture, no multi-node story
- Python venv only — handles pip deps but not Python version, system libs, or process isolation
- Vagrant/VM — heavier, slower, older-generation tooling for the same goals

### Drill questions

1. What does Docker isolate that venv doesn't?
2. If my app works on my Mac, why might it break on a Linux server without Docker?
3. What's the artifact you'd deploy to Kubernetes — source code or an image?
4. Why is containerization specifically important for a *distributed* systems project?
5. Is a Docker container a VM? (Answer: no, it shares the host kernel. VMs run a full guest OS.)

**See also**: Drill 6 (`--host 0.0.0.0` — a consequence of container networking), Drill 8 (layer caching — a Dockerfile *design* concern), Drill 10 (multi-node needs container isolation).

---

## Drill 10 — Module-scope store, Part 2 handoff

**TL;DR**: `store` lives in this process's RAM. When Part 2 introduces N nodes, each node runs its own process with its own dict — separate memory spaces. Writes to Node A don't magically appear on Node B. That's the problem replication solves. **Critical distinction: replication ≠ persistence.** Part 2 keeps everything in RAM; it just makes sure multiple RAM copies stay in sync.

### Where store lives

In the RAM of the Python process running inside the container. Bound to that specific process's memory space.

### Lifecycle

Process starts → OS allocates memory → `store = {}` creates the dict object in that memory. Process ends (container stops, crashes, restarts) → OS reclaims memory → dict ceases to exist. No persistence.

### Why this is fine for Part 1

The Part 1 goal is validating the API contract (four endpoints, correct status codes, correct request/response shapes). Durability is out of scope. In-memory dict is the simplest thing that lets us focus on the contract.

### Why this design becomes the central problem in Part 2

The `store` variable is bound to *this process's* memory. When Part 2 introduces multiple nodes, each node runs its own Python process — each with its own `store` dict. Three separate dicts, no shared state.

Consequence: a `PUT /data/foo` to Node A only touches Node A's dict. Node B and Node C's dicts are unchanged. A subsequent `GET /data/foo` routed to Node B returns 404 — from the client's perspective, the write vanished.

**Replication** is the coordination code we write so a write to any node ends up on all nodes, keeping the separate dicts in sync.

### Critical distinction — replication vs persistence

- **Persistence** = data survives *process restart*. Achieved via disk.
- **Replication** = data lives on *multiple machines simultaneously*. Achieved via nodes talking to each other.

These solve different failure modes:
- Persistence handles "process restarted, do I still have my data?"
- Replication handles "one machine died, do other machines still have the data?"

Part 2 is replication only. All dicts remain in RAM. Persistence is not added in Parts 2, 3, or 4.

### Full arc for context

- **Part 1**: one process, one dict in RAM. Simple, non-distributed baseline.
- **Part 2**: multiple processes, replicated dicts. Solves single-node failure.
- **Part 3**: causal consistency on top of replication. Guarantees dicts eventually converge in a way that respects operation order.
- **Part 4**: sharding. Each dict owns a slice of the keyspace instead of a full copy.

### Drill questions

1. Where does the `store` dict physically live?
2. What happens to `store` when the container restarts?
3. If Node A's `store` and Node B's `store` are two separate dicts, how does a PUT to A ever end up on B?
4. Is replication the same as persistence? What's the difference?
5. If I added disk persistence to Part 1, would that make it a distributed system? (Answer: no. Still one node. Persistence and distribution are orthogonal.)
6. In Part 2, what happens if all three containers restart simultaneously? (Answer: all data lost, same as Part 1. Replication doesn't save you from correlated failures.)

**See also**: Drill 1 (in-memory dict as Part 1 choice), Drill 2 (concurrency on this dict).

---

# Self-quiz appendix

Read a question, answer out loud without scrolling to the drill. If you fumble, review the corresponding drill.

### Drill 1

1. What is a distributed system, at three levels of depth?
2. What does "in-memory" mean, technically?
3. Why not use a database for Part 1?
4. What happens if the container restarts?
5. What's the time complexity of your reads and writes, and why?

### Drill 2

1. Does `async` prevent or enable concurrency?
2. Point to the exact line where a coroutine suspends. Why does it suspend there?
3. Can the event loop switch tasks mid-function? Under what condition?
4. If we added `await write_to_disk(...)` between the check and set, what breaks?
5. Why does the GIL save us here, and why does it stop saving us in Part 2?
6. Two clients PUT the same key at the same instant. Walk me through the timeline.

### Drill 3

1. What runtime does a browser provide?
2. Why can't browsers bind to a port?
3. What's the difference between a client and a server?
4. If I wanted my KVS to be usable from a browser, what would the architecture look like?
5. What browser feature comes closest to a "long-lived server-like process"?

### Drill 4

1. What's ASGI vs WSGI?
2. Concretely, how does `asyncio.gather()` help Part 2 replication?
3. If I used Flask, what would I need to change to make Part 2 work?
4. Does FastAPI prevent race conditions? Why or why not?

### Drill 5

1. Why not use `HTTPException` for success codes?
2. Why not use `JSONResponse` for errors?
3. What's the default status code when you just `return` from a handler?
4. If a helper function three layers deep hits an error, how does the error get to the client?
5. What does FastAPI's built-in exception handler actually do with an `HTTPException`?

### Drill 6

1. What's the difference between `127.0.0.1` and `0.0.0.0`?
2. Why does `curl` from my host fail if I bind to `127.0.0.1` inside a container?
3. Is `0.0.0.0` a security risk here? Why or why not?
4. If I wanted to only allow connections from Docker's port forwarding, could I?

### Drill 7

1. What's the difference between 400 and 404?
2. What's the difference between 4xx and 5xx?
3. Why might you *not* use 404 for a missing key?
4. Which status code would you return in Part 2 if a write can't reach all peer nodes?
5. Should DELETE return 200 or 204?

### Drill 8

1. What is a Docker layer?
2. When does Docker invalidate a cached layer?
3. What does "cache invalidation cascades forward" mean?
4. If pip install were fast, would the ordering still matter?
5. If you had two files that change at different rates, how would you order them?

### Drill 9

1. What does Docker isolate that venv doesn't?
2. If my app works on my Mac, why might it break on a Linux server without Docker?
3. What's the artifact you'd deploy to Kubernetes?
4. Why is containerization specifically important for a distributed systems project?
5. Is a Docker container a VM?

### Drill 10

1. Where does the `store` dict physically live?
2. What happens to `store` when the container restarts?
3. If Node A's `store` and Node B's `store` are two separate dicts, how does a PUT to A ever end up on B?
4. Is replication the same as persistence?
5. If I added disk persistence to Part 1, would that make it a distributed system?
6. In Part 2, what happens if all three containers restart simultaneously?