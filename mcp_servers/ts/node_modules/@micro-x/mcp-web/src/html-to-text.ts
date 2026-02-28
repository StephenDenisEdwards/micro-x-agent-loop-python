import * as cheerio from "cheerio";

/**
 * Convert HTML to readable plain text.
 * Handles block elements, lists, tables, and whitespace normalization.
 * Port of Python html_utilities.html_to_text().
 */
export function htmlToText(html: string): { text: string; title: string } {
  const $ = cheerio.load(html);

  // Extract title
  const title = $("title").first().text().trim();

  // Remove non-visible elements
  $("script, style, head").remove();

  // Replace <br> with newlines
  $("br").replaceWith("\n");

  // Add newlines around block elements
  $("p, div, tr, h1, h2, h3, h4, h5, h6, blockquote").each((_i, el) => {
    $(el).prepend("\n");
    $(el).append("\n");
  });

  // Preserve link URLs: <a href="url">text</a> → text url
  $("a[href]").each((_i, el) => {
    const $el = $(el);
    const href = $el.attr("href") ?? "";
    const linkText = $el.text().trim();
    if (href && href !== linkText && !href.startsWith("#")) {
      $el.replaceWith(linkText ? `${linkText} ${href}` : href);
    }
  });

  // Bullet list items
  $("li").each((_i, el) => {
    $(el).prepend("\n- ");
  });

  // Table cells
  $("td, th").each((_i, el) => {
    $(el).append("\t");
  });

  // Get body text (or full text)
  let text = ($("body").text() || $.text());

  // Normalize whitespace
  text = text.replace(/\t+/g, "  ");
  text = text.replace(/ {3,}/g, "  ");
  text = text.replace(/\n{3,}/g, "\n\n");

  return { text: text.trim(), title };
}
