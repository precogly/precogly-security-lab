# One group per box. A security group is not a firewall on a host; it is a
# label, and rules are attached to the label. Neither group below carries a
# rule inline — every rule is its own aws_vpc_security_group_egress_rule in
# security_group_rules.tf.
#
# Declaring a group with no inline blocks leaves it with no egress at all. AWS
# attaches an allow-all egress rule at creation and the provider removes it as
# soon as egress is managed. That is the point: everything a box may reach is
# written down.
#
# Neither group has an ingress rule, and none is planned:
#
#   people, scanner box ──► tailnet ──► precogly instance :443
#                                        (Tailscale, inside the box)
#   the internet ─────────────────────► (nothing: no inbound rule)
#
# Access between people, the scanner box and the instance is the tailnet
# policy's job (docs/tailnet-setup.md). Tailscale traffic
# arrives as replies to connections each box opened outbound, which the group's
# connection tracking lets back in without an ingress rule. A group cannot
# express "this person" anyway, only addresses and other groups.
#
# A group's `description` is immutable. Changing one forces the group to be
# replaced, which cannot happen while an instance holds a network interface in
# it, so these describe the group's role rather than its current rules.

resource "aws_security_group" "precogly" {
  name        = "${var.project}-precogly"
  description = "Precogly instance: reached only over the tailnet"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-precogly" }
}

# The scanner box runs scanners and AI agents, which is untrusted code. Its
# tailnet reach is bounded by the policy (tag:scanner -> tag:precogly :443
# only). Its internet reach is the egress below, and is wide, because an agent
# has to reach its model's API. So an agent that escapes its job here can reach
# any internet host; containing that is not done yet.
resource "aws_security_group" "scanner" {
  name        = "${var.project}-scanner"
  description = "Scanner box: scanners and AI agents, untrusted code"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-scanner" }
}
