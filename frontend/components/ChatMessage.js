import ResultsChart from "./ResultsChart";
import ResultsTable from "./ResultsTable";
import SqlBlock from "./SqlBlock";

export function UserMessage({ text }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-ledger-gold/10 border border-ledger-gold/30 px-4 py-2.5 text-parchment-100">
        {text}
      </div>
    </div>
  );
}

export function AssistantMessage({ result }) {
  if (result.failed) {
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-ledger-clay/40 bg-ledger-clay/10 px-4 py-3">
          <p className="flex items-center gap-2 text-sm font-medium text-ledger-clay">
            <span aria-hidden>⚠</span> Query blocked by the safety guardrail
          </p>
          <p className="mt-1.5 text-sm text-parchment-100/90">{result.explanation}</p>
          {result.last_candidate_sql && (
            <pre className="mt-2 overflow-x-auto rounded border border-ledger-clay/30 bg-ink-900/60 px-3 py-2 font-mono text-[12px] text-parchment-300/80">
              {result.last_candidate_sql}
            </pre>
          )}
          <p className="mt-2 text-xs text-parchment-300/60">
            QueryMind only runs read-only, single-statement SELECTs against a known set of tables — try
            rephrasing as a question rather than a command.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-ink-600 bg-ink-800 px-4 py-3">
        <p className="text-sm text-parchment-100">{result.explanation}</p>
        <SqlBlock sql={result.sql} />
        {result.rows?.length > 0 && (
          <>
            <ResultsChart columns={result.columns} rows={result.rows} />
            <ResultsTable columns={result.columns} rows={result.rows} rowCount={result.row_count} />
          </>
        )}
      </div>
    </div>
  );
}

export function PendingMessage() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-ink-600 bg-ink-800 px-4 py-3 text-sm text-parchment-300/70">
        <span className="flex gap-1">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ledger-gold [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ledger-gold [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ledger-gold" />
        </span>
        Running the query
      </div>
    </div>
  );
}
