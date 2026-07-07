#!/usr/bin/env python3
"""Aggregate blackmatrix7/ios_rule_script China rulesets into one deduped ruleset,
rendered into Shadowrocket, Surge, Loon, QuantumultX, and Clash formats."""
import datetime
import ipaddress
import urllib.request

BASE = "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket"
CHNROUTES_URL = "https://raw.githubusercontent.com/misakaio/chnroutes2/master/chnroutes.txt"
REPO_RAW_BASE = "https://raw.githubusercontent.com/Mr-Grin/china-direct-rules/main"

# ChinaDNS is intentionally excluded: its 4 rules were verified to already be
# covered by ChinaMax's domain set (see diff report).
# ChinaIPs is included despite ~99.93% overlap with ChinaMax, since
# collapse_cidrs() below merges it for free and it still contributes a small
# amount of unique address space.
#
# chnroutes.txt is fetched directly from misakaio/chnroutes2 (a bare CIDR
# list, refreshed daily) instead of blackmatrix7's ChinaIPsBGP.list mirror of
# it, since that mirror was found to lag the upstream by weeks. As of this
# writing it's a 100% subset of ChinaMax's IP-CIDR set (zero unique
# addresses), but it's kept since collapse_cidrs() dedupes it for free and it
# guards against future BGP churn ChinaMax hasn't picked up yet.
#
# All five client outputs are rendered from this single canonical ruleset
# rather than fetched separately per client. blackmatrix7's per-client files
# are ~99% identical data with different serialization; the small
# platform-exclusive extras (e.g. QuantumultX's one HOST-WILDCARD rule,
# Surge/Clash's desktop-only PROCESS-NAME rules) are skipped in exchange for
# one build pipeline and guaranteed-identical coverage across every client.
SOURCES = [
    f"{BASE}/China/China.list",
    f"{BASE}/China/China_Domain.list",
    f"{BASE}/ChinaMax/ChinaMax.list",
    f"{BASE}/ChinaMax/ChinaMax_Domain.list",
    f"{BASE}/ChinaIPs/ChinaIPs.list",
    CHNROUTES_URL,
]

MARK = object()


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def insert_suffix(trie: dict, domain: str) -> None:
    node = trie
    for label in reversed(domain.strip(".").split(".")):
        node = node.setdefault(label, {})
    node[MARK] = True


def collect_suffixes(trie: dict, prefix: list, out: list) -> None:
    if trie.get(MARK):
        out.append(".".join(reversed(prefix)))
        return  # any descendant is already matched by this shorter suffix
    for label, child in trie.items():
        if label is MARK:
            continue
        collect_suffixes(child, prefix + [label], out)


def reduce_domain_suffixes(domains: set) -> set:
    trie: dict = {}
    for d in domains:
        insert_suffix(trie, d)
    out: list = []
    collect_suffixes(trie, [], out)
    return set(out)


def suffix_covers(trie: dict, domain: str) -> bool:
    node = trie
    for label in reversed(domain.strip(".").split(".")):
        if node.get(MARK):
            return True
        node = node.get(label)
        if node is None:
            return False
    return bool(node.get(MARK))


def classify_user_agent(value: str) -> tuple:
    """Turn a USER-AGENT wildcard pattern into a (kind, literal) pair.

    Surge/Shadowrocket/Loon/QuantumultX match USER-AGENT as a fnmatch-style
    glob anchored at both ends, so a value with no '*' only matches that exact
    header. '?' isn't used by any current source and isn't a plain substring
    op, so patterns using it are left as "complex" (never deduped) rather
    than mismodeled.
    """
    if "?" in value:
        return ("complex", value)
    stars = value.count("*")
    if stars == 0:
        return ("exact", value)
    if stars == 1:
        if value.startswith("*"):
            return ("suffix", value[1:])
        if value.endswith("*"):
            return ("prefix", value[:-1])
        return ("complex", value)
    if stars == 2 and value.startswith("*") and value.endswith("*") and "*" not in value[1:-1]:
        return ("contains", value[1:-1])
    return ("complex", value)


