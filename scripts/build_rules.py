#!/usr/bin/env python3
"""Aggregate blackmatrix7/ios_rule_script China rulesets into one deduped Shadowrocket RULE-SET."""
import datetime
import ipaddress
import urllib.request

BASE = "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket"

# ChinaIPsBGP / ChinaDNS are intentionally excluded: they were verified to be
# near-total subsets of ChinaMax's IP-CIDR / domain coverage (see diff report).
# ChinaIPs is included despite ~99.93% overlap with ChinaMax, since collapse_cidrs()
# below merges it for free and it still contributes a small amount of unique address space.
SOURCES = [
    f"{BASE}/China/China.list",
    f"{BASE}/China/China_Domain.list",
    f"{BASE}/ChinaMax/ChinaMax.list",
    f"{BASE}/ChinaMax/ChinaMax_Domain.list",
    f"{BASE}/ChinaIPs/ChinaIPs.list",
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


def collapse_cidrs(cidrs: set) -> list:
    v4 = [ipaddress.ip_network(c) for c in cidrs if ipaddress.ip_network(c).version == 4]
    v6 = [ipaddress.ip_network(c) for c in cidrs if ipaddress.ip_network(c).version == 6]
    collapsed = []
    if v4:
        collapsed += list(ipaddress.collapse_addresses(v4))
    if v6:
        collapsed += list(ipaddress.collapse_addresses(v6))
    return collapsed


def parse_source(text: str, is_domain_set: bool):
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


def build() -> str:
    parsed = []
    for url in SOURCES:
        text = fetch(url)
        parsed.append(parse_source(text, is_domain_set=url.endswith("_Domain.list")))
    merged = merge(parsed)

    domain_suffix = reduce_domain_suffixes(merged["domain_suffix"])
    suffix_trie: dict = {}
    for d in domain_suffix:
        insert_suffix(suffix_trie, d)
    domain = {d for d in merged["domain"] if not suffix_covers(suffix_trie, d)}
    ip_cidr = collapse_cidrs(merged["ip_cidr"])

    lines = []
    lines.append("# NAME: ChinaDirectMerged")
    lines.append("# GENERATED-BY: china-direct-rules/scripts/build_rules.py")
    lines.append(f"# UPDATED: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    lines.append("# SOURCES:")
    for url in SOURCES:
        lines.append(f"#   {url}")
    lines.append(f"# DOMAIN-SUFFIX: {len(domain_suffix)}")
    lines.append(f"# DOMAIN: {len(domain)}")
    lines.append(f"# DOMAIN-KEYWORD: {len(merged['domain_keyword'])}")
    lines.append(f"# USER-AGENT: {len(merged['user_agent'])}")
    lines.append(f"# IP-ASN: {len(merged['ip_asn'])}")
    lines.append(f"# IP-CIDR: {len(ip_cidr)}")
    total = len(domain_suffix) + len(domain) + len(merged["domain_keyword"]) + len(merged["user_agent"]) + len(merged["ip_asn"]) + len(ip_cidr)
    lines.append(f"# TOTAL: {total}")
    lines.append("")

    for d in sorted(merged["domain_keyword"]):
        lines.append(f"DOMAIN-KEYWORD,{d}")
    for d in sorted(merged["user_agent"]):
        lines.append(f"USER-AGENT,{d}")
    for d in sorted(merged["ip_asn"]):
        lines.append(f"IP-ASN,{d},no-resolve")
    for net in sorted(ip_cidr, key=lambda n: (n.version, n)):
        lines.append(f"IP-CIDR,{net},no-resolve")
    for d in sorted(domain):
        lines.append(f"DOMAIN,{d}")
    for d in sorted(domain_suffix, key=lambda s: s[::-1]):
        lines.append(f"DOMAIN-SUFFIX,{d}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    output = build()
    with open("rules/china_direct.list", "w", encoding="utf-8") as f:
        f.write(output)
    print(f"wrote rules/china_direct.list ({len(output.splitlines())} lines)")
