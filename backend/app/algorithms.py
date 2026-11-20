"""Independent implementations of the graph algorithms (no NetworkX). Graphs are
adjacency dicts {u: {v: weight}} (undirected: symmetric). Verified against NetworkX in tests."""
import heapq, math, sys
from collections import deque

INF = math.inf


def components(adj):
    seen, comps = set(), []
    for s in adj:
        if s in seen:
            continue
        seen.add(s); comp = [s]; dq = deque([s])
        while dq:
            u = dq.popleft()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v); comp.append(v); dq.append(v)
        comps.append(comp)
    return comps


def dijkstra(adj, sources, target=None, trace=False):
    """d(v) = min(d(v), d(u)+w(u,v)). Returns (dist, prev, steps). O((V+E) log V)."""
    for u in adj:
        for v, w in adj[u].items():
            if w < 0:
                raise ValueError(f"negative weight on edge {u}-{v}")
    dist = {n: INF for n in adj}; prev = {}; steps = []; pq = []; done = set()
    for s in sources:
        dist[s] = 0.0; heapq.heappush(pq, (0.0, s))
    while pq:
        d, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        if trace:
            top = sorted(x for x in pq if x[1] not in done and x[0] == dist[x[1]])[:6]
            steps.append({"t": "select", "u": u, "d": d, "pq": [[round(a, 4), b] for a, b in top]})
        if u == target:
            break
        for v, w in adj[u].items():
            if v in done:
                continue
            nd = d + w; upd = nd < dist[v]
            if trace:
                steps.append({"t": "relax", "u": u, "v": v, "w": w, "cand": nd,
                              "old": None if dist[v] == INF else dist[v], "upd": upd})
            if upd:
                dist[v] = nd; prev[v] = u; heapq.heappush(pq, (nd, v))
    return dist, prev, steps


def path_to(prev, target):
    p = [target]
    while p[-1] in prev:
        p.append(prev[p[-1]])
    return p[::-1]


def kruskal(nodes, edges, trace=False, budget=None):
    """edges: iterable of (u, v, w). Returns minimum spanning FOREST if disconnected."""
    parent = {n: n for n in nodes}; rank = {n: 0 for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    E = sorted(((w, u, v) for u, v, w in edges), key=lambda e: (e[0], e[1], e[2]))
    adj = {n: {} for n in nodes}
    for w, u, v in E:
        adj[u][v] = w; adj[v][u] = w
    target = len(nodes) - len(components(adj))
    mst, steps, examined, total, stopped = [], [], 0, 0.0, False
    for w, u, v in E:
        if len(mst) == target:
            break
        if budget is not None and total + w > budget + 1e-12:
            stopped = True; break
        examined += 1
        ru, rv = find(u), find(v)
        acc = ru != rv
        if trace:
            steps.append({"t": "edge", "u": u, "v": v, "w": w, "acc": acc, "ru": ru, "rv": rv})
        if acc:
            if rank[ru] < rank[rv]:
                ru, rv = rv, ru
            parent[rv] = ru
            if rank[ru] == rank[rv]:
                rank[ru] += 1
            mst.append((u, v, w)); total += w
    return {"edges": mst, "weight": total, "examined": examined, "steps": steps,
            "components": len(nodes) - len(mst), "stopped": stopped}


def prim(adj, start=None, trace=False, budget=None):
    """Prim from `start`; restarts in each remaining component (spanning forest)."""
    order = ([start] if start in adj else []) + [n for n in adj if n != start]
    visited, mst, steps, examined, total, stopped = set(), [], [], 0, 0.0, False
    for s in order:
        if s in visited or stopped:
            continue
        visited.add(s)
        heap = [(w, s, v) for v, w in adj[s].items()]
        heapq.heapify(heap)
        if trace:
            steps.append({"t": "start", "s": s})
        while heap:
            w, u, v = heapq.heappop(heap); examined += 1
            if v in visited:
                if trace:
                    steps.append({"t": "skip", "u": u, "v": v, "w": w})
                continue
            if budget is not None and total + w > budget + 1e-12:
                stopped = True; break
            visited.add(v); mst.append((u, v, w)); total += w
            for x, wx in adj[v].items():
                if x not in visited:
                    heapq.heappush(heap, (wx, v, x))
            if trace:
                fr = [[round(a, 4), b, c] for a, b, c in sorted(heap) if c not in visited][:5]
                steps.append({"t": "pick", "u": u, "v": v, "w": w, "frontier": fr})
    return {"edges": mst, "weight": total, "examined": examined, "steps": steps,
            "components": len(adj) - len(mst), "stopped": stopped}


def degree_centrality(adj):
    n = len(adj)
    return {u: (len(adj[u]) / (n - 1) if n > 1 else 0.0) for u in adj}


def betweenness(adj):
    """Brandes' algorithm, unweighted, normalised like NetworkX (undirected)."""
    n = len(adj); C = dict.fromkeys(adj, 0.0)
    for s in adj:
        S, P = [], {v: [] for v in adj}
        sigma = dict.fromkeys(adj, 0); sigma[s] = 1
        D = {s: 0}; Q = deque([s])
        while Q:
            v = Q.popleft(); S.append(v)
            for w in adj[v]:
                if w not in D:
                    D[w] = D[v] + 1; Q.append(w)
                if D[w] == D[v] + 1:
                    sigma[w] += sigma[v]; P[w].append(v)
        delta = dict.fromkeys(adj, 0.0)
        while S:
            w = S.pop()
            for v in P[w]:
                delta[v] += sigma[v] / sigma[w] * (1 + delta[w])
            if w != s:
                C[w] += delta[w]
    scale = 1.0 / ((n - 1) * (n - 2)) if n > 2 else 0.0
    return {v: c * scale for v, c in C.items()}


def articulation_points(adj):
    sys.setrecursionlimit(10000)
    disc, low, ap, t = {}, {}, set(), [0]

    def dfs(u, p):
        disc[u] = low[u] = t[0]; t[0] += 1; children = 0
        for v in adj[u]:
            if v == p:
                continue
            if v in disc:
                low[u] = min(low[u], disc[v])
            else:
                children += 1; dfs(v, u); low[u] = min(low[u], low[v])
                if p is not None and low[v] >= disc[u]:
                    ap.add(u)
        if p is None and children > 1:
            ap.add(u)

    for n in adj:
        if n not in disc:
            dfs(n, None)
    return ap


def avg_shortest_path_hops(adj):
    tot, cnt = 0, 0
    for s in adj:
        D = {s: 0}; Q = deque([s])
        while Q:
            u = Q.popleft()
            for v in adj[u]:
                if v not in D:
                    D[v] = D[u] + 1; Q.append(v)
        tot += sum(D.values()); cnt += len(D) - 1
    return tot / cnt if cnt else None


def closeness(adj):
    """Weighted closeness, Wasserman-Faust (same convention as NetworkX wf_improved=True)."""
    n = len(adj); out = {}
    for s in adj:
        dist, _, _ = dijkstra(adj, [s])
        reach = [d for v, d in dist.items() if d < INF and v != s]
        tot = sum(reach)
        out[s] = (len(reach) / tot) * (len(reach) / (n - 1)) if tot > 0 and n > 1 else 0.0
    return out