def pattern_subsumes(a: tuple, b: tuple) -> bool:
    """True if every string matched by pattern b is also matched by pattern a,
    i.e. keeping a makes b redundant. Patterns are (kind, literal) pairs from
    classify_user_agent, or ("contains", value) for plain DOMAIN-KEYWORD
    substrings. "complex" never subsumes and is never subsumed."""
    ak, ac = a
    bk, bc = b
    if ak == "complex" or bk == "complex":
        return False
    if ak == "contains":
        return ac in bc
    if ak == "prefix":
        return bk in ("prefix", "exact") and bc.startswith(ac)
    if ak == "suffix":
        return bk in ("suffix", "exact") and bc.endswith(ac)
    return False  # "exact" only ever matches itself, so it can't subsume a distinct pattern


def reduce_redundant_patterns(values: set, classify) -> set:
    """Drop patterns whose matches are a subset of some other pattern's in the
    same set (e.g. DOMAIN-KEYWORD "qiyi" makes "iqiyi" redundant; USER-AGENT
    "QQ*" makes "QQMusic*" redundant)."""
    parsed = {v: classify(v) for v in values}
    redundant = set()
    for b in values:
        for a in values:
            if a != b and pattern_subsumes(parsed[a], parsed[b]):
                redundant.add(b)
                break
    return values - redundant


def normalize_v4_mapped(net: ipaddress._BaseNetwork) -> ipaddress._BaseNetwork:
    """Some upstream entries encode plain IPv4 hosts as IPv4-mapped IPv6 /128
    literals (e.g. ::ffff:1.2.3.4/128). Rule engines match connections by
    address family, so as IPv6 these never match real IPv4 traffic - convert
    back to IPv4 so the rule actually works."""
    if net.version == 6 and net.prefixlen == 128 and net.network_address.ipv4_mapped is not None:
        return ipaddress.ip_network(f"{net.network_address.ipv4_mapped}/32")
    return net


def collapse_cidrs(cidrs: set) -> list:
    nets = [normalize_v4_mapped(ipaddress.ip_network(c)) for c in cidrs]
    v4 = [n for n in nets if n.version == 4]
    v6 = [n for n in nets if n.version == 6]
    collapsed = []
    if v4:
        collapsed += list(ipaddress.collapse_addresses(v4))
    if v6:
        collapsed += list(ipaddress.collapse_addresses(v6))
    return collapsed


def parse_source(text: str, is_domain_set: bool, is_cidr_set: bool = False):
    rules = {
        "domain_suffix": set(),
        "domain": set(),
        "domain_keyword": set(),
        "user_agent": set(),
        "ip_asn": set(),
        "ip_cidr": set(),
    }
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if is_domain_set:
            rules["domain_suffix"].add(line.lstrip("."))
            continue
        if is_cidr_set:
            rules["ip_cidr"].add(line)
            continue
        parts = line.split(",")
        rtype = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        if rtype == "DOMAIN-SUFFIX":
            rules["domain_suffix"].add(value.lstrip("."))
        elif rtype == "DOMAIN":
            rules["domain"].add(value)
        elif rtype == "DOMAIN-KEYWORD":
            rules["domain_keyword"].add(value)
        elif rtype == "USER-AGENT":
            rules["user_agent"].add(value)
        elif rtype == "IP-ASN":
            rules["ip_asn"].add(value)
        elif rtype == "IP-CIDR":
            rules["ip_cidr"].add(value)
    return rules


def merge(all_rules: list) -> dict:
    merged = {
        "domain_suffix": set(),
        "domain": set(),
        "domain_keyword": set(),
        "user_agent": set(),
        "ip_asn": set(),
        "ip_cidr": set(),
    }
    for r in all_rules:
        for k in merged:
            merged[k] |= r[k]
    return merged


