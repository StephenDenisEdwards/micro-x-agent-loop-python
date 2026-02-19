def format_contact_summary(person: dict) -> str:
    """Format a contact for search/list results (name, email, phone)."""
    names = person.get("names", [])
    name = names[0].get("displayName", "(no name)") if names else "(no name)"

    resource_name = person.get("resourceName", "")

    emails = person.get("emailAddresses", [])
    email = emails[0].get("value", "") if emails else ""

    phones = person.get("phoneNumbers", [])
    phone = phones[0].get("value", "") if phones else ""

    lines = [f"ResourceName: {resource_name}", f"  Name: {name}"]
    if email:
        lines.append(f"  Email: {email}")
    if phone:
        lines.append(f"  Phone: {phone}")

    return "\n".join(lines)


def format_contact_detail(person: dict) -> str:
    """Format a contact with full details including etag."""
    names = person.get("names", [])
    name = names[0].get("displayName", "(no name)") if names else "(no name)"

    resource_name = person.get("resourceName", "")
    etag = person.get("etag", "")

    lines = [
        f"ResourceName: {resource_name}",
        f"Name: {name}",
        f"Etag: {etag}",
    ]

    emails = person.get("emailAddresses", [])
    if emails:
        for e in emails:
            label = e.get("type", "other")
            lines.append(f"Email ({label}): {e.get('value', '')}")

    phones = person.get("phoneNumbers", [])
    if phones:
        for p in phones:
            label = p.get("type", "other")
            lines.append(f"Phone ({label}): {p.get('value', '')}")

    addresses = person.get("addresses", [])
    if addresses:
        for a in addresses:
            label = a.get("type", "other")
            formatted = a.get("formattedValue", "")
            lines.append(f"Address ({label}): {formatted}")

    orgs = person.get("organizations", [])
    if orgs:
        for o in orgs:
            title = o.get("title", "")
            org_name = o.get("name", "")
            lines.append(f"Organization: {org_name}" + (f" ({title})" if title else ""))

    bios = person.get("biographies", [])
    if bios:
        lines.append(f"Biography: {bios[0].get('value', '')}")

    return "\n".join(lines)
