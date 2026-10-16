#!/usr/bin/env python3
"""Build a Mininet network from a YAML or JSON description, then open the Mininet CLI.

Run it inside the lab container, from the folder holding your files:
    python3 build_topo.py topology.yaml
    python3 build_topo.py topology.json
"""
import ipaddress
import json
import sys

import yaml
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.nodelib import LinuxBridge


def load(path):
    """Read the network description. Same data model, two possible serialisations."""
    with open(path) as f:
        if path.endswith(".json"):
            return json.load(f)
        return yaml.safe_load(f)


def check_mine(spec):
    """Return problems with the student's own addresses (supplied — you don't need to change it).

    Every lab this semester uses addresses from your own blocks:
    IPv4 10.NN.0.0/16 and IPv6 fd00:NNNN::/32, from the last digits of your student ID.
    """
    last4 = str(spec.get("student_id_last4", ""))
    if len(last4) != 4 or not last4.isdigit():
        return ['student_id_last4 must be the last 4 digits of your student ID, in quotes, e.g. "4207"']
    v4_block = ipaddress.ip_network(f"10.{int(last4[2:])}.0.0/16")
    v6_block = ipaddress.ip_network(f"fd00:{last4}::/32")

    problems = []
    for host in spec["hosts"]:
        for key, block in (("ip", v4_block), ("ipv6", v6_block)):
            if key not in host:
                continue
            try:
                address = ipaddress.ip_interface(host[key]).ip
            except ValueError:
                problems.append(f"{host['name']}: {host[key]} isn't a valid address (still NN or NNNN?)")
                continue
            if address not in block:
                problems.append(f"{host['name']}: {address} isn't in your block {block}")
    return problems


def check(spec):
    """Return a list of problems in the description (an empty list means it looks fine).

    Week 2 task: 
    1. Report any IP address that is used by more than one host (IPv4 and IPv6).
    2. Report any link that references a switch or host that does not exist.
    """
    problems = []
    
    # --- 1. CHECK FOR DUPLICATE IP ADDRESSES ---
    ip_to_hosts = {}
    for host in spec.get("hosts", []):
        host_name = host.get("name", "unknown")
        for key in ("ip", "ipv6"):
            if key in host:
                raw_addr = host[key]
                try:
                    # Normalize the IP address (strips subnet mask like /16 or /64 for accurate comparison)
                    ip_obj = str(ipaddress.ip_interface(raw_addr).ip)
                except ValueError:
                    # Invalid addresses are already caught by check_mine, skip them here
                    continue

                if ip_obj not in ip_to_hosts:
                    ip_to_hosts[ip_obj] = []
                ip_to_hosts[ip_obj].append(host_name)

    # Report duplicate IP addresses
    for ip, hosts in ip_to_hosts.items():
        if len(hosts) > 1:
            problems.append(f"IP address {ip} is used by more than one host: {', '.join(hosts)}")

    # --- 2. CHECK FOR INVALID LINKS (Non-existent nodes & Host-to-Host links) ---
    # Gather switch names into a set and host names into a separate set
    switches = set(spec.get("switches", []))
    hosts = set()
    for host in spec.get("hosts", []):
        if "name" in host:
            hosts.add(host["name"])
            
    valid_nodes = switches.union(hosts)

    # Check every link pair [a, b]
    for link in spec.get("links", []):
        if not isinstance(link, list) or len(link) != 2:
            problems.append(f"Invalid link format: {link} (must be a pair like [node1, node2])")
            continue
        
        node_a, node_b = link
        
        # Check if nodes exist at all
        if node_a not in valid_nodes:
            problems.append(f"Link references non-existent node: '{node_a}'")
        if node_b not in valid_nodes:
            problems.append(f"Link references non-existent node: '{node_b}'")
            
        # Check if both nodes are hosts (Host-to-Host connection rule)
        if node_a in hosts and node_b in hosts:
            problems.append(f"Invalid link between two hosts: '{node_a}' and '{node_b}' (hosts cannot connect directly to hosts)")
            
    return problems


def build(spec):
    """Turn the description into a Mininet network: switches, then hosts, then links."""
    net = Mininet(switch=LinuxBridge, controller=None, autoSetMacs=True)
    for name in spec["switches"]:
        net.addSwitch(name)
    for host in spec["hosts"]:
        net.addHost(host["name"], ip=host["ip"])
    for a, b in spec["links"]:
        net.addLink(a, b)
    return net


def add_ipv6(net, spec):
    """Mininet only sets IPv4 addresses, so add each host's IPv6 address once the network is up."""
    for host in spec["hosts"]:
        if "ipv6" in host:
            node = net.get(host["name"])
            node.cmd(f"ip -6 addr add {host['ipv6']} dev {node.defaultIntf()}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 build_topo.py <topology.yaml|topology.json>")
    spec = load(sys.argv[1])

    problems = check_mine(spec) + check(spec)
    if problems:
        for p in problems:
            print("PROBLEM:", p)
        sys.exit("Fix the description and try again.")

    setLogLevel("info")
    net = build(spec)
    net.start()
    add_ipv6(net, spec)
    CLI(net)
    net.stop()