def build_canonical() -> dict:
    parsed = []
    for url in SOURCES:
        text = fetch(url)
        parsed.append(parse_source(text, is_domain_set=url.endswith("_Domain.list"), is_cidr_set=url == CHNROUTES_URL))
    merged = merge(parsed)

    domain_suffix = reduce_domain_suffixes(merged["domain_suffix"])
    suffix_trie: dict = {}
    for d in domain_suffix:
        insert_suffix(suffix_trie, d)
    domain = {d for d in merged["domain"] if not suffix_covers(suffix_trie, d)}
    domain_keyword = reduce_redundant_patterns(merged["domain_keyword"], lambda v: ("contains", v))
    user_agent = reduce_redundant_patterns(merged["user_agent"], classify_user_agent)
    ip_cidr = collapse_cidrs(merged["ip_cidr"])
    ip_cidr_v4 = sorted((n for n in ip_cidr if n.version == 4))
    ip_cidr_v6 = sorted((n for n in ip_cidr if n.version == 6))

    return {
        "domain_suffix": sorted(domain_suffix, key=lambda s: s[::-1]),
        "domain": sorted(domain),
        "domain_keyword": sorted(domain_keyword),
        "user_agent": sorted(user_agent),
        "ip_asn": sorted(merged["ip_asn"]),
        "ip_cidr_v4": ip_cidr_v4,
        "ip_cidr_v6": ip_cidr_v6,
    }


def header(ctx: dict, comment: str = "#") -> list:
    total = sum(len(ctx[k]) for k in ("domain_suffix", "domain", "domain_keyword", "user_agent", "ip_asn", "ip_cidr_v4", "ip_cidr_v6"))
    lines = [
        f"{comment} NAME: ChinaDirectMerged",
        f"{comment} GENERATED-BY: china-direct-rules/scripts/build_rules.py",
        f"{comment} UPDATED: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        f"{comment} SOURCES:",
    ]
    for url in SOURCES:
        lines.append(f"{comment}   {url}")
    lines += [
        f"{comment} DOMAIN-SUFFIX: {len(ctx['domain_suffix'])}",
        f"{comment} DOMAIN: {len(ctx['domain'])}",
        f"{comment} DOMAIN-KEYWORD: {len(ctx['domain_keyword'])}",
        f"{comment} USER-AGENT: {len(ctx['user_agent'])}",
        f"{comment} IP-ASN: {len(ctx['ip_asn'])}",
        f"{comment} IP-CIDR: {len(ctx['ip_cidr_v4'])}",
        f"{comment} IP-CIDR6: {len(ctx['ip_cidr_v6'])}",
        f"{comment} TOTAL: {total}",
    ]
    return lines


def render_shadowrocket(ctx: dict) -> str:
    """Shadowrocket RULE-SET: mixes rule types in one file, single IP-CIDR type for v4+v6."""
    lines = header(ctx) + [""]
    for d in ctx["domain_keyword"]:
        lines.append(f"DOMAIN-KEYWORD,{d}")
    for d in ctx["user_agent"]:
        lines.append(f"USER-AGENT,{d}")
    for d in ctx["ip_asn"]:
        lines.append(f"IP-ASN,{d},no-resolve")
    for net in ctx["ip_cidr_v4"] + ctx["ip_cidr_v6"]:
        lines.append(f"IP-CIDR,{net},no-resolve")
    for d in ctx["domain"]:
        lines.append(f"DOMAIN,{d}")
    for d in ctx["domain_suffix"]:
        lines.append(f"DOMAIN-SUFFIX,{d}")
    return "\n".join(lines) + "\n"


def render_surge_loon(ctx: dict) -> str:
    """Surge & Loon RULE-SET: same syntax, IPv6 CIDRs get their own IP-CIDR6 type."""
    lines = header(ctx) + [""]
    for d in ctx["domain_keyword"]:
        lines.append(f"DOMAIN-KEYWORD,{d}")
    for d in ctx["user_agent"]:
        lines.append(f"USER-AGENT,{d}")
    for d in ctx["ip_asn"]:
        lines.append(f"IP-ASN,{d},no-resolve")
    for net in ctx["ip_cidr_v4"]:
        lines.append(f"IP-CIDR,{net},no-resolve")
    for net in ctx["ip_cidr_v6"]:
        lines.append(f"IP-CIDR6,{net},no-resolve")
    for d in ctx["domain"]:
        lines.append(f"DOMAIN,{d}")
    for d in ctx["domain_suffix"]:
        lines.append(f"DOMAIN-SUFFIX,{d}")
    return "\n".join(lines) + "\n"


