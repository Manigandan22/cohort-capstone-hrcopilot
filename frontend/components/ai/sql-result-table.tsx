"use client";

import { useState } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { AISqlResult } from "@/lib/api";

const humanize = (column: string) => column.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const formatCell = (value: unknown) => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
};

export function SqlResultTable({ result }: { result: AISqlResult }) {
  const [showSql, setShowSql] = useState(false);

  return (
    <div className="mt-3 space-y-2">
      {result.rows.length > 0 ? (
        <div className="max-h-80 overflow-auto rounded-md border border-border bg-white">
          <Table>
            <TableHeader className="sticky top-0 bg-slate-50">
              <TableRow>
                {result.columns.map((column) => (
                  <TableHead key={column} className="h-9 whitespace-nowrap px-3 text-xs">
                    {humanize(column)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.rows.map((row, index) => (
                <TableRow key={index}>
                  {result.columns.map((column) => (
                    <TableCell key={column} className="px-3 py-2 text-xs">
                      {formatCell(row[column])}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>
          {result.row_count} row{result.row_count === 1 ? "" : "s"}
          {result.truncated ? " (more results exist; showing the first ones)" : ""}
        </span>
        {result.sql ? (
          <button type="button" className="text-indigo-600 hover:underline" onClick={() => setShowSql((v) => !v)}>
            {showSql ? "Hide SQL" : "Show SQL"}
          </button>
        ) : null}
      </div>
      {showSql && result.sql ? (
        <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">{result.sql}</pre>
      ) : null}
    </div>
  );
}
