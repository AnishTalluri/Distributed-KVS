# Distributed KVS: Defense Doc

Repo: github.com/AnishTalluri/Distributed-KVS
Status: Part 1 complete (single node). Parts 2 to 4 next, then Part 5 (vector store + RAG).

## How to use this

- Before an interview: say the pitch out loud, then go section by section. Cover the answer, say yours, then check.
- Each section has the same shape: interview line, key points, Q&A.
- If you can't answer a question cold, that section isn't done. Reread it, then retry tomorrow.
- New sections get added in project order as we build.

## The pitch (memorize)

> I'm building a distributed key-value store from scratch, in stages. Right now it's the single-node stage: a FastAPI service in Docker with four HTTP endpoints, backed by an in-memory dictionary. Next I add replication so writes reach every node, then causal consistency so nodes agree on the order of events, then sharding so each node holds a slice of the keys. After that, I'm extending it into a vector store with a small RAG app on top.

Don't say:
- "It's distributed" (it isn't yet; it's building toward that)
- "Byzantine" (that means nodes that lie, not nodes that crash)
- "It updates itself" (the server responds to client requests)

---

## 1. Project overview

**Interview line:** A distributed system is several machines working together as one service. Part 1 is the single-machine baseline so the API is locked in before distribution starts.

**Key points**
- Distributed = multiple machines, coordinating over a network, serving one logical service.
- Why distribute: one machine is a single point of failure and has a fixed capacity.
- Every hard problem in Parts 2 to 4 exists because we chose to distribute.
- Fault tolerance is a goal of distributed systems, not the definition.

**Q&A**
- **Q: Is this a distributed system right now?**
  A: No. Part 1 is one node. It becomes distributed in Part 2.
- **Q: Why build in stages?**
  A: The API stays the same while the inside changes, so each stage can be tested against the same contract.
- **Q: What does distribution buy you?**
  A: Surviving a node failure, and more capacity than one machine.

---

## 2. Storage: in-memory dict

**Interview line:** The whole database is one Python dict in RAM. It's the simplest thing that lets me get the API right first.

