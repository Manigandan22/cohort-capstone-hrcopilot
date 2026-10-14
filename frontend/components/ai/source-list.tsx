import { FileText } from "lucide-react";

import type { AIPolicySource } from "@/lib/api";

export function SourceList({ sources }: { sources: AIPolicySource[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="mt-3 border-t border-border pt-3">
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Sources</p>
      <ul className="flex flex-wrap gap-2">
        {sources.map((source) => (
          <li
            key={`${source.title}-${source.filename}`}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-slate-50 px-2 py-1 text-xs text-slate-700"
          >
            <FileText className="h-3.5 w-3.5 text-indigo-500" />
            <span className="font-medium">{source.title}</span>
            <span className="text-muted-foreground">· {source.category}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
