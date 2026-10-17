# Every rule, one resource each, grouped by the group it attaches to. All of
# them are egress; the reason there is no ingress is in security_group.tf.
#
# The two boxes get the same four rules, written out twice rather than looped,
# so each group's whole reach can be read in one place.
#
# Deliberately absent:
#
# - A rule for DNS. "You cannot filter traffic to or from the Amazon DNS server
#   using network ACLs or security groups" — VPC User Guide, *Understanding
#   Amazon DNS*, under Rules and considerations. A :53 rule would do nothing.
#   The same holds for the instance metadata service and Amazon Time Sync, both
#   link-local.
# - Any `from_port`/`to_port` pair wider than a single port. A range here would
#   mean the port was not looked up.
#
# Tailscale works over 443 alone, through its relays (DERP). The two UDP rules
# let it find a direct path instead: 3478 is STUN, which tells a node its public
# address, and 41641 is the port tailscaled listens on. An egress rule matches
# the destination port, so this one admits direct traffic to peers that listen
# on 41641 unchanged, which is the other box. A laptop behind home NAT appears
# on a random port, so people's paths may stay relayed; for a browser that
# costs latency, not reachability.
#
# The box-to-box path is the one that matters: relayed, scan traffic between
# two boxes in one VPC would leave it, cross a relay, and come back. It needs no
# ingress rule. Each side sends to the other at once, and each group admits the
# other's packets as replies. Whether that works in practice is checked after
# apply with `tailscale status` (a direct path shows an address, a relayed one
# shows "relay").

# The Precogly instance.
#
# 443: Tailscale's coordination servers and relays, the Tailscale package
# repository, Docker Hub and the npm/PyPI registries during `compose build`,
# GitHub for the clone, Secrets Manager and SSM.
resource "aws_vpc_security_group_egress_rule" "precogly_https" {
  security_group_id = aws_security_group.precogly.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "Tailscale, packages, images, GitHub, Secrets Manager, SSM"
}

# 80: Ubuntu's EC2 package mirrors are plain HTTP; apt checks signatures, not
# the transport.
resource "aws_vpc_security_group_egress_rule" "precogly_http" {
  security_group_id = aws_security_group.precogly.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "Ubuntu apt mirrors"
}

resource "aws_vpc_security_group_egress_rule" "precogly_stun" {
  security_group_id = aws_security_group.precogly.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "udp"
  from_port         = 3478
  to_port           = 3478
  description       = "Tailscale STUN, for direct paths"
}

resource "aws_vpc_security_group_egress_rule" "precogly_wireguard" {
  security_group_id = aws_security_group.precogly.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "udp"
  from_port         = 41641
  to_port           = 41641
  description       = "Tailscale direct WireGuard"
}

# The scanner box. The same four, for the same reasons. 443 also carries what
# makes this group wide: an agent's model API, and anything else on the
# internet an agent decides to fetch.
resource "aws_vpc_security_group_egress_rule" "scanner_https" {
  security_group_id = aws_security_group.scanner.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "Tailscale, packages, tools, model APIs, Secrets Manager, SSM"
}

resource "aws_vpc_security_group_egress_rule" "scanner_http" {
  security_group_id = aws_security_group.scanner.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "Ubuntu apt mirrors"
}

resource "aws_vpc_security_group_egress_rule" "scanner_stun" {
  security_group_id = aws_security_group.scanner.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "udp"
  from_port         = 3478
  to_port           = 3478
  description       = "Tailscale STUN, for direct paths"
}

resource "aws_vpc_security_group_egress_rule" "scanner_wireguard" {
  security_group_id = aws_security_group.scanner.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "udp"
  from_port         = 41641
  to_port           = 41641
  description       = "Tailscale direct WireGuard"
}