**Key points**
- `store = {}` lives in the memory of one Python process.
- Process stops (container restart) = dict gone. No persistence.
- Dict operations are O(1) on average (it's a hash table).
- Alternatives: SQLite, writing to a file, Redis. All add persistence, none needed for Part 1. Redis would defeat the point of building a KVS.

**Q&A**
- **Q: What does "in-memory" mean?**
  A: The data lives in RAM inside the running process, never written to disk.
- **Q: What happens when the container restarts?**
  A: The process restarts with fresh memory, so the dict is empty.
- **Q: Why not use a database?**
  A: Part 1 is about the API contract. A database adds setup and nothing the spec needs yet.
- **Q: Time complexity of reads and writes?**
  A: O(1) average, because a dict is a hash table.

---

## 3. Status codes and error handling

**Interview line:** 2xx means success, 4xx means the client's fault, 5xx means the server broke. A client should never be able to cause a 500.

**Key points**
- 200 OK (read, update, delete), 201 created (new key), 400 bad request, 404 key not found.
- 400 = "your request is broken." 404 = "your request is fine, the key doesn't exist."
- Three different 400s in PUT: couldn't parse the JSON, JSON isn't an object, no `value` field.
- Errors use `raise HTTPException`. Success uses `return`. Exceptions are for abnormal flow, returns for normal flow.
- Bare `return` gives 200 by default. `JSONResponse(status_code=201)` is used when the code isn't 200.

**Q&A**
- **Q: 400 vs 404?**
  A: 400 means the request itself is malformed. 404 means the request is fine but the key doesn't exist.
- **Q: 4xx vs 5xx?**
  A: 4xx is the client's fault, so retrying the same request won't help. 5xx is the server's fault.
- **Q: Why `raise HTTPException` for errors instead of returning a response?**
  A: It stops the handler right there, FastAPI formats every error the same way, and it works from inside helper functions.
- **Q: What happens if a client PUTs a body of `5`?**
  A: 400 with "Request body must be a JSON object." It used to crash with a 500 until I added an `isinstance(body, dict)` check.
- **Q: Would you ever avoid 404 for a missing key?**
  A: If key names are sensitive, like user IDs, 404 vs 200 leaks which ones exist. Not a concern for this project.

---

## 4. How requests run: async and threads

**Interview line:** `async def` handlers run on one main thread and only pause at `await`. Plain `def` handlers run on a thread pool. That difference decides where races can happen.

**Key points**
- Two layers make concurrency possible: the OS accepts the connections, and uvicorn's event loop dispatches them.
- `await` marks a spot where the handler waits on I/O (network, disk). The event loop runs other work meanwhile.
- PUT is `async def` because reading the body is network I/O.
- GET and DELETE are plain `def`, so FastAPI runs them on helper threads.
- Async enables concurrency. It does not make requests wait in line.
- Why FastAPI over Flask: FastAPI is async-first. In Part 2, a write must reach every node, and async lets those calls run at the same time (`asyncio.gather`) instead of one after another.

**Q&A**
- **Q: Does `async` prevent or enable concurrency?**
  A: Enables it. It lets one thread juggle many requests while each waits on I/O.
- **Q: Where does PUT pause?**
  A: At `await request.json()`, because the body is still arriving over the network.
- **Q: Two PUTs to the same key at once. What happens?**
  A: Both succeed, last writer wins. One gets 201, the other 200. No crash, because there's no `await` between the check and the write.
- **Q: Is that PUT behavior safe by design?**
  A: No, by accident of layout. Adding an `await` between the check and the write would create a race.
- **Q: Why FastAPI instead of Flask?**
  A: Part 2 fans writes out to every node. Async runs those calls in parallel, so latency is the slowest call, not the sum of all of them.

---

## 5. Race conditions: the DELETE fix

**Interview line:** The old DELETE checked, then deleted, with a gap in between. I closed the gap with a one-step `pop`.

**Key points**
- Check then act with a gap = race condition.
- Old code: `if key not in store` then `del store[key]`. Two threads could both pass the check, and the second `del` crashed with a 500.
- Fix: `store.pop(key, _MISSING)`. Check and delete happen in one step.
- `_MISSING = object()` is a unique marker no client can send. It separates "key missing" from "value is null."
- Compare with `is _MISSING`. Never `if not removed`, because null, 0, and "" are real stored values.
- Three fix options: all handlers async (one thread), a one-step operation (removes the gap), a lock (guards the gap). I chose the one-step operation.

**Q&A**
- **Q: Why is the new DELETE safe when the old one wasn't?**
  A: The check and the delete are one step, so there's no gap for another thread to slip into.
- **Q: Why not `if not removed`?**
  A: A key storing null or 0 would look missing and wrongly return 404.
- **Q: When would you use a lock instead?**
  A: When the critical section has multiple steps and no single operation covers it. That comes back in Part 2.
- **Q: Does a lock help across nodes?**
  A: No. A lock only works inside one process. Ordering across nodes needs causal metadata (Part 3).

---

## 6. Docker

**Interview line:** The container packages Python, the libraries, and the code, so it runs the same anywhere. It's also how I'll run several nodes on one laptop in Part 2.

**Key points**
- Isolation: the container fixes the Python version and all dependencies. A venv only handles pip packages.
- Reproducibility: same image, same behavior on any machine.
- Each container has its own network, which is how Part 2 simulates separate nodes.
- `--host 0.0.0.0` = listen on all network interfaces. With `127.0.0.1`, traffic from outside the container can't reach uvicorn.
- Copy `requirements.txt` and install before copying the source code. Docker caches each step, so code edits don't rerun the slow install.

**Q&A**
- **Q: Why containerize at all?**
  A: Reproducible runtime, and it gives each Part 2 node its own isolated machine.
- **Q: What breaks without `--host 0.0.0.0`?**
  A: The container starts fine, but every request from the host gets "connection refused."
- **Q: Why copy requirements before the source code?**
  A: Docker reruns every step after the first changed one. Dependencies rarely change, so the install stays cached.
- **Q: Is a container a VM?**
  A: No. It shares the host's kernel. A VM runs a whole separate OS.

---

## 7. Can it run in a browser?

**Interview line:** No. A browser can only be a client. It can't open a port, doesn't run Python, and its code stops when the tab closes.

**Key points**
- The KVS needs a Python runtime, a listening port, and a process that runs indefinitely.
- Browsers are sandboxed: no binding ports, no long-lived server process.
- localhost is a network address, not a browser environment.
- A browser can call the KVS over HTTP, which already works today.

**Q&A**
- **Q: Could this run in a browser?**
  A: No. Browsers can't listen on a port or run Python natively. They can only send requests to a server.
- **Q: Isn't localhost a browser environment?**
  A: No. localhost just means "this same machine." The server still runs as a normal process.
- **Q: How would a browser use this KVS?**
  A: As a client, making HTTP requests to it.

---

## 8. Handoff to Part 2

**Interview line:** Each node has its own dict in its own memory. A write to one node doesn't appear on the others, and replication is the code that fixes that.

**Key points**
- Part 2 runs several nodes, each with a separate `store`.
- A PUT to Node A changes only Node A's dict. A GET to Node B would return 404.
- Replication = sending each write to every node.
- Replication is not persistence. Persistence survives a restart (disk). Replication survives a node dying (other copies).
- Part 2 keeps everything in RAM. If every node restarts at once, all data is lost.

**Q&A**
- **Q: How does a PUT to Node A reach Node B?**
  A: Node A forwards the write to the other nodes. That's replication.
- **Q: Replication vs persistence?**
  A: Persistence survives a process restart. Replication survives a node failure. Different problems.
- **Q: Would adding disk storage make Part 1 distributed?**
  A: No. Still one node.
- **Q: In Part 2, what happens if every node restarts at once?**
  A: All data is lost, because nothing is on disk.