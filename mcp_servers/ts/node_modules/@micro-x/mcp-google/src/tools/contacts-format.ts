import type { people_v1 } from "googleapis";

type Person = people_v1.Schema$Person;

/**
 * Format a contact for search/list results (name, email, phone).
 */
export function formatContactSummary(person: Person): string {
  const names = person.names ?? [];
  const name = names.length > 0 ? (names[0].displayName ?? "(no name)") : "(no name)";

  const resourceName = person.resourceName ?? "";

  const emails = person.emailAddresses ?? [];
  const email = emails.length > 0 ? (emails[0].value ?? "") : "";

  const phones = person.phoneNumbers ?? [];
  const phone = phones.length > 0 ? (phones[0].value ?? "") : "";

  const lines: string[] = [
    `ResourceName: ${resourceName}`,
    `  Name: ${name}`,
  ];
  if (email) {
    lines.push(`  Email: ${email}`);
  }
  if (phone) {
    lines.push(`  Phone: ${phone}`);
  }

  return lines.join("\n");
}

/**
 * Format a contact with full details including etag.
 */
export function formatContactDetail(person: Person): string {
  const names = person.names ?? [];
  const name = names.length > 0 ? (names[0].displayName ?? "(no name)") : "(no name)";

  const resourceName = person.resourceName ?? "";
  const etag = person.etag ?? "";

  const lines: string[] = [
    `ResourceName: ${resourceName}`,
    `Name: ${name}`,
    `Etag: ${etag}`,
  ];

  const emails = person.emailAddresses ?? [];
  for (const e of emails) {
    const label = e.type ?? "other";
    lines.push(`Email (${label}): ${e.value ?? ""}`);
  }

  const phones = person.phoneNumbers ?? [];
  for (const p of phones) {
    const label = p.type ?? "other";
    lines.push(`Phone (${label}): ${p.value ?? ""}`);
  }

  const addresses = person.addresses ?? [];
  for (const a of addresses) {
    const label = a.type ?? "other";
    const formatted = a.formattedValue ?? "";
    lines.push(`Address (${label}): ${formatted}`);
  }

  const orgs = person.organizations ?? [];
  for (const o of orgs) {
    const title = o.title ?? "";
    const orgName = o.name ?? "";
    lines.push(`Organization: ${orgName}${title ? ` (${title})` : ""}`);
  }

  const bios = person.biographies ?? [];
  if (bios.length > 0) {
    lines.push(`Biography: ${bios[0].value ?? ""}`);
  }

  return lines.join("\n");
}
