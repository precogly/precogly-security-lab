# The network both Phase A boxes sit in: the Precogly instance and the scanner
# box. Nothing here is specific to either — this file is only addressing and
# routing.
#
# One public subnet, one AZ:
#
#   10.0.0.0/16  VPC
#   └── 10.0.0.0/20    public   AZ a   route table -> internet gateway
#         ^
#         └── the rest of the /16 is unused. Phase B's private subnets go at
#             10.0.128.0/20 and 10.0.144.0/20, leaving a wide gap so a
#             subnet's tier stays readable from its address.
#
# Public because both boxes only ever dial out (Tailscale, packages, images),
# and an internet gateway gives them that for free where a NAT gateway costs
# ~$32/mo. "Public" here means only that the route table has a default route
# to the internet gateway. Whether anything can come *in* is the security
# groups' answer, and they have no inbound rules (security_group.tf). The trade
# is written up in the design doc, D10.
#
# One AZ because nothing in Phase A is long-running enough to want two. An AZ
# outage costs a re-run.

resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  # On by default, written out because the boxes resolve package mirrors,
  # Docker Hub and Tailscale's servers through the VPC resolver. Hostnames
  # (enable_dns_hostnames) are not needed: people and scanners use MagicDNS
  # names, never AWS ones.
  enable_dns_support = true

  tags = { Name = var.project }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.project}-igw" }
}

resource "aws_subnet" "public_a" {
  vpc_id = aws_vpc.main.id

  # Derived from the region rather than written out, so changing `region`
  # moves the subnet with it instead of failing at apply.
  availability_zone = "${var.region}a"
  cidr_block        = "10.0.0.0/20"

  # Off, so nothing gets a public address by accident. Each box asks for one
  # explicitly with associate_public_ip_address, next to the comment saying why.
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.project}-public-a"
    Tier = "public"
  }
}

# The default route below is the entire public/private distinction. Move this
# association and the subnet changes tier regardless of what it is called.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project}-public" }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}
