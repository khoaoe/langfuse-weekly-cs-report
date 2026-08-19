import { Fragment, type ReactNode } from "react";

import styles from "./why-drawer.module.css";

/** Narrow markdown subset actually produced by cs-agent-master's drafted
 * answers and skill docs: **bold**, "- "/"• " bullet lists, and blank-line
 * paragraphs. Not a general markdown renderer -- headings, links, tables,
 * nested lists etc. are intentionally out of scope. */

const BOLD_RE = /(\*\*[^*]+\*\*)/g;
const BULLET_RE = /^[-•]\s+/;

function renderInline(text: string, keyPrefix: string): ReactNode {
  const parts = text.split(BOLD_RE);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>;
    }
    return part ? <Fragment key={`${keyPrefix}-${index}`}>{part}</Fragment> : null;
  });
}

function renderLines(lines: readonly string[], keyPrefix: string): ReactNode {
  return lines.map((line, index) => (
    <Fragment key={`${keyPrefix}-line-${index}`}>
      {index > 0 ? <br /> : null}
      {renderInline(line, `${keyPrefix}-${index}`)}
    </Fragment>
  ));
}

export function MarkdownLite({ text }: { readonly text: string }) {
  const blocks = text
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

  return (
    <div className={styles.markdown}>
      {blocks.map((block, blockIndex) => {
        const lines = block
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        const isBulletList = lines.length > 0 && lines.every((line) => BULLET_RE.test(line));

        if (isBulletList) {
          return (
            <ul key={blockIndex} className={styles.markdownList}>
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  {renderInline(line.replace(BULLET_RE, ""), `${blockIndex}-${lineIndex}`)}
                </li>
              ))}
            </ul>
          );
        }

        return (
          <p key={blockIndex} className={styles.markdownParagraph}>
            {renderLines(lines, `${blockIndex}`)}
          </p>
        );
      })}
    </div>
  );
}
