export default function ResultsTable({ columns, rows, rowCount }) {
  if (!rows || rows.length === 0) {
    return <p className="mt-2 text-sm text-parchment-300/70">No rows returned.</p>;
  }

  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-ink-600">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="bg-ink-700">
            {columns.map((col) => (
              <th
                key={col}
                className="whitespace-nowrap border-b border-ink-600 px-3 py-2 font-mono text-xs uppercase tracking-wide text-ledger-gold"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? "bg-ink-800/40" : "bg-ink-800/10"}>
              {columns.map((col) => (
                <td key={col} className="whitespace-nowrap border-b border-ink-700/60 px-3 py-1.5 font-mono text-parchment-100">
                  {formatCell(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rowCount > rows.length && (
        <div className="border-t border-ink-600 bg-ink-700/50 px-3 py-1.5 text-xs text-parchment-300/60">
          Showing {rows.length} of {rowCount} row(s).
        </div>
      )}
    </div>
  );
}

function formatCell(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  return String(value);
}
