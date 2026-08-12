import { Alert } from "@/components/ui";

/**
 * Marks a screen whose backend does not exist yet.
 *
 * Shown deliberately rather than quietly presenting invented content as real: a reviewer
 * looking at a health portal should never have to guess which numbers came from the
 * database and which are placeholders.
 */
export function PreviewNotice({ children }: { children: React.ReactNode }) {
  return (
    <Alert tone="warn">
      <span>
        <strong className="font-bold">Placeholder screen.</strong> {children}
      </span>
    </Alert>
  );
}
