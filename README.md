# china-direct-rules

Daily-refreshed, deduplicated merge of [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)'s `China`, `ChinaMax`, and `ChinaIPs` rulesets, published as a ready-to-subscribe direct-connect ruleset for **Shadowrocket, Surge, Loon, QuantumultX, and Clash**.

## Why these three sources

Diffing all five China-related rulesets (`China`, `ChinaDNS`, `ChinaIPs`, `ChinaIPsBGP`, `ChinaMax`) showed:

- `ChinaIPsBGP` is a >99.9% address-space subset of `ChinaMax`'s IP-CIDR set — skipped, zero unique value.
- `ChinaIPs` is ~99.93% overlapping with `ChinaMax`, but the remaining ~0.07% (≈247k addresses) is real unique address space, and `collapse_cidrs()` merges it for free — so it's included.
- `ChinaDNS`'s 4 rules are already covered by `ChinaMax` (verbatim or via a broader suffix it already has) — skipped.
- `China` (the small curated list) contributes real, unique value `ChinaMax` doesn't have: 5 Tencent Cloud HK/SG IP ranges used by WeChat/QQ backends, a `microsoft` DOMAIN-KEYWORD, and ~162 domains (`bootcdn.net`, `baidustatic.com`, `51.la`, etc.) missing from `ChinaMax`'s domain set.

So `China.list` + `China_Domain.list` + `ChinaMax.list` + `ChinaMax_Domain.list` + `ChinaIPs.list` are merged. Only `ChinaIPsBGP` and `ChinaDNS` are skipped as fully redundant.

## Deduplication

`scripts/build_rules.py` doesn't just drop exact duplicate lines:

- **DOMAIN-SUFFIX**: built into a trie; any suffix already covered by a shorter suffix in the set (e.g. `doh.360.cn` under `cn`) is pruned.
- **IP-CIDR**: merged per IP version with `ipaddress.collapse_addresses`, which also removes CIDRs that are subsets of a larger already-included block.
- **DOMAIN / DOMAIN-KEYWORD / USER-AGENT / IP-ASN**: exact-value dedup; `DOMAIN` entries already covered by a kept `DOMAIN-SUFFIX` are dropped too.
- **IPv4-mapped IPv6 normalization**: upstream `ChinaMax.list` has 29 addresses written as `::ffff:a.b.c.d/128` instead of plain IPv4. As IPv6 literals these never match real IPv4 connections in any client's rule engine, so they're converted back to IPv4 `/32` before collapsing — otherwise they'd be 29 silently dead rules in every output.

## One canonical ruleset, five renderers

All five client files are generated from a single canonical rule set (parsed from the Shadowrocket-format sources above), not fetched separately per client. blackmatrix7's per-client directories are ~99% the same underlying data with different serialization; a few platform-exclusive extras exist (QuantumultX's one `HOST-WILDCARD` rule, Surge/Clash's desktop-only `PROCESS-NAME` rules) which aren't reproduced here. Trade-off: one build pipeline and guaranteed-identical domain/IP coverage across every client, at the cost of a handful of rarely-relevant platform-specific micro-rules.

| File | Client | Notes |
|---|---|---|
| `rules/shadowrocket.list` | Shadowrocket | `RULE-SET`; IPv4 and IPv6 CIDRs share one `IP-CIDR` type |
| `rules/surge.list` | Surge | `RULE-SET`; IPv6 CIDRs use a separate `IP-CIDR6` type |
| `rules/loon.list` | Loon | Same syntax as Surge |
| `rules/quantumultx.list` | QuantumultX | Uses `HOST`/`HOST-SUFFIX`/`HOST-KEYWORD`/`IP6-CIDR`; every line has an explicit trailing `direct` policy so it works standalone without needing a `force-policy=` override |
| `rules/clash.yaml` | Clash | `behavior: classical` rule-provider; **`USER-AGENT` rules are dropped** — Clash's classical behavior has no such rule type |

## Subscribing

**Shadowrocket** — rule config line:
```
RULE-SET,https://raw.githubusercontent.com/Mr-Grin/china-direct-rules/main/rules/shadowrocket.list,DIRECT
```

**Surge** — in `[Rule]`:
```
RULE-SET,https://raw.githubusercontent.com/Mr-Grin/china-direct-rules/main/rules/surge.list,DIRECT
```

**Loon** — in `[Rule]`:
```
RULE-SET,https://raw.githubusercontent.com/Mr-Grin/china-direct-rules/main/rules/loon.list,DIRECT
```

**QuantumultX** — in `[filter_remote]` (policy is already baked into the file, so no `force-policy=` needed):
```
https://raw.githubusercontent.com/Mr-Grin/china-direct-rules/main/rules/quantumultx.list, tag=china-direct, enabled=true
```

**Clash** — as a rule-provider in config:
```yaml
rule-providers:
  china-direct:
    type: http
    behavior: classical
    url: "https://raw.githubusercontent.com/Mr-Grin/china-direct-rules/main/rules/clash.yaml"
    path: ./ruleset/china-direct.yaml
    interval: 86400
rules:
  - RULE-SET,china-direct,DIRECT
```

Set each subscription's auto-update interval (e.g. 24h) so your client re-pulls after each daily GitHub Actions run.

## Automation

`.github/workflows/update.yml` runs daily at 21:30 UTC (05:30 Beijing) — a few hours after upstream's own daily refresh — regenerates all five files, and commits/pushes only if any file's actual rule content changed (the `# UPDATED:` timestamp line is ignored for this comparison, so no-op days produce no commit). Trigger manually anytime via the Actions tab (`workflow_dispatch`).