def render_quantumultx(ctx: dict) -> str:
    """QuantumultX filter: HOST(-SUFFIX/-KEYWORD) instead of DOMAIN(-SUFFIX/-KEYWORD),
    every line carries an explicit trailing policy so it works standalone without
    relying on a force-policy= override at subscription time."""
    lines = header(ctx) + [""]
    for d in ctx["domain_keyword"]:
        lines.append(f"HOST-KEYWORD,{d},direct")
    for d in ctx["user_agent"]:
        lines.append(f"USER-AGENT,{d},direct")
    for d in ctx["ip_asn"]:
        lines.append(f"IP-ASN,{d},direct")
    for net in ctx["ip_cidr_v4"]:
        lines.append(f"IP-CIDR,{net},direct")
    for net in ctx["ip_cidr_v6"]:
        lines.append(f"IP6-CIDR,{net},direct")
    for d in ctx["domain"]:
        lines.append(f"HOST,{d},direct")
    for d in ctx["domain_suffix"]:
        lines.append(f"HOST-SUFFIX,{d},direct")
    return "\n".join(lines) + "\n"


def render_clash(ctx: dict) -> str:
    """Clash classical rule-provider. No USER-AGENT support in classical mode,
    so those rules are dropped (documented in README)."""
    lines = header(ctx) + ["payload:"]
    for d in ctx["domain_keyword"]:
        lines.append(f"  - DOMAIN-KEYWORD,{d}")
    for d in ctx["ip_asn"]:
        lines.append(f"  - IP-ASN,{d}")
    for net in ctx["ip_cidr_v4"]:
        lines.append(f"  - IP-CIDR,{net}")
    for net in ctx["ip_cidr_v6"]:
        lines.append(f"  - IP-CIDR6,{net}")
    for d in ctx["domain"]:
        lines.append(f"  - DOMAIN,{d}")
    for d in ctx["domain_suffix"]:
        lines.append(f"  - DOMAIN-SUFFIX,{d}")
    return "\n".join(lines) + "\n"


def render_shadowrocket_module(ctx: dict) -> str:
    """Shadowrocket module wrapping the shadowrocket.list RULE-SET: lets users
    add it via Configuration > Module > + (paste URL) instead of hand-editing
    a profile's [Rule] section. Content is static (no embedded date/count) so
    it never produces timestamp-only diff noise across daily rebuilds."""
    lines = [
        "#!name = China Direct Rules",
        "#!desc = Daily-refreshed China direct-connect ruleset — github.com/Mr-Grin/china-direct-rules",
        "#!category = Rule",
        "",
        "[Rule]",
        f"RULE-SET,{REPO_RAW_BASE}/rules/shadowrocket.list,DIRECT",
    ]
    return "\n".join(lines) + "\n"


OUTPUTS = {
    "rules/shadowrocket.list": render_shadowrocket,
    "rules/shadowrocket.sgmodule": render_shadowrocket_module,
    "rules/surge.list": render_surge_loon,
    "rules/loon.list": render_surge_loon,
    "rules/quantumultx.list": render_quantumultx,
    "rules/clash.yaml": render_clash,
}

STATS_START = "<!-- RULE-STATS:START -->"
STATS_END = "<!-- RULE-STATS:END -->"


def render_readme_stats(ctx: dict) -> str:
    rows = [
        ("DOMAIN-SUFFIX", len(ctx["domain_suffix"])),
        ("DOMAIN", len(ctx["domain"])),
        ("DOMAIN-KEYWORD", len(ctx["domain_keyword"])),
        ("USER-AGENT", len(ctx["user_agent"])),
        ("IP-ASN", len(ctx["ip_asn"])),
        ("IP-CIDR (v4)", len(ctx["ip_cidr_v4"])),
        ("IP-CIDR6 (v6)", len(ctx["ip_cidr_v6"])),
    ]
    total = sum(n for _, n in rows)
    lines = [STATS_START, "", "| Type | Count |", "|---|---|"]
    for name, n in rows:
        lines.append(f"| {name} | {n:,} |")
    lines.append(f"| **TOTAL** | **{total:,}** |")
    lines.append("")
    lines.append(STATS_END)
    return "\n".join(lines)


def update_readme(ctx: dict, path: str = "README.md") -> None:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    start = text.index(STATS_START)
    end = text.index(STATS_END) + len(STATS_END)
    text = text[:start] + render_readme_stats(ctx) + text[end:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    ctx = build_canonical()
    for path, renderer in OUTPUTS.items():
        text = renderer(ctx)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {path} ({len(text.splitlines())} lines)")
    update_readme(ctx)
    print("updated README.md rule statistics")
