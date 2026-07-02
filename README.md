# china-direct-rules

Daily-refreshed, deduplicated merge of [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)'s `China` and `ChinaMax` Shadowrocket rulesets, for use as a single direct-connect subscription.

## Why these two sources

Diffing all five China-related rulesets (`China`, `ChinaDNS`, `ChinaIPs`, `ChinaIPsBGP`, `ChinaMax`) showed:

- `ChinaIPsBGP` is a >99.9% address-space subset of `ChinaMax`'s IP-CIDR set — skipped, zero unique value.
- `ChinaIPs` is ~99.93% overlapping with `ChinaMax`, but the remaining ~0.07% (≈247k addresses) is real unique address space, and `collapse_cidrs()` merges it for free — so it's included.
- `ChinaDNS`'s 4 rules are already covered by `ChinaMax` (verbatim or via a broader suffix it already has) — skipped.
- `China` (the small curated list) contributes real, unique value `ChinaMax` doesn't have: 5 Tencent Cloud HK/SG IP ranges used by WeChat/QQ backends, a `microsoft` DOMAIN-KEYWORD, and ~162 domains (`bootcdn.net`, `baidustatic.com`, `51.la`, etc.) missing from `ChinaMax`'s domain set.

So `China.list` + `China_Domain.list` + `ChinaMax.list` + `ChinaMax_Domain.list` + `ChinaIPs.list` are merged. Only `ChinaIPsBGP` and `ChinaDNS` are skipped as fully redundant.

## Deduplication

`scripts/build_rules.py` doesn't just drop exact duplicate lines:

- **DOMAIN-SUFFIX**: built into a trie; any suffix that is already covered by a shorter suffix in the set (e.g. `doh.360.cn` under `cn`) is pruned.
- **IP-CIDR**: merged per IP version with `ipaddress.collapse_addresses`, which also removes CIDRs that are subsets of a larger already-included block.
- **DOMAIN / DOMAIN-KEYWORD / USER-AGENT / IP-ASN**: exact-value dedup; `DOMAIN` entries already covered by a kept `DOMAIN-SUFFIX` are dropped too.

## Output

`output/china_direct.list` — a single Shadowrocket `RULE-SET` file mixing all rule types (same format `ChinaMax.list` itself uses).

## Subscribing in Shadowrocket

Add as a rule subscription:

```
https://raw.githubusercontent.com/<your-github-username>/china-direct-rules/main/output/china_direct.list
```

Rule config line:

```
RULE-SET,https://raw.githubusercontent.com/<your-github-username>/china-direct-rules/main/output/china_direct.list,DIRECT
```

Set the subscription's auto-update interval (e.g. 24h) so Shadowrocket re-pulls after each daily GitHub Actions run.

## Automation

`.github/workflows/update.yml` runs daily at 21:30 UTC (05:30 Beijing) — a few hours after upstream's own daily refresh — regenerates `output/china_direct.list`, and commits/pushes if anything changed. Trigger manually anytime via the Actions tab (`workflow_dispatch`).
